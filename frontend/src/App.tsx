import { useEffect, useState } from "react";
import type { FormEvent } from "react";
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
};
type Feature = {
  value: unknown;
  source: string;
  status: string;
  label: string;
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
};
type EventItem = {
  id: string;
  title: string;
  summary: string;
  publisher: string;
  score: number;
  reasons: string[];
  topics: string[];
  published_at: string;
  synthetic: boolean;
  source_count: number;
};
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
};
type Claim = {
  text: string;
  evidence_ids: string[];
  feature_keys: string[];
  assumption: boolean;
};
type Insight = {
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
  status: string;
  stage: string;
  result: Insight | null;
  error: string | null;
  question: string | null;
  trace: { step: string; at: string; details: unknown }[];
};
type Source = {
  title: string;
  content: string;
  publisher: string;
  url: string | null;
  synthetic: boolean;
  ingestion: { coverage?: string; fetched_at?: string; warning?: string };
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
  runs: Record<string, number>;
  feedback: Record<string, number>;
  budgets: { day: string; spent_rub: number }[];
  latency_avg_seconds: number | null;
  insufficient_count: number;
  source_errors: number;
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
const formatValue = (key: string, value: unknown): string =>
  value === null || value === undefined
    ? "Нет данных"
    : typeof value === "boolean"
      ? value
        ? "Да"
        : "Нет"
      : key === "REVENUE_COMPANY"
        ? `${(Number(value) / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млрд ₽`
        : key === "outgoing_concentration"
          ? `${Math.round(Number(value) * 100)}%`
          : String(value);

function Logo() {
  return (
    <div className="brand">
      <span className="brand-symbol">
        А<span />
      </span>
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
            Компании и начальные материалы синтетические.
          </p>
        </div>
      </section>
    </main>
  );
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
                    {labels[k] || k}
                    <small>
                      {f.status === "calculated" ? "Расчет" : "Исходные данные"}{" "}
                      · {f.source}
                    </small>
                  </span>
                  <strong>{formatValue(k, f.value)}</strong>
                </div>
              ))}
            </div>
          </div>
          <div className="panel">
            <h3>Платежные связи</h3>
            <p className="muted small">
              Связь показывает платежи внутри выборки и не определяет тип
              договора.
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
              <span>До 20 МБ</span>
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
              Импортированные компании добавятся текущему администратору.
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
            {claim.evidence_ids.map((id) => {
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
                    {insight.evidence.indexOf(e) + 1}
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

function Analysis({
  runId,
  onBack,
  onSource,
}: {
  runId: string;
  onBack: () => void;
  onSource: (id: string) => void;
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
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const insight = run?.result;
  return (
    <div className="analysis-page">
      <button className="text-button back" onClick={onBack}>
        <ArrowLeft size={17} /> К событиям
      </button>
      {error && <ErrorBox error={error} />}
      <div className="analysis-heading">
        <span className="eyebrow">ПЕРСОНАЛЬНЫЙ РАЗБОР</span>
        <h1>{insight?.headline || "Собираем контекст события"}</h1>
        {insight && (
          <div className="analysis-byline">
            <Building2 size={16} /> {insight.company_name}
            <span>·</span>
            {roles[insight.role as Role]}
            <span
              className={
                "pill " +
                (insight.verification === "checked" ? "green" : "amber")
              }
            >
              <ShieldCheck size={13} />
              {insight.verification === "checked"
                ? "Основания проверены"
                : "Ограниченные основания"}
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
        <ErrorBox error={run.error || "Анализ не завершен"} />
      )}{" "}
      {insight && (
        <>
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
              Источники <span>{insight.evidence.length}</span>
            </button>
            <button
              className={tab === "trace" ? "active" : ""}
              onClick={() => setTab("trace")}
            >
              Как получен вывод <span>{run?.trace.length}</span>
            </button>
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
                <section className="panel impact-panel">
                  <div className="section-label">
                    <Sparkles size={18} /> ВЛИЯНИЕ НА ВАШ БИЗНЕС
                  </div>
                  <Claims
                    claims={insight.impact}
                    insight={insight}
                    onSource={onSource}
                  />
                  {!insight.impact.length && (
                    <p>
                      Персональная интерпретация не опубликована: недостаточно
                      подтвержденных оснований.
                    </p>
                  )}
                </section>
                <section className="panel">
                  <div className="section-label">
                    <BookOpen size={18} />{" "}
                    {insight.evidence.some(
                      (e) => e.kind === "bank" && e.synthetic,
                    )
                      ? "УЧЕБНАЯ АНАЛИТИКА · НЕ ПОЗИЦИЯ БАНКА"
                      : "ПОЗИЦИЯ АЛЬФА-БАНКА"}
                  </div>
                  {insight.bank_view.length ? (
                    <Claims
                      claims={insight.bank_view}
                      insight={insight}
                      onSource={onSource}
                    />
                  ) : (
                    <p className="muted">
                      Подходящий материал банка не найден. Мнение банка не
                      достраивается.
                    </p>
                  )}
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
                  <h3>Разберемся глубже</h3>
                  <p className="muted small">
                    Уточните влияние события. Ответ использует контекст компании
                    и проверяемые источники.
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
            <div className="sources-grid">
              {insight.evidence.map((e, i) => (
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
          )}
          {tab === "trace" && (
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
          ["Среднее время", `${metrics.latency_avg_seconds ?? "—"} сек`],
        ].map(([l, v]) => (
          <div className="panel metric" key={l}>
            <span>{l}</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>
      <div className="two-columns">
        <div className="panel">
          <h3>Качество и обратная связь</h3>
          {Object.entries({
            "Недостаточно оснований": metrics.insufficient_count,
            "Ошибки источников": metrics.source_errors,
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
        </div>
        <div className="panel">
          <h3>Бюджет моделей</h3>
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

export default function App() {
  const [corpus, setCorpus] = useState<"real" | "synthetic">("real");
  const [feedStatus, setFeedStatus] = useState<FeedStatus | null>(null);
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
  const [page, setPage] = useState("feed"),
    [runId, setRunId] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0),
    [source, setSource] = useState<Source | null>(null),
    [sourceBusy, setSourceBusy] = useState(false);
  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    if (!user) return;
    let active = true;
    api<Company[]>("/companies")
      .then((c) => {
        if (active) {
          setCompanies(c);
          setCompanyId((id) =>
            c.some((v) => v.id === id) ? id : c[0]?.id || "",
          );
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
    Promise.all([
      api<Context>(`/companies/${encodeURIComponent(companyId)}/context`),
      api<{ items: EventItem[]; topics: Record<string, string> }>(
        `/feed?company_id=${encodeURIComponent(companyId)}&role=${role}&corpus=${corpus}`,
      ),
    ])
      .then(([c, f]) => {
        if (active) {
          setContext(c);
          setItems(f.items);
          setTopics(f.topics);
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
  }, [companyId, role, revision, corpus, companies]);
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
          const feed = await api<{ items: EventItem[]; topics: Record<string, string> }>(
            `/feed?company_id=${encodeURIComponent(companyId)}&role=${role}&corpus=${corpus}`,
          );
          if (active) { setItems(feed.items); setTopics(feed.topics); }
        }
      } catch { /* Transient refresh errors keep the current view intact. */ }
      finally { pending = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [user, companyId, role, corpus, page, runId, revision]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSource(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);
  async function analyze(event: EventItem) {
    setError("");
    try {
      const r = await post<{ run_id: string }>("/analyses", {
        company_id: companyId,
        event_id: event.id,
        role,
      });
      setRunId(r.run_id);
    } catch (e) {
      setError((e as Error).message);
    }
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
  const filtered = items.filter(
    (i) =>
      (!topic || i.topics.includes(topic)) &&
      (i.title + i.summary).toLowerCase().includes(search.toLowerCase()),
  );
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
          {user.is_admin && (
            <>
              <div className="workspace-label">РАБОТА С ДАННЫМИ</div>
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
                : "Модели подключены"}
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
                      ? "Источники и данные"
                      : "Качество и бюджет"}
              </h1>
              <p className="muted">
                {page === "feed"
                  ? "Главное для вашей компании. С объяснением, почему это важно."
                  : page === "context"
                    ? "Факты, связи и ограничения, на которых строится персонализация."
                    : page === "import"
                      ? "Добавляйте материалы и проверяйте анализ на новых событиях."
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
          <div className="selector-bar">
            <div className="select-company">
              <Building2 size={19} />
              <label>
                <span>Компания</span>
                <select
                  aria-label="Компания"
                  value={companyId}
                  onChange={(e) => setCompanyId(e.target.value)}
                >
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
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
          {page === "feed" &&
            (runId ? (
              <Analysis
                runId={runId}
                onBack={() => setRunId(null)}
                onSource={(id) => void openSource(id)}
              />
            ) : (
              <>
                <div className="corpus-bar">
                  <div className="corpus-tabs" aria-label="Материалы ленты">
                    <button aria-pressed={corpus === "real"} onClick={() => { setCorpus("real"); setTopic(""); setSearch(""); }}>Реальные новости</button>
                    {context?.synthetic && <button aria-pressed={corpus === "synthetic"} onClick={() => { setCorpus("synthetic"); setTopic(""); setSearch(""); }}>Учебные события</button>}
                  </div>
                  {feedStatus && <span className="muted small">{feedStatus.automatic ? `Автообновление · каждые ${Math.round(feedStatus.interval_seconds / 60)} мин` : "Автообновление отключено"}</span>}
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
                        {items.length.toString().padStart(2, "0")}
                      </strong>
                      <span>событий в контексте</span>
                    </div>
                    <div>
                      <strong>
                        {items
                          .filter((i) => i.score >= 40)
                          .length.toString()
                          .padStart(2, "0")}
                      </strong>
                      <span>с высоким приоритетом</span>
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
                    <div className="filters">
                      <button
                        className={!topic ? "active" : ""}
                        onClick={() => setTopic("")}
                      >
                        Все события
                      </button>
                      {Object.entries(topics)
                        .filter(([t]) =>
                          items.some((i) => i.topics.includes(t)),
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
                                  (event.score >= 40 ? "high" : "normal")
                                }
                              >
                                <span />
                                {event.score >= 40
                                  ? "Высокая значимость"
                                  : "В контексте бизнеса"}
                              </span>
                              <span>
                                <Clock3 size={13} />
                                {date(event.published_at)}
                              </span>
                            </div>
                            <button
                              className="event-title"
                              onClick={() => void analyze(event)}
                            >
                              {event.title}
                            </button>
                            <p className="event-summary">{event.summary}</p>
                            <div className="relevance">
                              <span>
                                <Sparkles size={15} />
                              </span>
                              <div>
                                <strong>Почему важно для вас</strong>
                                <p>{event.reasons.slice(0, 2).join(". ")}</p>
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
                                onClick={() => void analyze(event)}
                              >
                                Разобрать влияние
                                <ArrowRight size={16} />
                              </button>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <div className="panel empty">
                        <Search size={30} />
                        <h3>Пока нет подходящих событий</h3>
                        <p>
                          {corpus === "real" && !items.length
                            ? feedStatus?.automatic === false
                              ? "Автообновление отключено. Администратор может загрузить новости в разделе «Источники и импорт»."
                              : "Новости появятся здесь после обработки. Состояние автоматической загрузки показано выше."
                            : "Измените фильтр или загрузите материал в разделе источников."}
                        </p>
                      </div>
                    )}
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
          {page === "import" && user.is_admin && (
            <ImportPanel onChange={() => setRevision((r) => r + 1)} />
          )}
          {page === "metrics" && user.is_admin && <MetricsPanel />}
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
                {source.ingestion.coverage === "summary" ? "Только RSS-аннотация" : "Текст статьи"}
              </span>
              {source.ingestion.fetched_at && <span className="muted small">Загружено {new Date(source.ingestion.fetched_at).toLocaleString("ru-RU")}</span>}
            </p>}
            {source.ingestion?.warning && <p className="muted small">{source.ingestion.warning}</p>}
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
