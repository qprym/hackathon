import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import LlmSettings from './LlmSettings';
import FeedSettings from './FeedSettings';
import {
  ArrowDownLeft,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  BookOpen,
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  ExternalLink,
  FileText,
  FlaskConical,
  Globe2,
  Layers3,
  LoaderCircle,
  LogOut,
  MessageSquare,
  Plus,
  RefreshCw,
  Search,
  Settings as SettingsIcon,
  Send,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  TrendingUp,
  X,
} from "lucide-react";

type Role = "CEO" | "CFO" | "TREASURER";
type User = {
  id: string;
  name: string;
  username: string;
  is_admin: boolean;
  mode: string;
};
type Company = {
  id: string;
  name: string;
  industry: string;
  region: string;
  synthetic: boolean;
  ready_roles?: Role[];
};
type Feature = {
  value: unknown;
  source: string;
  status: string;
  label: string;
  unit?: string;
};
type Context = Company & {
  features: Record<string, Feature>;
  products: string[];
  missing: string[];
  limitations: string[];
  counterparties: {
    id: string;
    industry: string;
    amount: number;
    direction: string;
  }[];
  group: { id: string; industry: string }[];
  shared_person_links: { company_id: string; relation: string }[];
};
type EventItem = {
  id: string;
  document_id: string | null;
  title: string;
  summary: string;
  summary_truncated?: boolean;
  source_coverage?: string;
  reading_notes?: {term:string;meaning:string}[];
  analysis?: {status:'saved'|'available'|'unavailable';run_id?:string;message?:string;mode?:string};
  publisher: string;
  score: number;
  reasons: string[];
  feature_keys?: string[];
  topics: string[];
  published_at: string;
  synthetic: boolean;
  source_count: number;
  related_publications?: { document_id: string; title: string; publisher: string }[];
  ranking_method?: string;
  ranking_status?: string;
  ranking_historical?: boolean;
  ordering?: { note: string; repeated_financial_topics: string[] };
  previous_editions?: { id: string; document_id: string | null; title: string; published_at: string; publisher: string }[];
  ranking_grounds?: { document_id: string | null; quote: string; publisher: string; location?: string }[];
  exposure: { level: "direct" | "indirect" | "unknown"; note: string };
};
type SelectionStatus = { method: string; model: string; total: number; completed: number; queued: number; failed: number; not_requested: number; historical?: number; budget_blocked?: number; can_request: boolean };
type ListSelection = { status: string; version: string; job_id: string | null; historical?: boolean; insufficient?: number };
type FeedResponse = { items: EventItem[]; topics: Record<string, string>; selection: SelectionStatus; list_selection?: ListSelection | null;
  available_topics: string[];
  relationship_counts?: {direct:number;indirect:number;unknown:number};
  processing?: {news_updates:boolean;analysis_mode:'saved_only'|'demo'|'llm'};
  personalization?: { status: string; selected_count: number; article_count: number; assessed_count: number };
  feed_version: string; total: number; next_offset: number | null; pipeline: { automatic: boolean; model_available: boolean; provider_mode: string; paused_reason?:string|null } };
type Evidence = {
  id: string;
  document_id: string;
  title: string;
  publisher: string;
  kind: string;
  excerpt: string;
  url: string | null;
  published_at: string;
  page: number | null;
  synthetic: boolean;
  coverage?: string;
  relevance?: { level: "direct" | "background"; reason: string };
};
type Claim = {
  text: string;
  evidence_ids: string[];
  feature_keys: string[];
  assumption: boolean;
};
type Insight = {
  fixture?: string;
  fixture_notice?: string;
  headline: string;
  facts: Claim[];
  bank_view: Claim[];
  impact: Claim[];
  risks: Claim[];
  opportunities: Claim[];
  actions: Claim[];
  answer: Claim[];
  limitations: string[];
  evidence: Evidence[];
  context_features: Record<string, Feature>;
  verification: string;
  mode: string;
  company_name: string;
  role: string;
};
type Run = {
  id: string;
  company_id: string;
  role: Role;
  event_title: string;
  status: string;
  stage: string;
  result: Insight | null;
  error: string | null;
  question: string | null;
  trace: { step: string; at: string; details: unknown }[];
  search_outdated?: boolean;
  validation_outdated?: boolean;
  feedback?: { category: string; comment: string } | null;
};
type Source = {
  id: string;
  title: string;
  content: string;
  reading_notes?: {term:string;meaning:string}[];
  publisher: string;
  url: string | null;
  synthetic: boolean;
  ingestion: { coverage?: string; fetched_at?: string; warning?: string; original_file?: string; extraction?: string; date_source?: string; pages?: { number: number; text_status?: string; visual_status?: string; numeric_tables_status?: string }[] };
  chunks: { page: number | null; text: string }[];
};
type FeedStatus = {
  automatic: boolean;
  interval_seconds: number;
  items: {
    key: string;
    name: string;
    status: string;
    last_finished_at: string | null;
    next_refresh_at: string | null;
    report: { articles?: number; summaries?: number; imported?: number };
    error: string | null;
  }[];
};
type Metrics = {
  llm_allowance: { request_limit: number; requests_used: number; requests_remaining: number; spent_rub: number; test_limit_rub: number; budget_enforced: boolean; provider_mode: string };
  runs: Record<string, number>;
  feedback: Record<string, number>;
  budgets: { day: string; spent_rub: number }[];
  latency_avg_seconds: number | null;
  insufficient_count: number;
  source_errors: number;
  source_errors_24h: number;
  by_mode: Record<string, { total: number; checked: number; insufficient: number; latency_samples: number;
    latency_avg_seconds: number | null; latency_p50_seconds: number | null; latency_p95_seconds: number | null }>;
  documents: number;
  events: number;
  quality_note: string;
};

const roles: Record<Role, string> = {
  CEO: "Генеральный директор",
  CFO: "Финансовый директор",
  TREASURER: "Казначей",
};
const labels: Record<string, string> = {
  REVENUE_COMPANY: "Годовая выручка",
  MAINOKVED_CODE: "ОКВЭД",
  MAINOKVED_NAME: "Вид деятельности",
  REGION: "Регион",
  FTS_FLAG: "Сведения ФТС",
  FTS_COUNTRY_NAME: "Страна в данных ФТС",
  CL_PRODUCT_LOA_MARK: "Кредитные продукты",
  CL_PRODUCT_DEP_MARK: "Депозиты",
  CL_PRODUCT_LEA_MARK: "Лизинг",
  CL_PRODUCT_GAR_MARK: "Банковские гарантии",
  CL_PRODUCT_RKO_MARK: "Расчетный счет",
  COMPANY_AGE_YEARS_GRADATION: "Возраст компании",
  AMOUNT_WORKERS_FNS_GRADATION: "Численность сотрудников",
  outgoing_concentration: "Концентрация платежей",
  counterparty_count: "Контрагенты в выборке",
};

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Alfa-Request": "1" };
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    ...options,
    credentials: "include",
    headers: { ...headers, ...options.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : response.status === 401
          ? "Войдите в сервис"
          : "Проверьте данные запроса или подключение к серверу",
    );
  }
  return response.json();
}
const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
const date = (value: string) =>
  new Date(value).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
  });
const formatValue = (key: string, value: unknown, unit?: string): string =>
  value === null || value === undefined
    ? "Нет данных"
    : typeof value === "boolean"
      ? value
        ? "Да"
        : "Нет"
      : key === "REVENUE_COMPANY"
        ? unit === "unknown" ? `${Number(value).toLocaleString("ru-RU")} · ед. не указаны`
          : `${(Number(value) / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млрд ₽`
        : key === "outgoing_concentration"
          ? `${Math.round(Number(value) * 100)}%`
          : String(value);

function Logo() {
  return (
    <div className="brand">
      <img className="brand-symbol" src="/alfa-symbol.png" width="39" height="40" alt="Альфа-Банк" />
      <span>
        Альфа<span className="brand-light">Бизнес</span>
      </span>
    </div>
  );
}
function Spinner({ text = "Загрузка…" }: { text?: string }) {
  return (
    <div className="loading">
      <LoaderCircle className="spin" size={22} />
      <span>{text}</span>
    </div>
  );
}
function ErrorBox({ error, onClose }: { error: string; onClose?: () => void }) {
  return (
    <div role="alert" className="error">
      <CircleHelp size={18} />
      <span>{error}</span>
      {onClose && (
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Закрыть ошибку"
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
}

function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [username, setUsername] = useState("demo"),
    [password, setPassword] = useState("demo-alfa-2026");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await post<User>("/auth/login", { username, password }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-shell">
      <section className="login-story">
        <Logo />
        <div className="login-copy">
          <span className="eyebrow">АЛЬФА · КОНТЕКСТ</span>
          <h1>
            Большая картина.
            <br />
            <span>Ваши решения.</span>
          </h1>
          <p>
            События, аналитика и контекст вашей компании — чтобы видеть то, что
            действительно важно.
          </p>
          <div className="story-orbit">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="orbit-core">
              <Sparkles size={42} />
            </div>
            <span className="orbit-tag tag-one">
              <Globe2 size={16} /> События
            </span>
            <span className="orbit-tag tag-two">
              <Building2 size={16} /> Ваш бизнес
            </span>
            <span className="orbit-tag tag-three">
              <TrendingUp size={16} /> Влияние
            </span>
          </div>
        </div>
        <small>Прототип для Альфа Хак · 2026</small>
      </section>
      <section className="login-form">
        <div>
          <span className="pill red">
            <FlaskConical size={14} /> Демонстрационный кабинет
          </span>
          <h2>Войти в контекст</h2>
          <p className="muted">
            Выберите компанию и посмотрите на события
            <br />
            через призму вашего бизнеса.
          </p>
          <form onSubmit={submit}>
            <label>
              Логин
              <input
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </label>
            <label>
              Пароль
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            {error && <ErrorBox error={error} />}
            <button className="primary full" disabled={busy}>
              {busy ? (
                <LoaderCircle className="spin" size={18} />
              ) : (
                <>
                  Войти в кабинет
                  <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
          <p className="login-help">
            <ShieldCheck size={18} /> Демоаккаунт: demo / demo-alfa-2026.
            <br />
            Учебные профили и материалы отмечены отдельно.
          </p>
        </div>
      </section>
    </main>
  );
}

function RelationsBrowser({ companyId }: { companyId: string }) {
  type Row = { id: string; industry: string; region: string; direction: string; amount: number | null; count: number | null; profile_available: boolean; provenance: Record<string, unknown> };
  type Result = { items: Row[]; total: number; next_offset: number | null };
  const [query, setQuery] = useState('');
  const [direction, setDirection] = useState('all');
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true; setResult(null); setError('');
    api<Result>(`/companies/${companyId}/relations?${new URLSearchParams({ q: query, direction, offset: String(offset), limit: '30' })}`)
      .then(r => { if (active) setResult(r); }).catch(e => { if (active) setError(String(e.message)); });
    return () => { active = false; };
  }, [companyId, query, direction, offset]);
  return <div className="panel">
    <h3>Поиск по всем платёжным связям</h3>
    <p className="muted small">Поиск по доступным профилям. Скрытая отрасль не участвует в поиске; платёж не определяет предмет договора.</p>
    <label>Отрасль, название или регион<input value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }} /></label>
    <label>Направление платежей<select value={direction} onChange={e => { setDirection(e.target.value); setOffset(0); }}>
      <option value="all">Все</option><option value="outgoing">Исходящие</option><option value="incoming">Входящие</option>
    </select></label>
    {error && <ErrorBox error={error} />}
    {!result && !error && <Spinner />}
    {result?.items.map((r, i) => <div className="connection" key={`${r.id}-${r.direction}-${i}`}>
      <span>{r.id}<small>{r.profile_available ? `${r.industry} · ${r.region}` : 'Профиль недоступен'} · {r.direction === 'outgoing' ? 'Исходящие' : 'Входящие'}</small>
        <small>{r.count ?? '—'} платежей · единицы суммы из исходной выборки</small>
      </span><strong>{r.amount?.toLocaleString('ru-RU') ?? '—'}</strong>
    </div>)}
    {result && <p className="muted small">Связей: {result.total}. Показаны {result.items.length ? offset + 1 : 0}–{offset + result.items.length}.</p>}
    {!!offset && <button className="secondary" onClick={() => setOffset(Math.max(0, offset - 30))}>Предыдущие связи</button>}
    {result?.next_offset != null && <button className="secondary" onClick={() => setOffset(result.next_offset!)}>Следующие связи</button>}
  </div>;
}

function ContextPanel({
  context,
  detailed = false,
}: {
  context: Context | null;
  detailed?: boolean;
}) {
  if (!context) return <Spinner />;
  return (
    <>
      <div className="panel context-panel">
        <div className="panel-title">
          <span className="icon-tile">
            <Building2 size={19} />
          </span>
          <h3>Контекст компании</h3>
        </div>
        <h2 className="company-heading">{context.name}</h2>
        <p className="muted small">{context.industry}</p>
        <div className="context-line">
          <span>Регион</span>
          <strong>{context.region}</strong>
        </div>
        <div className="context-line">
          <span>Выручка</span>
          <strong>
            {formatValue(
              "REVENUE_COMPANY",
              context.features.REVENUE_COMPANY?.value,
              context.features.REVENUE_COMPANY?.unit,
            )}
          </strong>
        </div>
        <div className="context-line">
          <span>ОКВЭД</span>
          <strong>
            {formatValue("", context.features.MAINOKVED_CODE?.value)}
          </strong>
        </div>
        <div className="divider" />
        <span className="overline">БАНКОВСКИЕ ПРОДУКТЫ</span>
        <div className="tags">
          {context.products.map((p) => (
            <span className="tag" key={p}>
              {p}
            </span>
          ))}
        </div>
        <div className="context-note">
          <ShieldCheck size={16} />
          <span>
            Каждый признак связан с источником. Недостающие данные не
            достраиваются.
          </span>
        </div>
      </div>
      {detailed ? (
        <>
          <div className="panel">
            <h3>Признаки и их происхождение</h3>
            <div className="feature-table">
              {Object.entries(context.features).map(([k, f]) => (
                <div key={k}>
                  <span>
                    {labels[k] || f.label || k}
                    <small>
                      {f.status === "calculated" ? "Расчет" : "Исходные данные"}{" "}
                      · {f.source}
                    </small>
                  </span>
                  <strong>{formatValue(k, f.value, f.unit)}</strong>
                </div>
              ))}
            </div>
          </div>
          <div className="panel">
            <h3>Платежные связи</h3>
            <p className="muted small">
              Связь показывает платежи внутри выборки и не определяет тип
              договора. Суммы показаны в единицах исходного файла; валюта и период требуют уточнения.
            </p>
            {context.counterparties.length ? (
              context.counterparties.map((c, i) => (
                <div className="connection" key={i}>
                  {c.direction === "outgoing" ? (
                    <ArrowUpRight size={18} />
                  ) : (
                    <ArrowDownLeft size={18} />
                  )}
                  <span>
                    {c.id}
                    <small>{c.industry}</small>
                  </span>
                  <strong>{c.amount?.toLocaleString("ru-RU")}</strong>
                </div>
              ))
            ) : (
              <p className="muted">Связи не загружены</p>
            )}
          </div>
          <div className="panel">
            <h3>Группа и общие связи</h3>
            <p className="muted small">Показаны только доступные вам профили. Общее физлицо не доказывает владение или должность.</p>
            {context.group.map((c) => <div className="connection" key={c.id}><Building2 size={18} /><span>{c.id}<small>{c.industry}</small></span></div>)}
            {context.shared_person_links.map((c) => <div className="connection" key={c.company_id}><Layers3 size={18} /><span>{c.company_id}<small>{c.relation}</small></span></div>)}
            {!context.group.length && !context.shared_person_links.length && <p className="muted">Доступных связанных профилей нет.</p>}
          </div>
          <RelationsBrowser key={context.id} companyId={context.id} />
        </>
      ) : (
        <div className="insight-note">
          <div className="mini-orbit">
            <Layers3 size={26} />
          </div>
          <h3>Больше, чем заголовок</h3>
          <p>
            Мы связываем события с отраслью, продуктами и бизнес-связями
            компании. Вы видите основания каждого вывода.
          </p>
        </div>
      )}
      <details className="panel missing">
        <summary>
          Что пока неизвестно <ChevronDown size={16} />
        </summary>
        {context.missing.map((m) => (
          <p key={m}>{m}</p>
        ))}
        {detailed && context.limitations.map((m) => <p key={m}>{m}</p>)}
      </details>
    </>
  );
}

function ImportPanel({ onChange }: { onChange: () => void }) {
  const [tab, setTab] = useState<"news" | "csv" | "pdf" | "rss">("news"),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState<unknown>(null),
    [error, setError] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    const form = new FormData(e.currentTarget);
    try {
      let r;
      if (tab === "news")
        r = await post("/admin/news", {
          title: form.get("title"),
          content: form.get("content"),
          publisher: form.get("publisher"),
          url: form.get("url") || null,
          published_at: new Date(
            String(form.get("published_at")),
          ).toISOString(),
          kind: form.get("kind"),
          synthetic: form.get("synthetic") === "on",
        });
      else if (tab === "rss")
        r = await post("/admin/feeds/" + form.get("feed"));
      else {
        form.set(
          "synthetic",
          form.get("synthetic") === "on" ? "true" : "false",
        );
        if (tab === "pdf")
          form.set(
            "published_at",
            new Date(String(form.get("published_at"))).toISOString(),
          );
        r = await api("/admin/import/" + tab, { method: "POST", body: form });
      }
      setResult(r);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="import-layout">
      <div className="panel">
        <h2>Добавить материал</h2>
        <p className="muted">
          Новая новость проходит тот же путь анализа. Тип CSV определяется по
          колонкам.
        </p>
        <div className="tabs">
          {(
            [
              ["news", "Новость / текст"],
              ["csv", "Компании и связи"],
              ["pdf", "Аналитика PDF"],
              ["rss", "RSS-источники"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => {
                setTab(key);
                setResult(null);
                setError("");
              }}
              className={tab === key ? "active" : ""}
            >
              {label}
            </button>
          ))}
        </div>
        <form onSubmit={submit} key={tab} className="import-form">
          {(tab === "news" || tab === "pdf") && (
            <>
              <label>
                Заголовок
                <input
                  name="title"
                  required
                  minLength={5}
                  maxLength={500}
                  placeholder="Что произошло?"
                />
              </label>
              <label>
                Дата публикации
                <input
                  name="published_at"
                  type="date"
                  required
                  defaultValue={new Date().toISOString().slice(0, 10)}
                />
              </label>
            </>
          )}
          {tab === "news" && (
            <>
              <div className="form-row">
                <label>
                  Тип материала
                  <select name="kind">
                    <option value="news">Внешняя новость</option>
                    <option value="bank">Аналитика банка</option>
                  </select>
                </label>
                <label>
                  Издатель
                  <input
                    name="publisher"
                    required
                    minLength={2}
                    placeholder="Название источника"
                  />
                </label>
              </div>
              <label>
                Ссылка на источник
                <input name="url" type="url" placeholder="https://…" />
              </label>
              <label>
                Полный текст
                <textarea
                  name="content"
                  rows={8}
                  minLength={60}
                  maxLength={100000}
                  required
                  placeholder="Вставьте текст материала. Минимум 60 символов."
                />
              </label>
            </>
          )}
          {(tab === "csv" || tab === "pdf") && (
            <label className="upload-zone">
              <FileText size={30} />
              <strong>Выберите {tab.toUpperCase()} файл</strong>
              <span>До 64 МБ · сканы PDF распознаются локально</span>
              <input
                type="file"
                name="file"
                accept={tab === "csv" ? ".csv,.tsv" : ".pdf"}
                required
              />
            </label>
          )}
          {tab === "csv" && (
            <p className="form-note">
              Компании: SYNTHETIC_U + MAINOKVED_CODE. Связи: SYNTHETIC_F +
              SYNTHETIC_U. Платежи: PAYER + BENEFICIARY + PAY_AMT + PAY_CNT.
              Первые 100 импортированных компаний добавятся текущему администратору. Для полного набора и выбора доступных профилей есть локальная команда импорта из README.
            </p>
          )}
          {tab === "pdf" && (
            <p className="form-note">
              Загружайте предоставленные материалы банка. Дата обязательна.
              Графики без извлекаемого текста требуют отдельной проверки.
            </p>
          )}
          {tab === "rss" && (
            <>
              <label>
                Источник
                <select name="feed">
                  <option value="cbr">Банк России · пресс-релизы</option>
                  <option value="vedomosti">Ведомости · новости</option>
                </select>
              </label>
              <p className="form-note">
                Загружаются открытые статьи и их источники. Реальные новости
                доступны всем профилям. Учебные события находятся в отдельной
                вкладке ленты. Недоступный полный текст помечается явно.
              </p>
            </>
          )}
          {tab !== "rss" && (
            <label className="checkbox">
              <input name="synthetic" type="checkbox" defaultChecked />{" "}
              Синтетический материал для демонстрации
            </label>
          )}
          {error && <ErrorBox error={error} />}
          <button className="primary" disabled={busy}>
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <Plus size={17} />
            )}{" "}
            {tab === "rss" ? "Обновить источник" : "Загрузить и обработать"}
          </button>
        </form>
        {result !== null && (
          <div className="import-result">
            <h3>
              <Check size={18} /> Результат обработки
            </h3>
            <pre>{JSON.stringify(result, null, 2)}</pre>
          </div>
        )}
      </div>
      <aside className="panel import-aside">
        <ShieldCheck size={25} />
        <h3>Проверяемые основания</h3>
        <p>
          Исходный текст сохраняется вместе с датой, издателем и фрагментами для
          цитирования.
        </p>
        <p>
          Повторная загрузка той же публикации не создает дубликат. Ошибки CSV
          возвращаются с номером строки.
        </p>
        <p>
          Синтетические примеры и реальные публикации анализируются раздельно.
        </p>
      </aside>
    </div>
  );
}

function Claims({
  claims,
  insight,
  onSource,
}: {
  claims: Claim[];
  insight: Insight;
  onSource: (id: string) => void;
}) {
  return (
    <div className="claims">
      {claims.map((claim, i) => (
        <div className="claim" key={i}>
          <p>{claim.text}</p>
          <div className="claim-meta">
            {claim.assumption && (
              <span className="assumption">Сценарий / предположение</span>
            )}
            {claim.feature_keys.map((k) => (
              <span
                key={k}
                className="feature-ref"
                title={insight.context_features[k]?.source}
              >
                {labels[k] || k}
              </span>
            ))}
            {claim.evidence_ids.filter((id, i, all) => {
              const item = insight.evidence.find((e) => e.id === id);
              return all.findIndex((ref) => {
                const candidate = insight.evidence.find((e) => e.id === ref);
                return candidate?.document_id === item?.document_id && candidate?.page === item?.page;
              }) === i;
            }).map((id) => {
              const e = insight.evidence.find((e) => e.id === id);
              return (
                e && (
                  <button
                    key={id}
                    className="source-ref"
                    onClick={() => onSource(e.document_id)}
                    title={e.title}
                  >
                    <FileText size={12} /> Источник{" "}
                    {[...new Set(insight.evidence.map((item) => item.document_id))].indexOf(e.document_id) + 1}
                    {e.page ? ` · стр. ${e.page}` : ""}
                  </button>
                )
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function BankSearchPreview({ runId, onSource }: { runId: string; onSource: (id: string) => void }) {
  const [result, setResult] = useState<{ sources: Evidence[]; has_direct: boolean } | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  async function refresh() {
    setLoading(true); setError("");
    try { setResult(await api<{ sources: Evidence[]; has_direct: boolean }>(`/runs/${runId}/bank-research`)); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  return <section className="panel bank-search-preview">
    <h3>Актуальный подбор аналитики банка</h3>
    <p className="muted">Поиск по сохранённым документам без обращения к AI. Текст прежнего разбора не изменяется.</p>
    <button className="text-button" disabled={loading} onClick={refresh}>{loading ? "Ищем материалы…" : "Проверить подбор аналитики"}</button>
    {error && <ErrorBox error={error} />}
    {result && <>
      <p>{result.has_direct ? "Найдены материалы по предмету новости. Применимость выводов требует проверки." : result.sources.length
        ? "Прямой оценки предмета новости нет. Найден только фон смежной отрасли; он не доказывает последствия для компании."
        : "В доступных документах нет применимой аналитики по предмету новости."}</p>
      {result.sources.map(e => <div className="bank-publication" key={e.id}>
        <span className="pill">{e.relevance?.level === "background" ? "Исторический фон" : "По предмету новости"}</span>
        <h4>{e.title}</h4><p className="muted small">{date(e.published_at)}{e.page && ` · стр. ${e.page}`}</p>
        <p className="muted small">{e.relevance?.reason}</p>
        <details className="bank-excerpt"><summary>Фрагмент из материала</summary><blockquote>{e.excerpt}</blockquote></details>
        <button className="text-button" onClick={() => onSource(e.document_id)}>Открыть материал <ArrowUpRight size={15}/></button>
      </div>)}
    </>}
  </section>;
}

function Analysis({
  runId,
  onBack,
  onSource,
  onRetry,
  isAdmin,
}: {
  runId: string;
  onBack: () => void;
  onSource: (id: string) => void;
  onRetry: (id: string) => void;
  isAdmin: boolean;
}) {
  const [run, setRun] = useState<Run | null>(null),
    [error, setError] = useState(""),
    [tab, setTab] = useState("analysis");
  const [question, setQuestion] = useState(""),
    [questionId, setQuestionId] = useState<string | null>(null),
    [answer, setAnswer] = useState<Run | null>(null),
    [asking, setAsking] = useState(false),
    [feedback, setFeedback] = useState("");
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setRun(null);
    setError("");
    setAnswer(null);
    setQuestionId(null);
    setFeedback("");
    const poll = async () => {
      try {
        const r = await api<Run>("/runs/" + runId);
        if (!active) return;
        setRun(r);
        setFeedback(r.feedback?.category || "");
        if (r.status === "queued" || r.status === "running")
          timer = setTimeout(poll, 900);
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [runId]);
  useEffect(() => {
    if (!questionId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const r = await api<Run>("/runs/" + questionId);
        if (!active) return;
        setAnswer(r);
        if (r.status === "queued" || r.status === "running")
          timer = setTimeout(poll, 900);
        else setAsking(false);
      } catch (e) {
        if (active) {
          setError((e as Error).message);
          setAsking(false);
        }
      }
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [questionId]);
  async function ask(e: FormEvent) {
    e.preventDefault();
    setError("");
    setAsking(true);
    try {
      const r = await post<{ run_id: string }>(
        "/insights/" +
          (answer?.status === "completed" ? answer.id : runId) +
          "/questions",
        { question },
      );
      setAnswer(null);
      setQuestionId(r.run_id);
      setQuestion("");
    } catch (e) {
      setError((e as Error).message);
      setAsking(false);
    }
  }
  async function rate(category: string) {
    try {
      await post("/insights/" + runId + "/feedback", { category });
      setFeedback(category);
      setRun(current => current ? { ...current, feedback: { category, comment: "" } } : current);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function retry() {
    setError("");
    setAsking(true);
    try {
      const result = await post<{ run_id: string }>("/insights/" + runId + "/retry", {});
      onRetry(result.run_id);
    } catch (e) { setError((e as Error).message); }
    finally { setAsking(false); }
  }
  const insight = run?.result;
  return (
    <div className="analysis-page">
      <button className="text-button back" onClick={onBack}>
        <ArrowLeft size={17} /> К событиям
      </button>
      {error && <ErrorBox error={error} />}
      {insight?.verification === "insufficient" && <div className="panel">
        <p>Повторная проверка заново загрузит контекст и источники. В режиме LLM она использует до четырёх обращений: исправление и проверку, при необходимости ещё один цикл.</p>
        <button className="secondary-button" onClick={() => void retry()} disabled={asking}>Исправить и проверить разбор</button>
      </div>}
      <div className="analysis-heading">
        <span className="eyebrow">ПЕРСОНАЛЬНЫЙ РАЗБОР</span>
        <h1>{insight?.headline || run?.event_title || "Собираем контекст события"}</h1>
        {insight && (
          <div className="analysis-byline">
            <Building2 size={16} /> {insight.company_name}
            <span>·</span>
            {roles[insight.role as Role]}
            <span
              className={
                "pill " +
                (insight.verification === "checked" && feedback !== "factual_error" ? "green" : "amber")
              }
            >
              <ShieldCheck size={13} />
              {feedback === "factual_error" ? "Есть замечание к разбору" : insight.verification === "checked"
                ? insight.mode === "demo" ? "Ссылки проверены · демо" : "Автопроверка пройдена"
                : insight.verification === "insufficient" ? "Проверка не пройдена" : "Ограниченные основания"}
            </span>
          </div>
        )}
      </div>
      {run && !insight && run.status !== "failed" && (
        <div className="panel">
          <Spinner text={run.stage} />
          <div className="progress-steps">
            {run.trace.map((s, i) => (
              <div key={i}>
                <Check size={15} />
                {s.step}
              </div>
            ))}
          </div>
        </div>
      )}
      {run?.status === "failed" && (
        <div className="panel">
          <h2>Разбор не завершён</h2>
          <ErrorBox error={run.error || "Анализ не завершен"} />
          <p>Черновик не опубликован как проверенный вывод. Просмотр этого результата и журнала не вызывает модель.</p>
          <details className="trace-panel">
            <summary>Журнал незавершённого разбора · содержит непроверенный черновик</summary>
            {run.trace.map((step, i) => <details key={i}>
              <summary>{step.step}</summary><pre>{JSON.stringify(step.details, null, 2)}</pre>
            </details>)}
          </details>
        </div>
      )}{" "}
      {insight && (
        <>
          {run?.search_outdated && <div className="panel">
            <p>Сохранённый разбор выполнен по прежним правилам поиска и проверки. По новым правилам этот ответ ещё не пересчитан.</p>
            <button className="text-button" onClick={() => setTab("sources")}>Посмотреть актуальный подбор банка без AI</button>
          </div>}
          {feedback === "factual_error" && <div className="panel" role="note">
            <strong>Замечание к разбору</strong>
            <p>{run?.feedback?.comment || "Отмечена возможная ошибка. Вывод требует дополнительной проверки."}</p>
            <p className="muted small">Исходный ответ модели и результат автопроверки сохранены для сверки.</p>
          </div>}
          {run?.validation_outdated && <p className="muted">Сохранённый ответ получен до обновления правил проверки финансовых выводов. Новый разбор моделью ещё не выполнялся.</p>}
          <div className="tabs detail-tabs">
            <button
              className={tab === "analysis" ? "active" : ""}
              onClick={() => setTab("analysis")}
            >
              Разбор события
            </button>
            <button
              className={tab === "sources" ? "active" : ""}
              onClick={() => setTab("sources")}
            >
              Источники <span>{new Set(insight.evidence.map((e) => e.document_id)).size}</span>
            </button>
            {isAdmin && <button
              className={tab === "trace" ? "active" : ""}
              onClick={() => setTab("trace")}
            >
              Журнал анализа <span>{run?.trace.length}</span>
            </button>}
          </div>
          {tab === "analysis" && (
            <div className="analysis-layout">
              <div className="analysis-main">
                <section className="panel">
                  <div className="section-label">
                    <Globe2 size={18} /> ФАКТЫ СОБЫТИЯ
                  </div>
                  <Claims
                    claims={insight.facts}
                    insight={insight}
                    onSource={onSource}
                  />
                </section>
                <section className="panel bank-perspective" aria-labelledby="bank-perspective-title">
                  <div className="authorship-heading">
                    <span className="authorship-icon bank"><BookOpen size={20} /></span>
                    <div>
                      <span className="authorship-badge bank">{insight.evidence.some(e=>e.kind==='bank' && e.synthetic) ? 'УЧЕБНЫЙ ИСТОЧНИК' : 'ИСТОЧНИК · АЛЬФА-БАНК'}</span>
                      <h2 id="bank-perspective-title">{insight.evidence.some((e) => e.kind === "bank" && e.synthetic)
                        ? "Учебная аналитика банка" : "Мнение экспертов Альфа-Банка"}</h2>
                    </div>
                  </div>
                  <p className="authorship-description">{insight.evidence.some((e) => e.kind === "bank" && e.synthetic)
                    ? "Синтетический пример, не реальное мнение экспертов."
                    : "Краткий пересказ AI опубликованной аналитики банка. Мнение относится к дате материала."}</p>
                  {insight.bank_view.length > 0 && insight.bank_view.every(claim => claim.evidence_ids.every(id =>
                    insight.evidence.find(e => e.id === id)?.relevance?.level === "background")) &&
                    <p className="pill amber">Исторический фон смежной отрасли. Прямой оценки события и последствий для компании нет.</p>}
                  {insight.bank_view.length ? (
                    <Claims claims={insight.bank_view} insight={insight} onSource={onSource} />
                  ) : (
                    <p className="muted">{insight.evidence.some((e) => e.kind === "bank")
                      ? insight.evidence.filter(e => e.kind === "bank").every(e => e.relevance?.level === "background")
                        ? "Прямой оценки этой новости у банка не найдено. Есть только исторический фон смежной отрасли — он не подтверждает последствия для компании. Фрагменты доступны в источниках."
                        : "Материалы банка найдены, но подтверждённый вывод по ним не сформирован. Фрагменты доступны в источниках."
                      : "Подходящий материал банка не найден. Мнение банка не достраивается."}</p>
                  )}
                  {insight.evidence.filter((e, i, all) => e.kind === "bank"
                    && insight.bank_view.some((claim) => claim.evidence_ids.includes(e.id))
                    && all.findIndex((candidate) => candidate.document_id === e.document_id
                      && insight.bank_view.some((claim) => claim.evidence_ids.includes(candidate.id))) === i
                  ).map((e) => (
                    <div className="bank-publication" key={e.document_id}>
                      <div className="bank-publication-meta">
                        <span><Clock3 size={13} /> Материал от {new Date(e.published_at).toLocaleDateString("ru-RU")}</span>
                        <button className="text-button" onClick={() => onSource(e.document_id)}>Открыть материал <ArrowUpRight size={14} /></button>
                      </div>
                      <strong>{e.title}</strong>
                      <details className="bank-excerpt">
                        <summary>Фрагмент из материала{e.page ? ` · стр. ${e.page}` : ""}</summary>
                        <blockquote>{e.excerpt}</blockquote>
                        <p className="muted small">Для материалов из PDF сверяйте распознанные числа с оригиналом.</p>
                      </details>
                    </div>
                  ))}
                </section>
                <section className="ai-perspective" aria-labelledby="ai-perspective-title">
                  <div className="authorship-heading">
                    <span className="authorship-icon ai"><Sparkles size={20} /></span>
                    <div>
                      <span className="authorship-badge ai">{insight.fixture ? "ГОТОВЫЙ УЧЕБНЫЙ ПРИМЕР" : insight.mode === "demo" ? "ДЕМО · АНАЛИТИЧЕСКИЕ ПРАВИЛА" : "AI · ПЕРСОНАЛЬНЫЙ АНАЛИЗ"}</span>
                      <h2 id="ai-perspective-title">{insight.mode === "demo" ? "Сценарии для вашей компании" : "Выводы AI для вашей компании"}</h2>
                    </div>
                  </div>
                  <p className="authorship-description">{insight.fixture_notice || (insight.mode === "demo"
                    ? "Сценарии сформированы правилами без вызова модели."
                    : "AI сопоставляет новость, материалы банка и профиль компании. Это сценарии и предложения модели, не мнение экспертов банка.")}</p>
                  <section className="panel impact-panel">
                    <h3>Влияние на ваш бизнес</h3>
                    <Claims claims={insight.impact} insight={insight} onSource={onSource} />
                    {!insight.impact.length && <p>Персональная интерпретация не опубликована: недостаточно подтверждённых оснований.</p>}
                  </section>
                <div className="risk-grid">
                  {[
                    ["Риски", insight.risks, "risk"],
                    ["Возможности", insight.opportunities, "opportunity"],
                  ].map(([title, claims, cls]) => (
                    <section key={String(title)} className={"panel " + cls}>
                      <h3>{String(title)}</h3>
                      {(claims as Claim[]).length ? (
                        <Claims
                          claims={claims as Claim[]}
                          insight={insight}
                          onSource={onSource}
                        />
                      ) : (
                        <p className="muted small">
                          Достаточных оснований для отдельного вывода нет.
                        </p>
                      )}
                    </section>
                  ))}
                </div>
                <section className="panel">
                  <div className="section-label">
                    <ArrowUpRight size={18} /> ЧТО МОЖНО ПРОВЕРИТЬ
                  </div>
                  <Claims
                    claims={insight.actions}
                    insight={insight}
                    onSource={onSource}
                  />
                </section>
                </section>
                <div className="feedback">
                  <span>Разбор помог принять решение?</span>
                  <button
                    className={feedback === "useful" ? "selected" : ""}
                    onClick={() => void rate("useful")}
                  >
                    <ThumbsUp size={16} /> Полезно
                  </button>
                  <button
                    className={feedback === "irrelevant" ? "selected" : ""}
                    onClick={() => void rate("irrelevant")}
                  >
                    <ThumbsDown size={16} /> Не по теме
                  </button>
                  <button
                    className={feedback === "factual_error" ? "selected" : ""}
                    onClick={() => void rate("factual_error")}
                  >
                    Ошибка факта
                  </button>
                  {feedback && <small>Сохранено</small>}
                </div>
              </div>
              <aside>
                <div className="panel question-panel">
                  <span className="icon-tile red">
                    <MessageSquare size={20} />
                  </span>
                  <h3>Уточнить у AI</h3>
                  <p className="muted small">
                    AI ответит с учётом компании и источников. Ответ модели не является мнением экспертов Альфа-Банка.
                  </p>
                  {insight.mode === "demo" && (
                    <div className="form-note">
                      В деморежиме произвольные вопросы не интерпретируются. Для
                      содержательного ответа требуется разрешенная LLM.
                    </div>
                  )}
                  <form onSubmit={ask}>
                    <textarea
                      aria-label="Уточняющий вопрос"
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder="Каких данных не хватает для оценки влияния?"
                      minLength={3}
                      maxLength={2000}
                      required
                      rows={4}
                    />
                    <button className="primary full" disabled={asking}>
                      {asking ? (
                        <LoaderCircle className="spin" size={16} />
                      ) : (
                        <Send size={16} />
                      )}{" "}
                      Задать вопрос
                    </button>
                  </form>
                  {answer && (
                    <div className="answer">
                      <span className="authorship-badge ai">Ответ AI</span>
                      {answer.question && <strong>{answer.question}</strong>}
                      {answer.status === "failed" ? (
                        <ErrorBox
                          error={answer.error || "Не удалось получить ответ"}
                        />
                      ) : answer.result ? (
                        <Claims
                          claims={answer.result.answer}
                          insight={answer.result}
                          onSource={onSource}
                        />
                      ) : (
                        <Spinner text={answer.stage} />
                      )}
                    </div>
                  )}
                </div>
                <div className="panel limitations">
                  <div className="section-label">
                    <CircleHelp size={17} /> ГРАНИЦЫ ВЫВОДА
                  </div>
                  {insight.limitations.map((l, i) => (
                    <p key={i}>{l}</p>
                  ))}
                </div>
              </aside>
            </div>
          )}
          {tab === "sources" && (
            <>
            <BankSearchPreview key={runId} runId={runId} onSource={onSource}/>
            {run?.search_outdated && <p className="muted">Ниже — источники сохранённого разбора, подобранные по прежним правилам. Они оставлены для проверки истории.</p>}
            <details open={!run?.search_outdated}>
            <summary>Источники сохранённого разбора · {new Set(insight.evidence.map(e => e.document_id)).size}</summary>
            <div className="sources-grid">
              {insight.evidence.filter((e, i, all) => all.findIndex((item) => item.document_id === e.document_id) === i).map((e, i) => (
                <div className="panel source-card" key={e.id}>
                  <span className="overline">
                    ИСТОЧНИК {i + 1} ·{" "}
                    {e.kind === "bank" ? "АНАЛИТИКА" : "НОВОСТЬ"}
                  </span>
                  <h3>{e.title}</h3>
                  <p className="muted small">
                    {e.publisher} · {date(e.published_at)}
                    {e.page && ` · стр. ${e.page}`}
                  </p>
                  {e.coverage === "summary" && <span className="pill amber">Только RSS-аннотация</span>}
                  {e.kind === "bank" && e.relevance?.level === "background" &&
                    <p className="muted small">Исторический фон смежной отрасли. Этот фрагмент не подтверждает последствия для компании.</p>}
                  <blockquote>{e.excerpt}</blockquote>
                  <button
                    className="text-button"
                    onClick={() => onSource(e.document_id)}
                  >
                    Открыть материал <ArrowUpRight size={15} />
                  </button>
                </div>
              ))}
            </div>
            </details>
            </>
          )}
          {tab === "trace" && isAdmin && (
            <div className="panel trace-panel">
              <h3>Журнал анализа</h3>
              <p className="muted">
                Инструменты, источники и результаты проверок. Скрытые
                рассуждения модели не сохраняются.
              </p>
              {run?.trace.map((s, i) => (
                <details key={i}>
                  <summary>
                    <span className="trace-number">{i + 1}</span>
                    <span>{s.step}</span>
                    <small>{new Date(s.at).toLocaleTimeString("ru-RU")}</small>
                    <ChevronDown size={15} />
                  </summary>
                  <pre>{JSON.stringify(s.details, null, 2)}</pre>
                </details>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MetricsPanel() {
  const [metrics, setMetrics] = useState<Metrics | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    api<Metrics>("/admin/metrics")
      .then(setMetrics)
      .catch((e) => setError(e.message));
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!metrics) return <Spinner />;
  return (
    <>
      <div className="stats-grid">
        {[
          ["Материалов", metrics.documents],
          ["Событий", metrics.events],
          ["Готовых разборов", metrics.runs.completed || 0],
          ["Среднее время · LLM", `${metrics.by_mode.live.latency_avg_seconds ?? "—"} сек`],
        ].map(([l, v]) => (
          <div className="panel metric" key={l}>
            <span>{l}</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>
      <div className="two-columns">
        {([['live', 'Реальная LLM'], ['demo', 'Учебные сценарии']] as const).map(([mode, title]) => {
          const group = metrics.by_mode[mode];
          return <div className="panel" key={mode}><h3>{title}</h3>
            <div className="context-line"><span>Запусков / прошли самопроверку</span><strong>{group.total} / {group.checked}</strong></div>
            <div className="context-line"><span>Недостаточно оснований</span><strong>{group.insufficient}</strong></div>
            <div className="context-line"><span>Медиана / P95, сек</span><strong>{group.latency_p50_seconds ?? '—'} / {group.latency_p95_seconds ?? '—'}</strong></div>
            <p className="form-note">Время включает очередь и обработку: {group.latency_samples} завершённых запусков. Самопроверка не заменяет независимую оценку.</p>
          </div>;
        })}
      </div>
      <div className="two-columns">
        <div className="panel">
          <h3>Качество и обратная связь</h3>
          {Object.entries({
            "Недостаточно оснований": metrics.insufficient_count,
            "Ошибки источников за 24 часа": metrics.source_errors_24h,
            Полезно: metrics.feedback.useful || 0,
            "Не по теме": metrics.feedback.irrelevant || 0,
            "Ошибка факта": metrics.feedback.factual_error || 0,
          }).map(([l, v]) => (
            <div className="context-line" key={l}>
              <span>{l}</span>
              <strong>{v}</strong>
            </div>
          ))}
          <p className="form-note">{metrics.quality_note}</p>
          <p className="form-note">Режим не установлен у {metrics.by_mode.unknown.total} запусков; они не включены в показатели LLM и учебных сценариев. Ошибок источников за всё время: {metrics.source_errors}.</p>
          <a className="text-button" href="/review.html" target="_blank" rel="noreferrer">Открыть форму разметки <ArrowUpRight size={15} /></a>
        </div>
        <div className="panel">
          <h3>{metrics.llm_allowance.budget_enforced ? "Бюджет удалённого API" : "Локальная модель"}</h3>
          {!metrics.llm_allowance.budget_enforced && <p>Локальная LLM работает без денежного лимита и квоты тестовых запросов. Ниже сохранена история прежних расходов удалённого API.</p>}
          <div className="context-line"><span>Обращения за весь тест</span><strong>{metrics.llm_allowance.requests_used} / {metrics.llm_allowance.request_limit}</strong></div>
          <div className="context-line"><span>Общий денежный потолок</span><strong>{metrics.llm_allowance.test_limit_rub} ₽</strong></div>
          <div className="context-line"><span>Учтено по тарифам</span><strong>{metrics.llm_allowance.spent_rub.toFixed(3)} ₽</strong></div>
          <p className="form-note">Оценка по настроенным тарифам включает резерв незавершённых запросов. Фактические списания сверяйте в кабинете провайдера; скидки и кеш могут уменьшать стоимость.</p>
          {metrics.llm_allowance.budget_enforced && !metrics.llm_allowance.test_limit_rub && <p className="form-note">Платные обращения заблокированы до задания денежного лимита.</p>}
          {metrics.budgets.length ? (
            metrics.budgets.map((b) => (
              <div className="context-line" key={b.day}>
                <span>{b.day}</span>
                <strong>{b.spent_rub.toFixed(3)} ₽</strong>
              </div>
            ))
          ) : (
            <p className="muted">
              Платных вызовов пока нет. В деморежиме LLM отключена.
            </p>
          )}
          <p className="form-note">
            Приложение резервирует стоимость перед вызовом. Общий расход ключа
            вне этого приложения контролируется у провайдера.
          </p>
          <h3>Задачи</h3>
          {Object.entries(metrics.runs).map(([s, n]) => (
            <div className="context-line" key={s}>
              <span>{s}</span>
              <strong>{n}</strong>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function BankLibrary({ onSource }: { onSource: (id: string) => void }) {
  const [items, setItems] = useState<{ id: string; title: string; publisher: string; published_at: string; synthetic: boolean; pages: number; extraction: string; date_kind: string }[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { api<typeof items>("/library").then(setItems).catch((e) => setError(e.message)); }, []);
  return <><p className="muted">Дата материала — граница актуальности позиции банка. Сканы распознаны локально; оригинал доступен для сверки.</p>{error && <ErrorBox error={error} />}<div className="sources-grid">{items.map((item) => <div className="panel source-card" key={item.id}><span className="overline">{item.synthetic ? "УЧЕБНЫЙ ПРИМЕР" : "АЛЬФА-БАНК"}</span><h3>{item.title}</h3><p className="muted small">{item.date_kind === "observed_at" ? "Загружен " : ""}{new Date(item.published_at).toLocaleDateString("ru-RU")} · {item.pages || "—"} стр. · {item.extraction === "ocr" ? "OCR" : "Текст"}</p><button className="text-button" onClick={() => onSource(item.id)}>Открыть материал <ArrowUpRight size={15} /></button></div>)}</div></>;
}

function Showcase({onOpen}: {onOpen: (id: string) => Promise<void>}) {
  const [data,setData]=useState<{notice:string;items:{id:string;company_id:string;company_name:string;role:Role;title:string}[]} | null>(null);
  const [error,setError]=useState('');
  const [opening,setOpening]=useState<string | null>(null);
  useEffect(()=>{api<NonNullable<typeof data>>('/examples').then(setData).catch(e=>setError(e.message));},[]);
  if(error) return <ErrorBox error={error} />;
  if(!data) return <Spinner text="Загружаем примеры…" />;
  return <>
    <div className="panel"><h2>Можно посмотреть без ключа LLM</h2><p>{data.notice}</p>
      <p>Компании, новости и банковские обзоры вымышлены. Раздел банка демонстрирует формат и не является позицией Альфа-Банка. Для каждой роли заранее подготовлен отдельный сценарий с источниками.</p></div>
    {!data.items.length && <p>Для доступных вам компаний учебные примеры не установлены.</p>}
    <div className="library-grid">{[...new Set(data.items.map(i=>i.company_id))].map(company=>{
      const rows=data.items.filter(i=>i.company_id===company);
      return <div key={company} className="panel library-card"><span className="overline">УЧЕБНЫЙ ПРИМЕР</span>
        <h3>{rows[0].company_name}</h3><p>{rows[0].title}</p>
        <div className="showcase-actions">{rows.map(row=><button key={row.id} className="text-button" disabled={opening!==null} onClick={async()=>{
          setOpening(row.id);try{await onOpen(row.id);}finally{setOpening(null);}
        }}>Открыть разбор · {row.role==='TREASURER'?'Казначей':row.role} <ArrowUpRight size={15}/></button>)}</div>
      </div>;
    })}</div>
  </>;
}

export default function App() {
  const [corpus, setCorpus] = useState<"real" | "synthetic">("real");
  const [feedStatus, setFeedStatus] = useState<FeedStatus | null>(null);
  const [selection, setSelection] = useState<SelectionStatus | null>(null);
  const [listSelection, setListSelection] = useState<ListSelection | null>(null);
  const [selectionBusy, setSelectionBusy] = useState(false);
  const [feedMeta, setFeedMeta] = useState<FeedResponse | null>(null);
  const [feedScope, setFeedScope] = useState<"personal" | "all">("personal");
  const [moreBusy, setMoreBusy] = useState(false);
  const [feedChanged, setFeedChanged] = useState(false);
  const currentFeed = useRef<string | null>(null);
  const [user, setUser] = useState<User | null>(null),
    [checking, setChecking] = useState(true),
    [companies, setCompanies] = useState<Company[]>([]),
    [companyId, setCompanyId] = useState(""),
    [role, setRole] = useState<Role>("CFO");
  const [context, setContext] = useState<Context | null>(null),
    [items, setItems] = useState<EventItem[]>([]),
    [topics, setTopics] = useState<Record<string, string>>({}),
    [topic, setTopic] = useState(""),
    [search, setSearch] = useState("");
  const [availableTopics,setAvailableTopics]=useState<string[]>([]);
  const [feedSort,setFeedSort]=useState('relevance');
  const [analysisPending,setAnalysisPending]=useState<string|null>(null);
  const [analysisErrors,setAnalysisErrors]=useState<Record<string,string>>({});
  const analysisAttempt=useRef(0);
  useEffect(()=>{analysisAttempt.current++;setAnalysisPending(null);setAnalysisErrors({});},[companyId,role,corpus]);
  const [page, setPage] = useState("feed"),
    [runId, setRunId] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0),
    [source, setSource] = useState<Source | null>(null),
    [sourceBusy, setSourceBusy] = useState(false);
  const initialLink = useRef(true);
  const pendingLinkedRun = useRef<Run | null>(null);
  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    if (!user) return;
    let active = true;
    const linkedId = initialLink.current ? new URLSearchParams(window.location.search).get("run") : null;
    api<Company[]>("/companies")
      .then(async (c) => {
        const linked = linkedId ? await api<Run>("/runs/" + encodeURIComponent(linkedId)) : null;
        if (active) {
          initialLink.current = false;
          pendingLinkedRun.current = linked;
          setCompanies(c);
          if (linked) setRole(linked.role);
          const chosen = c.find(v => v.id === (linked?.company_id || companyId))
            || c.find(v => !v.synthetic && v.ready_roles?.includes(role))
            || c.find(v => v.synthetic) || c[0];
          if (chosen && (linked || chosen.id !== companyId)) setCorpus(chosen.synthetic ? 'synthetic' : 'real');
          setCompanyId(chosen?.id || '');
        }
      })
      .catch((e) => setError(e.message));
    return () => {
      active = false;
    };
  }, [user, revision]);
  useEffect(() => {
    if (!companyId) return;
    if (corpus === "synthetic" && companies.find((c) => c.id === companyId)?.synthetic === false) {
      setCorpus("real");
      return;
    }
    let active = true;
    setBusy(true);
    setError("");
    setRunId(null);
    setContext(null);
    setItems([]);
    currentFeed.current = null; setFeedMeta(null); setFeedChanged(false);
    Promise.all([
      api<Context>(`/companies/${encodeURIComponent(companyId)}/context`),
      api<FeedResponse>(
        `/feed?company_id=${encodeURIComponent(companyId)}&role=${role}&corpus=${corpus}&q=${encodeURIComponent(search)}&topic=${encodeURIComponent(topic)}&scope=${feedScope}&sort=${feedSort}&limit=5`,
      ),
    ])
      .then(([c, f]) => {
        if (active) {
          setContext(c);
          setItems(f.items);
          setTopics(f.topics);
          setAvailableTopics(f.available_topics || Object.keys(f.topics));
          setSelection(f.selection);
          setListSelection(f.list_selection ?? null);
          setFeedMeta(f); currentFeed.current = f.feed_version;
          const linked = pendingLinkedRun.current;
          if (linked?.company_id === companyId && linked.role === role) {
            setRunId(linked.id);
            pendingLinkedRun.current = null;
          }
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [companyId, role, revision, corpus, companies, search, topic, feedScope,feedSort]);
  useEffect(() => {
    if (!user) return;
    let active = true;
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const status = await api<FeedStatus>("/feeds/status");
        if (active) setFeedStatus(status);
        if (companyId && page === "feed" && !runId) {
          const feed = await api<FeedResponse>(
            `/feed?company_id=${encodeURIComponent(companyId)}&role=${role}&corpus=${corpus}&q=${encodeURIComponent(search)}&topic=${encodeURIComponent(topic)}&scope=${feedScope}&sort=${feedSort}&limit=5`,
          );
          if (active && currentFeed.current) {
            setFeedChanged(feed.feed_version !== currentFeed.current);
            setSelection(feed.selection);
          }
        }
      } catch { /* Transient refresh errors keep the current view intact. */ }
      finally { pending = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [user, companyId, role, corpus, page, runId, revision, search, topic, feedScope,feedSort]);
  async function loadMore() {
    if (!feedMeta || feedMeta.next_offset === null || moreBusy) return;
    const version = currentFeed.current;
    setMoreBusy(true); setError("");
    try {
      const next = await api<FeedResponse>(`/feed?company_id=${encodeURIComponent(companyId)}&role=${role}&corpus=${corpus}&q=${encodeURIComponent(search)}&topic=${encodeURIComponent(topic)}&scope=${feedScope}&sort=${feedSort}&limit=5&offset=${feedMeta.next_offset}&feed_version=${encodeURIComponent(feedMeta.feed_version)}`);
      if (currentFeed.current === version) { setItems(old => [...old, ...next.items]); setFeedMeta(next); }
    } catch (e) { setError((e as Error).message); }
    finally { setMoreBusy(false); }
  }
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSource(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);
  async function analyze(event: EventItem) {
    if(analysisPending)return;
    setAnalysisErrors(previous=>({...previous,[event.id]:''}));
    if(event.analysis?.status==='unavailable'){
      setAnalysisErrors(previous=>({...previous,[event.id]:event.analysis?.message||'Вызовы модели отключены. Сохранённого разбора нет.'}));return;
    }
    if(event.analysis?.status==='saved'&&event.analysis.run_id){setRunId(event.analysis.run_id);window.scrollTo({top:0});return;}
    const attempt=++analysisAttempt.current;
    setAnalysisPending(event.id);
    try {
      const r = await post<{ run_id: string }>("/analyses", {
        company_id: companyId,
        event_id: event.id,
        role,
      });
      if(attempt===analysisAttempt.current){setRunId(r.run_id);window.scrollTo({top:0});}
    } catch (e) {
      if(attempt===analysisAttempt.current)setAnalysisErrors(previous=>({...previous,[event.id]:(e as Error).message}));
    } finally {if(attempt===analysisAttempt.current)setAnalysisPending(null);}
  }
  async function openExample(id: string) {
    setError('');
    try {
      const opened = await post<{run_id:string}>(`/examples/${encodeURIComponent(id)}/open`);
      const run = await api<Run>(`/runs/${opened.run_id}`);
      pendingLinkedRun.current = run;
      setCompanyId(run.company_id); setRole(run.role); setCorpus('synthetic');
      setSearch(''); setTopic(''); setFeedScope('personal'); setPage('feed'); setRunId(run.id);
    } catch (e) { setError((e as Error).message); }
  }
  async function openSource(id: string) {
    setSourceBusy(true);
    try {
      setSource(await api<Source>("/sources/" + id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSourceBusy(false);
    }
  }
  async function logout() {
    try {
      await post("/auth/logout");
      setUser(null);
      setCompanyId("");
      setRunId(null);
      setPage("feed");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function navigate(next: string) {
    setPage(next);
    setRunId(null);
    setError("");
  }
  if (checking)
    return (
      <div className="app-loading">
        <Logo />
        <Spinner />
      </div>
    );
  if (!user) return <Login onLogin={setUser} />;
  const filtered = items;
  const unprocessed = corpus === 'real' && ['not_processed', 'processing', 'failed'].includes(feedMeta?.personalization?.status || '');
  const preparedCompany = companies.find(c=>!c.synthetic && c.id!==companyId && c.ready_roles?.includes(role));
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Logo />
        <div className="workspace-label">КАБИНЕТ КОМПАНИИ</div>
        <nav>
          <button
            className={page === "feed" ? "active" : ""}
            onClick={() => navigate("feed")}
          >
            <Sparkles size={19} />
            Новостная аналитика
            <span className="new-dot" />
          </button>
          <button
            className={page === "context" ? "active" : ""}
            onClick={() => navigate("context")}
          >
            <Building2 size={19} />
            Контекст компании
          </button>
          <button className={page === "library" ? "active" : ""} onClick={() => navigate("library")}><BookOpen size={19} />Аналитика банка</button>
          <button className={page === "examples" ? "active" : ""} onClick={() => navigate("examples")}><FlaskConical size={19} />Готовые примеры</button>
          {user.is_admin && (
            <>
              <div className="workspace-label">РАБОТА С ДАННЫМИ</div>
              <button className={page==='settings'?'active':''} onClick={()=>navigate('settings')}><SettingsIcon size={19}/>Настройки LLM</button>
              <button
                className={page === "import" ? "active" : ""}
                onClick={() => navigate("import")}
              >
                <Database size={19} />
                Источники и импорт
              </button>
              <button
                className={page === "metrics" ? "active" : ""}
                onClick={() => navigate("metrics")}
              >
                <BarChart3 size={19} />
                Качество и бюджет
              </button>
            </>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="demo-card">
            <FlaskConical size={20} />
            <strong>Альфа Хак 2026</strong>
            <p>Работающий прототип персональной аналитики</p>
          </div>
          <button className="logout" onClick={() => void logout()}>
            <LogOut size={17} /> Выйти из кабинета
          </button>
        </div>
      </aside>
      <div className="app-body">
        <header className="topbar">
          <div className="breadcrumb">
            Альфа-Бизнес <ChevronRight size={14} />
            <strong>Контекст</strong>
          </div>
          <div className="topbar-right">
            <span className="status-dot" />
            <span className="small muted">
              {user.mode === "demo"
                ? "Демонстрационный режим"
                : "LLM включена"}
            </span>
            <div className="avatar">
              {user.name
                .split(" ")
                .map((n) => n[0])
                .slice(0, 2)
                .join("")}
            </div>
            <span className="user-name">{user.name}</span>
          </div>
        </header>
        <main className="main-content">
          {error && <ErrorBox error={error} onClose={() => setError("")} />}
          <div className="page-title">
            <div>
              <span className="eyebrow">ВАШ БИЗНЕС В КОНТЕКСТЕ СОБЫТИЙ</span>
              <h1>
                {page === "feed"
                  ? "Новостная аналитика"
                  : page === "context"
                    ? "Контекст компании"
                    : page === "import"
                      ? "Источники и данные" : page === "library" ? "Аналитика банка" : page === 'examples' ? 'Готовые примеры' : page==='settings' ? 'Настройки LLM'
                      : "Качество и бюджет"}
              </h1>
              <p className="muted">
                {page === "feed"
                  ? "Главное для вашей компании. С объяснением, почему это важно."
                  : page === "context"
                    ? "Факты, связи и ограничения, на которых строится персонализация."
                    : page === "import"
                      ? "Добавляйте материалы и проверяйте анализ на новых событиях."
                      : page === "library" ? "Исследования банка, даты и оригиналы для проверки оснований."
                      : page === 'examples' ? 'Три компании и три роли. Разборы с источниками доступны без подключения модели.'
                      : page === 'settings' ? 'Адрес сервера, токен и модель для разбора новостей.'
                      : "Прозрачность работы сервиса и обратная связь пользователей."}
              </p>
            </div>
            {page === "feed" && (
              <button
                className="secondary refresh"
                onClick={() => setRevision((r) => r + 1)}
                disabled={busy}
              >
                <RefreshCw size={16} className={busy ? "spin" : ""} /> Обновить
                ленту
              </button>
            )}
          </div>
          {!['examples','settings'].includes(page) && <div className="selector-bar">
            <div className="select-company">
              <Building2 size={19} />
              <label>
                <span>Компания</span>
                <select
                  aria-label="Компания"
                  value={companyId}
                  onChange={(e) => {
                    const chosen=companies.find(c=>c.id===e.target.value);
                    setCompanyId(e.target.value); setCorpus(chosen?.synthetic ? 'synthetic' : 'real');
                    setSearch(''); setTopic('');
                  }}
                >
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}{c.synthetic ? ' · учебная' : !c.ready_roles?.length ? ' · подборка не готова' : ''}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="select-role">
              <span>Моя роль</span>
              <select
                aria-label="Моя роль"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
              >
                {Object.entries(roles).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </div>
            <span className="context-badge">
              <span className="status-dot" />
              {context?.synthetic
                ? "Синтетический профиль"
                : "Контекст клиента"}
            </span>
          </div>
          }
          {page === "feed" &&
            (runId ? (
              <Analysis
                runId={runId}
                onBack={() => setRunId(null)}
                onSource={(id) => void openSource(id)}
                onRetry={setRunId}
                isAdmin={user.is_admin}
              />
            ) : (
              <>
                <div className="corpus-bar">
                  <div className="corpus-tabs" aria-label="Материалы ленты">
                    <button aria-pressed={corpus === "real"} onClick={() => { setCorpus("real"); setTopic(""); setSearch(""); }}>Реальные новости</button>
                    {context?.synthetic && <button aria-pressed={corpus === "synthetic"} onClick={() => { setCorpus("synthetic"); setTopic(""); setSearch(""); }}>Учебные события</button>}
                  </div>
                  {feedStatus && <span className="muted small">{feedStatus.automatic ? `Автообновление · каждые ${Math.round(feedStatus.interval_seconds / 60)} мин` : "Автообновление отключено"} {user.is_admin&&<button className="text-button" onClick={()=>setPage('import')}>Настроить автообновление</button>}</span>}
                </div>
                {corpus === "real" && feedStatus && <div className="feed-status" aria-label="Состояние источников">
                  {feedStatus.items.map((feed) => <div key={feed.key} className={`feed-status-item ${feed.status}`}>
                    <span className="status-dot" />
                    <div><strong>{feed.name}</strong><span>
                      {({ pending: "Ожидает загрузки", idle: "Ожидает загрузки", running: "Загружаем статьи…", recovering: "Возобновляем загрузку…", ok: "Обновлено", partial: "Обновлено с замечаниями", error: "Источник временно недоступен" } as Record<string, string>)[feed.status] || feed.status}
                      {feed.last_finished_at && ` · ${new Date(feed.last_finished_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}`}
                      {feed.report.articles !== undefined && ` · ${feed.report.articles} статей`}
                      {!!feed.report.summaries && ` · ${feed.report.summaries} аннотаций`}
                    </span>{feed.error && <span>{feed.error}</span>}</div>
                  </div>)}
                </div>}
                {corpus === 'real' && feedMeta?.processing && <div className="panel feed-mode" aria-label="Режим работы ленты">
                  <strong>{feedMeta.processing.analysis_mode==='saved_only'?'Сохранённые новости и оценки · модель отключена':feedMeta.processing.analysis_mode==='demo'?'Разбор без LLM · учебный режим':'Вызовы модели разрешены'}</strong>
                  <p>{feedMeta.processing.news_updates?'Источники обновляются по расписанию.':'Автообновление источников отключено; это ранее загруженные статьи.'} {feedMeta.processing.analysis_mode==='saved_only'?'Оценка связи не означает, что готов подробный разбор. Новая генерация сейчас не выполняется.':'Подробный разбор запускается кнопкой в карточке.'}</p>
                  {user.is_admin&&feedMeta.processing.analysis_mode==='saved_only'&&<button className="text-button" onClick={()=>setPage('settings')}>Настроить подключение LLM</button>}
                </div>}
                <details className="panel feed-explainer">
                  <summary>Как определяется связь с компанией</summary>
                  <p>Для реальных новостей модель сопоставляет полный доступный текст с профилем компании и выбранной ролью. Проверяются цитаты источника и признаки профиля. Для учебных примеров используются демонстрационные правила.</p>
                  <p><strong>Прямая связь с профилем</strong> — модель нашла конкретное подтверждённое основание применимости. Это не доказательство убытка, выгоды или изменения условий вашего договора.</p>
                  <p><strong>Условная применимость</strong> — модель предлагает сценарий, для которого надо уточнить условия. Такая оценка может быть ошибочной: одного наличия кредита недостаточно, чтобы считать компанию участником специальной программы.</p>
                  <p><strong>Связь не установлена</strong> — полезное основание не найдено. <strong>Оценка не готова</strong> — материал ещё не проверен.</p>
                  {feedMeta?.relationship_counts&&<p>Во всей выбранной области просмотра: прямых — {feedMeta.relationship_counts.direct}, условных — {feedMeta.relationship_counts.indirect}, без установленной связи — {feedMeta.relationship_counts.unknown}. Смена компании и роли может менять оценки.</p>}
                </details>
                {corpus === "real" && selection && <div className="feed-status" aria-label="Нейросетевой отбор">
                  <div className="feed-status-item">
                    <Sparkles size={18} />
                    <div><strong>{selection.model === "deepseek-flash" ? "Сохранённые оценки DeepSeek" : "Сохранённые оценки модели"} · проверено {selection.completed} из {selection.total}</strong>
                      <span>Полный доступный текст статьи и контекст вашей компании. Все материалы доступны в отдельном режиме поиска.</span>
                      {!!selection.queued && <span>В очереди: {selection.queued}</span>}
                      {!!selection.historical && <span>Ещё {selection.historical} оценок сохранены с прежними настройками подключения. Они показаны отдельно от новых проверок.</span>}
                      {!!selection.failed && <span>Не удалось обработать: {selection.failed}.</span>}
                      {!!selection.budget_blocked&&<span role="alert">Для {selection.budget_blocked} материалов не хватило свободного лимита API. Измените лимит в настройках LLM и сохраните для возобновления.</span>}
                      {!selection.can_request && <span>На этом стенде доступны сохранённые оценки.</span>}
                      {listSelection?.status === "completed" && <span><strong>{listSelection.historical ? "Сохранённая короткая подборка дополнена остальными оценёнными материалами. Полный порядок ещё требует проверки моделью." : "Полная лента проверена моделью: приоритетные события вверху, остальные доступны ниже."}</strong></span>}
                      {listSelection?.status === "stale" && <span>Источники или профиль изменились. Полная подборка ожидает обновления.</span>}
                      {listSelection && ["queued", "running"].includes(listSelection.status) && <span>Обрабатываем новости и проверяем их применимость…</span>}
                      {listSelection?.status === "failed" && <span>Подборка не прошла проверку. Сохранённые индивидуальные оценки доступны ниже.</span>}
                      {listSelection?.status === "not_requested" && <span>Полный сравнительный порядок пока не подготовлен.</span>}
                      {!!listSelection?.insufficient && <span>Для {listSelection.insufficient} материалов недостаточно данных для оценки применимости.</span>}
                      {!feedMeta?.pipeline.model_available && <span>Модель на этом стенде не подключена. Доступны сохранённые результаты.</span>}
                      {feedMeta?.pipeline.paused_reason?<span role="alert">{feedMeta.pipeline.paused_reason}</span>
                        :feedMeta?.pipeline.automatic&&<span>Новые статьи обрабатываются автоматически{feedMeta.pipeline.provider_mode==='remote'?' в пределах бюджета API':''}.</span>}
                    </div>
                  </div>
                  {selection.can_request && user.is_admin && <button className="text-button" disabled={selectionBusy} onClick={async () => {
                    setSelectionBusy(true); setError("");
                    try { await api("/ranking", { method: "POST", body: JSON.stringify({ company_id: companyId }) }); setRevision((r) => r + 1); }
                    catch (e) { setError(e instanceof Error ? e.message : "Не удалось запустить отбор"); }
                    finally { setSelectionBusy(false); }
                  }}>{selectionBusy ? "Ставим в очередь…" : "Оценить до 10 последних новостей"}</button>}
                  {selection.can_request && <button className="text-button" disabled={selectionBusy} onClick={async () => {
                    setSelectionBusy(true); setError("");
                    try { await post("/reading-list", {company_id: companyId, retry_failed: true}); setRevision(x => x + 1); }
                    catch (e) { setError((e as Error).message); }
                    finally { setSelectionBusy(false); }
                  }}>Обновить полную ленту</button>}
                </div>}
                {feedChanged && <div className="panel" role="status">Есть обновление ленты. Текущий порядок сохранён до обновления. <button className="text-button" onClick={() => setRevision(x => x + 1)}>Показать обновление</button></div>}
                <div className="overview">
                  <div className="overview-copy">
                    <span className="pill">
                      <Sparkles size={13} /> Персональная подборка
                    </span>
                    <h2>Важное для вашего бизнеса</h2>
                    <p>От внешнего события — к его влиянию на ваши решения.</p>
                  </div>
                  <div className="overview-metrics">
                    <div>
                      <strong>
                        {unprocessed && feedScope === 'personal' ? '—' : (feedMeta?.total ?? items.length).toString().padStart(2, "0")}
                      </strong>
                      <span>{unprocessed && feedScope === 'personal' ? 'подборка ещё не готова' : search.trim() ? "публикаций найдено" : "событий в контексте"}</span>
                    </div>
                    <div>
                      <strong>
                        {items
                          .filter((i) => i.exposure.level === 'direct')
                          .length.toString()
                          .padStart(2, "0")}
                      </strong>
                      <span>с прямой связью среди показанных</span>
                    </div>
                    <div className="overview-mark">
                      <TrendingUp size={37} />
                    </div>
                  </div>
                </div>
                <div className="feed-layout">
                  <section>
                    <div className="feed-toolbar">
                      <h2>
                        Лента событий <span>{filtered.length}</span>
                      </h2>
                      <div className="search-box">
                        <Search size={15} />
                        <input
                          aria-label="Поиск по ленте"
                          placeholder="Найти событие"
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                      </div>
                    </div>
                    <label className="feed-sort">Порядок событий<select aria-label="Сортировка событий" value={feedSort} onChange={e=>setFeedSort(e.target.value)}>
                      <option value="relevance">По релевантности</option><option value="newest">Сначала новые</option><option value="oldest">Сначала старые</option>
                    </select></label>
                    <div className="filters" aria-label="Область поиска">
                      <button className={feedScope === "personal" ? "active" : ""} onClick={() => setFeedScope("personal")}>Для моей компании</button>
                      <button className={feedScope === "all" ? "active" : ""} onClick={() => setFeedScope("all")}>Все материалы</button>
                    </div>
                    {feedScope === "all" && <p className="muted small">Здесь также есть неоценённые и нерелевантные компании материалы. Их статус указан в карточке.</p>}
                    <div className="filters" aria-label="Темы новостей">
                      <button
                        className={!topic ? "active" : ""}
                        onClick={() => setTopic("")}
                      >
                        Все события
                      </button>
                      {Object.entries(topics)
                        .filter(([t]) =>
                          availableTopics.includes(t) || t === topic,
                        )
                        .map(([t, name]) => (
                          <button
                            key={t}
                            className={topic === t ? "active" : ""}
                            onClick={() => setTopic(t)}
                          >
                            {name}
                          </button>
                        ))}
                    </div>
                    {busy ? (
                      <Spinner text="Подбираем события под контекст…" />
                    ) : filtered.length ? (
                      <div className="event-list">
                        {filtered.map((event, i) => (
                          <article
                            className={
                              "event-card " + (i === 0 ? "featured" : "")
                            }
                            key={event.id}
                          >
                            <div className="event-meta">
                              <span
                                className={
                                  "priority " +
                                  (event.exposure.level === 'direct' ? "high" : "normal")
                                }
                              >
                                <span />
                                {event.ranking_method === 'llm' && event.exposure.level === 'unknown'
                                  ? (event.score === 0 && event.ranking_status === 'completed' ? "Связь не установлена" : "Оценка не готова")
                                  : event.exposure.level === 'direct'
                                  ? "Прямая связь с профилем"
                                  : event.exposure.level === 'indirect' ? "Условная применимость" : "Связь не установлена"}
                              </span>
                              <span>
                                <Clock3 size={13} />
                                {date(event.published_at)}
                              </span>
                            </div>
                            <button
                              className="event-title"
                              onClick={() => event.document_id ? void openSource(event.document_id) : void analyze(event)}
                            >
                              {event.title}
                            </button>
                            <p className="overline excerpt-label">{event.source_coverage==='summary'?'Аннотация источника':event.summary_truncated?'Начало статьи':'Текст статьи'}</p>
                            <p className="event-summary">{event.summary}</p>
                            {!!event.reading_notes?.length&&<p className="small muted">Сокращения источника: {event.reading_notes.map(n=>`${n.term} — ${n.meaning}`).join('; ')}.</p>}
                            {event.document_id&&<button className="text-button read-article" onClick={()=>void openSource(event.document_id!)}>{event.source_coverage==='summary'?'Читать доступную аннотацию':'Читать полный доступный текст'} <FileText size={14}/></button>}
                            <div className="relevance">
                              <span>
                                <Sparkles size={15} />
                              </span>
                              <div>
                                <strong>{event.exposure.level === "unknown" ? "Связь с компанией" : event.exposure.level==='indirect'?'Когда может быть полезно':'Почему важно для вас'}{event.ranking_method === "llm" && event.ranking_status === "completed" ? " · AI" : ""}</strong>
                                <p>{event.reasons.slice(0, 2).join(". ")}</p>
                                {event.ranking_historical&&<p className="small muted">Сохранённая оценка прежнего подключения. Текущая модель ещё не перепроверила этот материал.</p>}
                                {!event.reasons.includes(event.exposure.note) && <p className="small muted">{event.exposure.note}</p>}
                                {!!event.ordering?.repeated_financial_topics.length && <details className="small">
                                  <summary>Почему ниже в подборке</summary>
                                  <p>{event.ordering.note}</p>
                                </details>}
                                {!!event.ranking_grounds?.length && <details className="small">
                                  <summary>Основания отбора</summary>
                                  {event.feature_keys?.map(key=>{const feature=context?.features[key];return feature?<p key={key}><strong>Признак профиля: {feature.label}</strong> — {formatValue(key,feature.value,feature.unit)}.<br/><span className="muted">Основание: {feature.source}</span></p>:null;})}
                                  {event.ranking_grounds.map((ground, index) => <div key={index}>
                                    <p>{ground.location === 'title' ? 'Из заголовка: ' : ''}«{ground.quote}»</p>
                                    {ground.document_id && <button className="text-button" onClick={() => void openSource(ground.document_id!)}>{ground.publisher} · открыть источник</button>}
                                  </div>)}
                                </details>}
                              </div>
                            </div>
                            <div className="event-footer">
                              <span>
                                <FileText size={14} />
                                {event.synthetic
                                  ? "Синтетический пример"
                                  : event.publisher}{" "}
                                <span className="bullet">·</span>{" "}
                                {event.source_count} ист.
                              </span>
                              <button
                                className="text-button"
                                disabled={analysisPending!==null}
                                aria-busy={analysisPending===event.id}
                                onClick={() => void analyze(event)}
                              >
                                {analysisPending===event.id?'Открываем разбор…':event.analysis?.status==='saved'?'Открыть сохранённый разбор':event.analysis?.status==='unavailable'?'Почему нет разбора':'Разобрать влияние'}
                                <ArrowRight size={16} />
                              </button>
                            </div>
                            {event.analysis?.status==='unavailable'&&<p className="analysis-unavailable small">Готового разбора нет · модель отключена</p>}
                            {analysisErrors[event.id]&&<div className="error-box analysis-error" role="alert">
                              <p>{analysisErrors[event.id]}</p>
                              {user.is_admin&&event.analysis?.status==='unavailable'&&<button className="text-button" onClick={()=>setPage('settings')}>Перейти в настройки LLM</button>}
                            </div>}
                            {!!event.related_publications?.length && (
                              <details className="small">
                                <summary>Другие публикации об этом событии ({event.related_publications.length})</summary>
                                {event.related_publications.map((publication) => (
                                  <button key={publication.document_id} className="text-button" onClick={() => void openSource(publication.document_id)}>
                                    {publication.title} · {publication.publisher}
                                  </button>
                                ))}
                              </details>
                            )}
                            {!!event.previous_editions?.length && <details className="small">
                              <summary>Предыдущие выпуски ({event.previous_editions.length})</summary>
                              <p className="muted">В подборке показан последний оценённый выпуск. Исторические публикации сохранены отдельно.</p>
                              {event.previous_editions.map((edition) => edition.document_id ?
                                <button key={edition.id} className="text-button" onClick={() => void openSource(edition.document_id!)}>
                                  {date(edition.published_at)} · {edition.title}
                                </button> : <p key={edition.id}>{date(edition.published_at)} · {edition.title}</p>)}
                            </details>}
                          </article>
                        ))}
                      </div>
                    ) : (
                      <div className="panel empty">
                        <Search size={30} />
                        <h3>{unprocessed && feedScope === 'personal' ? 'Подборка для этой компании ещё не подготовлена' : search || topic ? 'Нет событий по этим фильтрам' : feedMeta?.personalization?.status === 'no_sources' ? 'Новости ещё не загружены' : 'Среди проверенных новостей пока нет подходящих событий'}</h3>
                        <p>
                          {unprocessed && feedScope === 'personal'
                            ? `Новости загружены, но проверенных оценок для выбранного профиля пока нет. Это не означает, что все новости нерелевантны. ${feedMeta?.pipeline.automatic ? 'Дождитесь завершения обработки.' : 'Для нового отбора нужно подключить модель. Готовые учебные примеры доступны уже сейчас.'}`
                            : 'В персональную ленту попадают проверенные новости с применимой связью с профилем и ролью. Необработанные материалы не считаются нерелевантными.'}
                        </p>
                        {(search || topic) && <button className="text-button" onClick={()=>{setSearch('');setTopic('');}}>Сбросить поиск и тему</button>}
                        {feedScope === 'personal' && <button className="text-button" onClick={()=>setFeedScope('all')}>Показать все материалы</button>}
                        {unprocessed && preparedCompany && <button className="text-button" onClick={()=>{
                          setCompanyId(preparedCompany.id);setCorpus('real');setSearch('');setTopic('');setFeedScope('personal');
                        }}>Перейти к готовой подборке</button>}
                        <button className="text-button" onClick={()=>navigate('examples')}>Открыть готовые примеры</button>
                      </div>
                    )}
                    {feedMeta?.next_offset != null && <button className="text-button" disabled={moreBusy} onClick={() => void loadMore()}>{moreBusy ? "Загружаем…" : `Показать ещё · ${items.length} из ${feedMeta.total}`}</button>}
                  </section>
                  <aside className="context-aside">
                    <ContextPanel context={context} />
                  </aside>
                </div>
              </>
            ))}
          {page === "context" && (
            <div className="context-full">
              <ContextPanel context={context} detailed />
            </div>
          )}
          {page === 'examples' && <Showcase onOpen={openExample} />}
          {page === "import" && user.is_admin && (
            <><FeedSettings request={api} onSaved={()=>setRevision(r=>r+1)}/><ImportPanel onChange={() => setRevision((r) => r + 1)} /></>
          )}
          {page === "metrics" && user.is_admin && <MetricsPanel />}
          {page === 'settings' && user.is_admin && <LlmSettings request={api} onSaved={()=>{
            void api<User>('/auth/me').then(setUser);setRevision(r=>r+1);
          }}/>}
          {page === "library" && <BankLibrary onSource={openSource} />}
          <footer className="footer">
            <span>Альфа · Контекст</span>
            <span>Источники → контекст → проверяемые выводы</span>
          </footer>
        </main>
      </div>
      {sourceBusy && (
        <div className="toast">
          <Spinner text="Открываем источник…" />
        </div>
      )}
      {source && (
        <div className="modal-backdrop" onClick={() => setSource(null)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-title"
            className="source-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-top">
              <span className="eyebrow">ПЕРВОИСТОЧНИК</span>
              <button
                className="icon-button"
                onClick={() => setSource(null)}
                aria-label="Закрыть источник"
              >
                <X size={21} />
              </button>
            </div>
            <h2 id="source-title">{source.title}</h2>
            <p className="muted small">{source.publisher}</p>
            {source.synthetic && (
              <span className="pill amber">Синтетический материал</span>
            )}
            {source.ingestion?.coverage && <p className="source-coverage">
              <span className={"pill " + (source.ingestion.coverage === "summary" ? "amber" : "")}>
                {source.ingestion.coverage === "summary" ? "Только RSS-аннотация" : source.ingestion.extraction === "ocr" ? "Распознанный PDF · OCR" : "Текст материала"}
              </span>
              {source.ingestion.fetched_at && <span className="muted small">Загружено {new Date(source.ingestion.fetched_at).toLocaleString("ru-RU")}</span>}
            </p>}
            {source.ingestion?.warning && <p className="muted small">{source.ingestion.warning}</p>}
            {source.ingestion?.date_source && <p className="muted small">Основание даты: {source.ingestion.date_source}</p>}
            {source.ingestion?.original_file && <a className="text-button" href={`/api/sources/${source.id}/original`} target="_blank" rel="noopener noreferrer">Скачать оригинальный PDF <ExternalLink size={16} /></a>}
            {source.ingestion?.original_file && <div className="context-note">
              <span>Графики и таблицы требуют сверки с оригиналом. Числа из неподтверждённых графических фрагментов не являются основанием расчёта.</span>
            </div>}
            {!!source.ingestion?.pages?.length && <details className="panel">
              <summary>Качество извлечения по страницам</summary>
              {source.ingestion.pages.map(p => <p className="muted small" key={p.number}>
                Стр. {p.number} · {p.text_status === 'empty' ? 'текст не извлечён' : p.text_status === 'ocr' ? 'текст распознан OCR' : 'доступен текст'} · графики: {p.visual_status === 'verified' ? 'проверены' : 'не проверены'} · таблицы: {p.numeric_tables_status === 'verified' ? 'проверены' : 'не проверены'}
              </p>)}
            </details>}
            {!!source.reading_notes?.length&&<p className="form-note">Сокращения в оригинале: {source.reading_notes.map(n=>`${n.term} — ${n.meaning}`).join('; ')}. Текст источника сохранён без подмены формулировок.</p>}
            <div className="source-content">{source.content}</div>
            {source.url && /^https?:\/\//.test(source.url) && (
              <a
                className="text-button"
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Открыть сайт источника <ExternalLink size={16} />
              </a>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
