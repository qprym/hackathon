import csv
import hashlib
import io
import ipaddress
import json
import re
import socket
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree
from pypdf import PdfReader
from sqlalchemy import select
from .context import PRODUCTS, feature
from .config import settings
from .db import utcnow
from .models import Company, Document, Event, Link
from .retrieval import classify, tokens

FEEDS = {"cbr": "https://www.cbr.ru/rss/RssPress", "vedomosti": "https://www.vedomosti.ru/rss/news"}
FEED_NAMES = {"cbr": "Банк России", "vedomosti": "Ведомости"}
ALLOWED_HOSTS = {"www.cbr.ru", "cbr.ru", "www.vedomosti.ru", "vedomosti.ru"}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def clean_text(text):
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return re.sub(r"[ \t]+", " ", soup.get_text(" ", strip=True)).strip()


def chunks_for(text, page=None):
    # Overlap preserves sentence context and the exact cited span remains in the document.
    return [{"text": text[i:i + 1000], "page": page, "offset": i}
            for i in range(0, len(text), 850) if text[i:i + 1000].strip()]


def pdf_chunks(text, page):
    """Keep paragraphs intact and retain exact offsets in the extracted page."""
    result = []
    for match in re.finditer(r'\S(?:.*?\S)?(?=\n\s*\n|$)', text, re.S):
        paragraph = match.group()
        start = 0
        while start < len(paragraph):
            end = min(start + 1400, len(paragraph))
            if end < len(paragraph):
                stops = list(re.finditer(r'[.!?]\s+', paragraph[start:end]))
                if stops and stops[-1].end() > 500:
                    end = start + stops[-1].end()
            piece = paragraph[start:end].strip()
            if len(piece) >= 60:
                result.append({'text':piece,'page':page,'offset':match.start()+start})
            start = end
    return result


def import_document(db, *, title, content, kind, publisher, published_at, url=None, synthetic=False, chunks=None, ingestion_meta=None):
    if published_at.tzinfo:
        published_at = published_at.astimezone(UTC).replace(tzinfo=None)
    if published_at > utcnow() + timedelta(days=1):
        raise ValueError("Дата публикации находится в будущем")
    text = clean_text(content)
    if len(text) < 60:
        raise ValueError("Недостаточно текста для анализа: минимум 60 символов")
    title, publisher = title.strip(), publisher.strip()
    # Deduplicate the same publication while retaining independent publishers and dates.
    identity = [kind, synthetic, text, title, publisher, url or "", published_at.isoformat()]
    content_hash = digest(json.dumps(identity, ensure_ascii=False))
    existing = db.scalar(select(Document).where(Document.content_hash == content_hash))
    if existing:
        if chunks is not None:
            existing.chunks = chunks
        if ingestion_meta:
            existing.ingestion_meta = ingestion_meta
        db.commit()
        return existing, False
    legacy = db.scalar(select(Document).where(Document.content_hash == digest(f"{kind}|{synthetic}|{text}")))
    if legacy and (legacy.title, legacy.publisher, legacy.url or "", legacy.published_at) == (title, publisher, url or "", published_at):
        legacy.content_hash = content_hash
        if ingestion_meta:
            legacy.ingestion_meta = ingestion_meta
        db.commit()
        return legacy, False
    doc = Document(title=title, content=text, kind=kind, publisher=publisher, url=url,
                   published_at=published_at, content_hash=content_hash, topics=classify(title + " " + text),
                   synthetic=synthetic, chunks=chunks or chunks_for(text), ingestion_meta=ingestion_meta or {})
    db.add(doc)
    db.flush()
    if kind == "news":
        event = None
        candidates = db.scalars(select(Event).where(Event.synthetic == synthetic,
            Event.published_at.between(published_at - timedelta(days=2), published_at + timedelta(days=2)))).all()
        for candidate in candidates:
            # Only the same publisher URL is an identity. Semantic merging is model-reviewed later.
            same_publication = any(
                (source:=db.get(Document,key)) and ((bool(url) and source.url==url and source.publisher==publisher)
                or (source.content==text and source.title==title and source.published_at==published_at))
                for key in candidate.document_ids)
            if same_publication:
                event = candidate
                break
        if event:
            event.document_ids = [*event.document_ids, doc.id]
            event.topics = sorted(set(event.topics + doc.topics))
        else:
            db.add(Event(title=title, document_ids=[doc.id], topics=doc.topics,
                         published_at=published_at, synthetic=synthetic))
    db.commit()
    return doc, True


def parse_number(value):
    if value is None or str(value).strip().lower() in ("", "nan", "none", "null", "н/д"):
        return None
    raw = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    number = float(raw)
    if not (-1e18 < number < 1e18):
        raise ValueError("Числовое значение вне допустимого диапазона")
    return number


def parse_bool(value):
    text = str(value or "").strip().lower()
    if text in ("1", "1.0", "да", "true", "yes"):
        return True
    if text in ("0", "0.0", "нет", "false", "no"):
        return False
    return None


def import_csv(db, raw, filename, synthetic=False):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    columns = {c.strip() for c in (reader.fieldnames or [])}
    if {"PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"} <= columns:
        kind = "payments"
    elif {"SYNTHETIC_F", "SYNTHETIC_U"} <= columns:
        kind = "persons"
    elif {"SYNTHETIC_U", "MAINOKVED_CODE"} <= columns:
        kind = "companies"
    else:
        raise ValueError("Неизвестная схема CSV: ожидаются компании, платежи или связи физлиц")
    errors, imported, ids, seen = [], 0, [], set()
    error_count = 0
    known_companies = set(db.scalars(select(Company.id))) if kind != "companies" else set()
    model = Company if kind == "companies" else Link
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    batch = []

    def flush_batch():
        if not batch:
            return
        stmt = insert(model).values(batch)
        db.execute(stmt.on_conflict_do_update(index_elements=[model.id],
            set_={key: getattr(stmt.excluded, key) for key in batch[0] if key != "id"}))
        batch.clear()

    for line, row in enumerate(reader, 2):
        try:
            if None in row:
                raise ValueError("Лишние значения: проверьте разделитель и кавычки")
            row = {k.strip(): (v.strip() if v and v.strip().lower() not in ("nan", "none", "null") else None)
                   for k, v in row.items()}
            if kind == "companies":
                company_id = row.get("SYNTHETIC_U")
                if not company_id or len(company_id) > 100:
                    raise ValueError("Некорректный SYNTHETIC_U")
                if company_id in seen:
                    raise ValueError("Повторяющийся SYNTHETIC_U внутри файла")
                features = {}
                for key, val in row.items():
                    if key in PRODUCTS or key == "FTS_FLAG":
                        val = parse_bool(val)
                    elif key == "REVENUE_COMPANY":
                        val = parse_number(val)
                        if val is not None and val < 0:
                            raise ValueError("Отрицательная выручка")
                    features[key] = feature(val, f"{filename}, строка {line}, {key}", label=PRODUCTS.get(key, key))
                if row.get("GROUP_ID") and len(row["GROUP_ID"]) > 100:
                    raise ValueError("Слишком длинный GROUP_ID")
                if "REVENUE_COMPANY" in features:
                    features["REVENUE_COMPANY"]["unit"] = "unknown"
                batch.append(dict(id=company_id, name=f"Компания {company_id}",
                    industry=(row.get("MAINOKVED_NAME") or "Не указана")[:250],
                    region=(row.get("REGION") or "Не указан")[:150], group_id=row.get("GROUP_ID"),
                    features=features, synthetic=synthetic, updated_at=utcnow()))
                seen.add(company_id)
                ids.append(company_id)
            else:
                source = row.get("PAYER" if kind == "payments" else "SYNTHETIC_F")
                target = row.get("BENEFICIARY" if kind == "payments" else "SYNTHETIC_U")
                if not source or not target or max(len(source), len(target)) > 100:
                    raise ValueError("Отсутствует или слишком длинный идентификатор связи")
                link_id = digest(f"{kind}:{source}:{target}")
                if link_id in seen:
                    raise ValueError("Повторная пара идентификаторов: агрегируйте платежи до импорта")
                amount = parse_number(row.get("PAY_AMT"))
                count = parse_number(row.get("PAY_CNT"))
                if amount is not None and amount < 0 or count is not None and (count < 0 or not count.is_integer()):
                    raise ValueError("Некорректные PAY_AMT/PAY_CNT")
                batch.append(dict(id=link_id, kind="payment" if kind == "payments" else "person",
                    source_id=source, target_id=target, amount=amount, count=int(count) if count is not None else None,
                    details={"source": filename, "line": line, "unit": "unknown",
                             "unknown_target": target not in known_companies}))
                seen.add(link_id)
            imported += 1
        except (ValueError, TypeError) as exc:
            error_count += 1
            if len(errors) < 200:
                errors.append({"line": line, "message": str(exc)})
        if len(batch) >= 250:
            flush_batch()
    flush_batch()
    db.commit()
    db.expire_all()
    return {"kind": kind, "imported": imported, "errors": errors, "error_count": error_count,
            "errors_truncated": error_count > len(errors), "company_ids": ids, "synthetic": synthetic,
            "warnings": ["Единицы выручки и платежей, а также период платежей должны быть подтверждены по описанию набора."]}


def extract_pdf(raw, with_pages=False):
    reader = PdfReader(io.BytesIO(raw))
    if len(reader.pages) > 150:
        raise ValueError("Максимум 150 страниц")
    texts, chunks, pages = [], [], []
    extracted = [clean_text(page.extract_text() or "") for page in reader.pages]
    scanned = [n for n, text in enumerate(extracted, 1) if len(text) < 100]
    if scanned:
        from .ocr import recognize_pages
        recognized = recognize_pages(raw, scanned)
    else:
        recognized = {}
    for n, text in enumerate(extracted, 1):
        if n in recognized:
            text = clean_text(recognized[n]['text'])
        texts.append(text)
        pages.append({'number': n, 'text': text, 'confidence': recognized[n]['confidence'] if n in recognized else 100,
            'text_status':'empty' if not text.strip() else 'ocr' if n in recognized else 'extracted',
            'visual_status':'not_verified','numeric_tables_status':'not_verified'})
        page_chunks = pdf_chunks(text, n)
        for chunk in page_chunks:
            chunk['extraction'] = 'ocr' if n in recognized else 'text'
            chunk['confidence'] = recognized[n]['confidence'] if n in recognized else None
            chunk['visual_status'] = 'not_verified'
            chunk['numeric_tables_status'] = 'not_verified'
        chunks.extend(page_chunks)
    if sum(map(len, texts)) < 100:
        raise ValueError("В PDF нет извлекаемого текста. Нужен текстовый PDF или предварительное распознавание разрешенной моделью.")
    result = ("\n".join(texts), chunks)
    return (*result, pages) if with_pages else result


def safe_fetch(url):
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        for _ in range(4):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.port not in (None, 443) or parsed.username:
                raise ValueError("Источник не входит в список разрешенных HTTPS-доменов")
            for result in socket.getaddrinfo(parsed.hostname, 443):
                if not ipaddress.ip_address(result[4][0]).is_global:
                    raise ValueError("Адрес источника не является публичным")
            with client.stream("GET", url, headers={"User-Agent": "AlfaInsightHackathon/1.0"}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 5_000_000:
                        raise ValueError("Источник превышает ограничение 5 МБ")
                return bytes(body)
        raise ValueError("Слишком много перенаправлений")


def extract_article(raw, key):
    """Read public article paragraphs only; scripts and subscription content are not sources."""
    page = BeautifulSoup(raw, "html.parser")
    for script in page.select('script[type="application/ld+json"]'):
        try:
            stack = [json.loads(script.string or script.get_text())]
            while stack:
                value = stack.pop()
                if isinstance(value, list):
                    stack.extend(value)
                elif isinstance(value, dict):
                    if value.get("isAccessibleForFree") in (False, "false", "False"):
                        raise ValueError("Полный текст доступен по подписке")
                    stack.extend(v for v in value.values() if isinstance(v, (dict, list)))
        except (json.JSONDecodeError, TypeError):
            continue
    for hidden in page.select('[hidden], [aria-hidden="true"], script, style, nav, footer, header'):
        hidden.decompose()
    if page.select_one('.paywall, .article-paywall, [data-paywall]'):
        raise ValueError("Полный текст ограничен издателем")
    if key == "vedomosti":
        body = page.select_one('.article__body')
        if body is None:
            raise ValueError("Не найден контейнер статьи «Ведомостей»")
        paragraphs = body.select('.article__boxes .box-paragraph__text')
        selector = "vedomosti:article__boxes/box-paragraph__text"
        text = "\n\n".join(clean_text(str(p)) for p in paragraphs if p.get_text(strip=True))
    elif key == "cbr":
        body = page.select_one('.landing-text') or page.find('article')
        text = clean_text(str(body)) if body else ""
        selector = "cbr:landing-text"
    else:
        raise ValueError("Нет адаптера источника")
    if len(text) < 100:
        raise ValueError("Не найден достаточный текст статьи на странице")
    return text, {"coverage": "article", "method": selector}


def import_feed(db, key, on_progress=None):
    if key not in FEEDS:
        raise ValueError("Неизвестный источник")
    root = ElementTree.fromstring(safe_fetch(FEEDS[key]))
    imported, unchanged, articles, summaries, errors, warnings = 0, 0, 0, 0, [], []
    items = root.findall(".//item")[:settings().rss_item_limit]
    for item in items:
        if on_progress:
            on_progress()
        title = item.findtext("title") or "Без заголовка"
        url = item.findtext("link")
        try:
            date = parsedate_to_datetime(item.findtext("pubDate") or "")
            content = clean_text(item.findtext("description") or "")
            meta = {"coverage": "summary", "method": "rss:description"}
            warning = None
            if url:
                try:
                    content, meta = extract_article(safe_fetch(url), key)
                except (ValueError, httpx.HTTPError, OSError) as exc:
                    warning = str(exc)[:200]
            else:
                warning = "В RSS отсутствует ссылка на статью"
            if meta['coverage'] == 'summary' and len(content) < 60:
                raise ValueError(warning or "В RSS нет достаточного текста")
            meta.update({"feed": key, "fetched_at": utcnow().isoformat() + "Z"})
            if warning:
                meta["warning"] = warning
                warnings.append({"title": title, "url": url, "message": warning})
            _, created = import_document(db, title=title, content=content, kind="news",
                publisher=FEED_NAMES[key], published_at=date, url=url, ingestion_meta=meta)
            imported += int(created)
            unchanged += int(not created)
            articles += int(meta["coverage"] == "article")
            summaries += int(meta["coverage"] == "summary")
        except (ValueError, TypeError, httpx.HTTPError, OSError) as exc:
            db.rollback()
            errors.append({"title": title, "url": url, "message": str(exc)[:200]})
    return {"imported": imported, "unchanged": unchanged, "articles": articles, "summaries": summaries,
            "examined": len(items), "errors": errors, "warnings": warnings}
