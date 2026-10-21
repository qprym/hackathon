import csv
import hashlib
import io
import ipaddress
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
from .db import utcnow
from .models import Company, Document, Event, Link
from .retrieval import classify, tokens

FEEDS = {"cbr": "https://www.cbr.ru/rss/RssPress", "vedomosti": "https://www.vedomosti.ru/rss/news"}
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


def import_document(db, *, title, content, kind, publisher, published_at, url=None, synthetic=False, chunks=None):
    if published_at.tzinfo:
        published_at = published_at.astimezone(UTC).replace(tzinfo=None)
    if published_at > utcnow() + timedelta(days=1):
        raise ValueError("Дата публикации находится в будущем")
    text = clean_text(content)
    if len(text) < 60:
        raise ValueError("Недостаточно текста для анализа: минимум 60 символов")
    content_hash = digest(f"{kind}|{synthetic}|{text}")
    existing = db.scalar(select(Document).where(Document.content_hash == content_hash))
    if existing:
        return existing, False
    doc = Document(title=title, content=text, kind=kind, publisher=publisher, url=url,
                   published_at=published_at, content_hash=content_hash, topics=classify(title + " " + text),
                   synthetic=synthetic, chunks=chunks or chunks_for(text))
    db.add(doc)
    db.flush()
    if kind == "news":
        event = None
        candidates = db.scalars(select(Event).where(Event.synthetic == synthetic,
            Event.published_at.between(published_at - timedelta(days=2), published_at + timedelta(days=2)))).all()
        for candidate in candidates:
            # Conservative grouping: numeric anchors must agree; differing reports stay separate.
            numbers_match = re.findall(r"\d+(?:[.,]\d+)?", candidate.title) == re.findall(r"\d+(?:[.,]\d+)?", title)
            similarity = SequenceMatcher(None, candidate.title.lower(), title.lower()).ratio()
            if numbers_match and similarity > .88:
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
    for line, row in enumerate(reader, 2):
        row = {k.strip(): (v.strip() if v else None) for k, v in row.items() if k is not None}
        try:
            with db.begin_nested():
                if kind == "companies":
                    company_id = row.get("SYNTHETIC_U")
                    if not company_id or len(company_id) > 100:
                        raise ValueError("Некорректный SYNTHETIC_U")
                    if company_id in seen:
                        raise ValueError("Повторяющийся SYNTHETIC_U внутри файла")
                    seen.add(company_id)
                    features = {}
                    for key, val in row.items():
                        if key in PRODUCTS or key == "FTS_FLAG":
                            val = parse_bool(val)
                        elif key == "REVENUE_COMPANY":
                            val = parse_number(val)
                            if val is not None and val < 0:
                                raise ValueError("Отрицательная выручка")
                        features[key] = feature(val, f"{filename}, строка {line}, {key}", label=PRODUCTS.get(key, key))
                    company = db.get(Company, company_id) or Company(id=company_id)
                    company.name = f"Компания {company_id}"
                    company.industry = (row.get("MAINOKVED_NAME") or "Не указана")[:250]
                    company.region = (row.get("REGION") or "Не указан")[:150]
                    if row.get("GROUP_ID") and len(row["GROUP_ID"]) > 100:
                        raise ValueError("Слишком длинный GROUP_ID")
                    company.group_id = row.get("GROUP_ID")
                    company.features = features
                    company.synthetic = synthetic
                    db.add(company)
                    ids.append(company_id)
                else:
                    source = row.get("PAYER" if kind == "payments" else "SYNTHETIC_F")
                    target = row.get("BENEFICIARY" if kind == "payments" else "SYNTHETIC_U")
                    if not source or not target or max(len(source), len(target)) > 100:
                        raise ValueError("Отсутствует или слишком длинный идентификатор связи")
                    link_id = digest(f"{kind}:{source}:{target}")
                    if link_id in seen:
                        raise ValueError("Повторная пара идентификаторов: агрегируйте платежи до импорта")
                    seen.add(link_id)
                    amount = parse_number(row.get("PAY_AMT"))
                    count = parse_number(row.get("PAY_CNT"))
                    if amount is not None and amount < 0 or count is not None and (count < 0 or not count.is_integer()):
                        raise ValueError("Некорректные PAY_AMT/PAY_CNT")
                    link = db.get(Link, link_id) or Link(id=link_id)
                    link.kind = "payment" if kind == "payments" else "person"
                    link.source_id, link.target_id = source, target
                    link.amount, link.count = amount, int(count) if count is not None else None
                    link.details = {"source": filename, "line": line,
                                    "unknown_target": db.get(Company, target) is None}
                    db.add(link)
                db.flush()
            imported += 1
        except (ValueError, TypeError) as exc:
            errors.append({"line": line, "message": str(exc)})
    db.commit()
    return {"kind": kind, "imported": imported, "errors": errors, "company_ids": ids, "synthetic": synthetic,
            "warnings": ["Единицы выручки и платежей, а также период платежей должны быть подтверждены по описанию набора."]}


def extract_pdf(raw):
    reader = PdfReader(io.BytesIO(raw))
    if len(reader.pages) > 150:
        raise ValueError("Максимум 150 страниц")
    texts, chunks = [], []
    for n, page in enumerate(reader.pages, 1):
        text = clean_text(page.extract_text() or "")
        texts.append(text)
        chunks.extend(chunks_for(text, n))
    if sum(map(len, texts)) < 100:
        raise ValueError("В PDF нет извлекаемого текста. Нужен текстовый PDF или предварительное распознавание разрешенной моделью.")
    return "\n".join(texts), chunks


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


def import_feed(db, key):
    if key not in FEEDS:
        raise ValueError("Неизвестный источник")
    root = ElementTree.fromstring(safe_fetch(FEEDS[key]))
    imported, errors = 0, []
    for item in root.findall(".//item")[:30]:
        title = item.findtext("title") or "Без заголовка"
        try:
            date = parsedate_to_datetime(item.findtext("pubDate") or "")
            content = clean_text(item.findtext("description") or "")
            url = item.findtext("link")
            # Full text is used only on open pages of the same allowlisted publisher.
            if url:
                try:
                    page = BeautifulSoup(safe_fetch(url), "html.parser")
                    article = page.find("article") or page.find("div", class_="landing-text")
                    if article:
                        extracted = clean_text(str(article))
                        if len(extracted) >= len(content):
                            content = extracted
                except (ValueError, httpx.HTTPError):
                    pass
            _, created = import_document(db, title=title, content=content, kind="news",
                publisher="Банк России" if key == "cbr" else "Ведомости", published_at=date, url=url)
            imported += int(created)
        except (ValueError, TypeError, httpx.HTTPError) as exc:
            errors.append({"title": title, "message": str(exc)[:200]})
    return {"imported": imported, "errors": errors}
