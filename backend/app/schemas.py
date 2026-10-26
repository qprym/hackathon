from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Role = Literal["CEO", "CFO", "TREASURER"]


class FeedPage(BaseModel):
    model_config = ConfigDict(extra='allow')
    items: list[dict] = Field(description='Карточки в персональном порядке с reasons, ranking_grounds и applicability')
    feed_version: str = Field(description='Неизменяемый снимок на 24 часа, привязанный к пользователю, контексту и фильтрам')
    total: int
    offset: int
    next_offset: int | None
    list_selection: dict | None = Field(default=None,description='Состояние обработки и версия полного отбора')
    pipeline: dict = Field(default_factory=dict,description='Автоматическая обработка и доступность настроенной модели')
    personalization: dict = Field(default_factory=dict,description='Готовность персонализации независимо от фильтров; not_processed не означает нерелевантность')
    available_topics: list[str] = Field(default_factory=list,description='Темы всей подборки до поиска, тематического фильтра и пагинации')


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class Analyze(BaseModel):
    company_id: str
    event_id: str
    role: Role = "CFO"


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class NewsInput(BaseModel):
    title: str = Field(min_length=5, max_length=500)
    content: str = Field(min_length=60, max_length=100000)
    publisher: str = Field(min_length=2, max_length=200)
    url: HttpUrl | None = None
    published_at: datetime
    kind: Literal["news", "bank"] = "news"
    synthetic: bool = False


class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=3, max_length=1800)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    feature_keys: list[str] = Field(default_factory=list, max_length=12)
    assumption: bool = False


class Insight(BaseModel):
    model_config = ConfigDict(extra='forbid')
    headline: str = Field(max_length=300)
    facts: list[Claim] = Field(default_factory=list, max_length=8)
    bank_view: list[Claim] = Field(default_factory=list, max_length=6)
    impact: list[Claim] = Field(default_factory=list, max_length=8)
    risks: list[Claim] = Field(default_factory=list, max_length=6)
    opportunities: list[Claim] = Field(default_factory=list, max_length=6)
    actions: list[Claim] = Field(default_factory=list, max_length=6)
    answer: list[Claim] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=15)


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence_id: str
    quote: str = Field(min_length=3, max_length=900)


class ReviewCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str
    verdict: Literal['supported', 'unsupported', 'uncertain']
    category: Literal['none', 'grounds', 'temporal', 'scope', 'causality', 'attribution', 'company', 'contradiction']
    text_span: str = Field(min_length=3, max_length=1800)
    reason: str = Field(min_length=10, max_length=1200)
    quotes: list[EvidenceQuote] = Field(default_factory=list, max_length=12)
    quote_ids: list[str] = Field(default_factory=list, max_length=12)
    feature_keys: list[str] = Field(default_factory=list, max_length=12)
    correction: str = Field(default='', max_length=900)
    missing_feature_keys: list[str] = Field(default_factory=list, max_length=12)


class ReviewNote(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str
    suggestion: str = Field(min_length=3, max_length=500)


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    checks: list[ReviewCheck] = Field(min_length=1, max_length=66)
    editorial_notes: list[ReviewNote] = Field(default_factory=list, max_length=10)
    search_queries: list[str] = Field(default_factory=list, max_length=2)


class ClaimEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str
    replacement: Claim | str | None


class InsightPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    edits: list[ClaimEdit] = Field(min_length=1, max_length=66)


class FeedbackInput(BaseModel):
    category: Literal["useful", "irrelevant", "factual_error"]
    comment: str = Field(default="", max_length=2000)
