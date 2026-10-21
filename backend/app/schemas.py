from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl

Role = Literal["CEO", "CFO", "TREASURER"]


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
    text: str = Field(min_length=3, max_length=1800)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    feature_keys: list[str] = Field(default_factory=list, max_length=12)
    assumption: bool = False


class Insight(BaseModel):
    headline: str = Field(max_length=300)
    facts: list[Claim] = Field(default_factory=list, max_length=8)
    bank_view: list[Claim] = Field(default_factory=list, max_length=6)
    impact: list[Claim] = Field(default_factory=list, max_length=8)
    risks: list[Claim] = Field(default_factory=list, max_length=6)
    opportunities: list[Claim] = Field(default_factory=list, max_length=6)
    actions: list[Claim] = Field(default_factory=list, max_length=6)
    answer: list[Claim] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=15)


class FeedbackInput(BaseModel):
    category: Literal["useful", "irrelevant", "factual_error"]
    comment: str = Field(default="", max_length=2000)
