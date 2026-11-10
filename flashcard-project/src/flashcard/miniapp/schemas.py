"""
Wire DTOs of the Mini App API (docs/mini-app.md, "API"). Responses are built from use-case
results and carry exactly the fields the contract lists; stored documents never reach the wire.
"""
import re
from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

from flashcard.app.collection import CollectionItem, ItemDetail
from flashcard.app.quota import CARD_CREDITS, SECTION_CREDITS, QuotaExceeded
from flashcard.app.study import Overview, StudyCard
from flashcard.language import LanguageConfig
from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.languages import LANGUAGE_DATA, LanguageLevel
from flashcard.schemas.user import MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, UserDB

from typing import get_args

_FLAG = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def country_from_flag(label: str) -> Optional[str]:
    """The lowercase country code of the first flag emoji in a label ("🇮🇷 FA" -> "ir"), else None."""
    match = _FLAG.search(label or "")
    if match is None:
        return None
    return "".join(chr(ord(ch) - 0x1F1E6 + ord("a")) for ch in match.group())


# ---- responses -----------------------------------------------------------------------------------

class Translation(BaseModel):
    label: str
    country: Optional[str]
    text: str


class Content(BaseModel):
    definition: Optional[str]
    translations: list[Translation]
    example: Optional[str]
    note: Optional[str]


class StudyCardOut(Content):
    delivery_id: int
    expression_id: str
    value: str
    direction: Literal["forward", "reverse"]
    from_storage: bool
    older_settings: bool


class QuotaResult(BaseModel):
    status: Literal["quota"] = "quota"
    tier: str
    # Today's credit limit.
    limit: int


class SettingsOut(BaseModel):
    target_level: str
    primary_language: str
    secondary_language: Optional[str]
    review_mode: Literal["standard", "dual"]
    review_interval_minutes: int
    is_active: bool


class LanguageOut(BaseModel):
    code: str
    name: str
    country: Optional[str]


class QuotaUsage(BaseModel):
    """Today's card credits; `limit` is null when nothing limits the user. Counters reset at 00:00 UTC."""
    used: int
    limit: Optional[int]
    card_cost: int
    section_cost: int


class Words(BaseModel):
    total: int
    ready: int
    # A delivered card is waiting for a grade.
    pending: bool


class Options(BaseModel):
    levels: list[str]
    languages: list[LanguageOut]
    min_interval: int
    max_interval: int


class MeOut(BaseModel):
    # The bot can send reminders: false for a Mini App user who has not started the bot chat.
    reminders_available: bool
    language: LanguageOut
    settings: SettingsOut
    quota: QuotaUsage
    words: Words
    options: Options


class CurrentOut(BaseModel):
    card: Optional[StudyCardOut]
    undo_available: bool


class ReadyCard(BaseModel):
    status: Literal["ready"] = "ready"
    card: StudyCardOut


class StatusOnly(BaseModel):
    status: Literal["none", "not_pending", "nothing_to_undo", "already_saved", "saved", "all_duplicates",
                    "parse_failed", "nothing_found", "invalid_language"]


class GradedOut(BaseModel):
    status: Literal["graded"] = "graded"
    undo_available: bool = True


class UndoneOut(BaseModel):
    status: Literal["undone"] = "undone"
    card: StudyCardOut


class PreviewReady(BaseModel):
    status: Literal["ready"] = "ready"
    norm: str
    content: Content
    # Card part -> key for GET /audio/{key}; only the parts that can be spoken.
    audio: dict[str, str] = Field(default_factory=dict)


class PreviewUnclear(BaseModel):
    status: Literal["unclear"] = "unclear"
    note: Optional[str]
    suggestions: list[str]


class PreviewInvalid(BaseModel):
    status: Literal["invalid"] = "invalid"
    suggestions: list[str]


class CollectionRow(BaseModel):
    id: str
    value: str
    reps: int
    lapses: int
    created_at: Optional[datetime]


class CollectionPage(BaseModel):
    items: list[CollectionRow]
    next_cursor: Optional[str]


class CollectionDetail(CollectionRow):
    content: Optional[Content]
    generated_at: Optional[datetime]


class Imported(BaseModel):
    status: Literal["imported"] = "imported"
    items: list[str]


class SaveInvalid(BaseModel):
    status: Literal["invalid"] = "invalid"
    suggestions: list[str]


class TooManyWords(BaseModel):
    status: Literal["too_many"] = "too_many"
    limit: int


class TooLong(BaseModel):
    status: Literal["too_long"] = "too_long"
    limit: int


# ---- requests ------------------------------------------------------------------------------------

class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# JavaScript's safe integer range.
_SAFE = 2**53 - 1


class GradeIn(_Request):
    delivery_id: StrictInt = Field(ge=-_SAFE, le=_SAFE)
    expression_id: StrictStr = Field(max_length=64)
    direction: Literal["forward", "reverse"]
    grade: StrictInt = Field(ge=0, le=5)


class RefreshIn(_Request):
    delivery_id: StrictInt = Field(ge=-_SAFE, le=_SAFE)
    section: Literal["definition", "translations", "example"]


class TextIn(_Request):
    text: StrictStr = Field(min_length=1, max_length=200)


class SaveIn(_Request):
    value: StrictStr = Field(min_length=1, max_length=200)

    @field_validator("value")
    @classmethod
    def _one_line(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("empty")
        return value


class ImportIn(_Request):
    # The use case answers `too_long` above its own limit; this only bounds the request itself.
    text: StrictStr = Field(min_length=1, max_length=5000)


class SettingsPatch(_Request):
    target_level: Optional[StrictStr] = None
    primary_language: Optional[StrictStr] = None
    # null turns the secondary language off.
    secondary_language: Optional[StrictStr] = None
    review_mode: Optional[StrictStr] = None
    review_interval_minutes: Optional[StrictInt] = None
    is_active: Optional[StrictBool] = None

    def changes(self) -> dict:
        """Only the fields the client sent. An explicit null is a change for `secondary_language` alone."""
        sent = {name: getattr(self, name) for name in self.model_fields_set}
        if any(value is None for name, value in sent.items() if name != "secondary_language"):
            raise ValueError("null is only allowed for secondary_language")
        return sent


# ---- conversions ---------------------------------------------------------------------------------

def content_out(card: ExpressionCard) -> Content:
    return Content(
        definition=card.learning_definition or None,
        translations=[
            Translation(label=line.label, country=country_from_flag(line.label), text=line.text)
            for line in card.translations
        ],
        example=card.learning_example or None,
        note=card.note or None,
    )


def study_card_out(card: StudyCard) -> StudyCardOut:
    return StudyCardOut(
        **content_out(card.card).model_dump(),
        delivery_id=card.delivery_id,
        expression_id=card.expression_id,
        value=card.value,
        direction=card.direction,
        from_storage=card.from_storage,
        older_settings=card.older_settings,
    )


def quota_out(result: QuotaExceeded) -> QuotaResult:
    return QuotaResult(tier=result.tier, limit=result.limit)


def settings_out(user: UserDB) -> SettingsOut:
    return SettingsOut(
        target_level=user.target_level,
        primary_language=user.primary_language,
        secondary_language=user.secondary_language,
        review_mode=user.review_mode,
        review_interval_minutes=user.review_interval_minutes,
        is_active=user.is_active,
    )


def me_out(overview: Overview, language: LanguageConfig) -> MeOut:
    return MeOut(
        reminders_available=overview.user.bot_chat_open,
        language=LanguageOut(code=language.code, name=language.name, country=country_from_flag(language.flag)),
        settings=settings_out(overview.user),
        quota=QuotaUsage(used=overview.quota.used, limit=overview.quota.limit,
                         card_cost=CARD_CREDITS, section_cost=SECTION_CREDITS),
        words=Words(total=overview.words.total, ready=overview.words.ready, pending=overview.pending),
        options=Options(
            levels=list(get_args(LanguageLevel)),
            languages=[
                LanguageOut(code=code, name=data["name"], country=country_from_flag(data["flag"]))
                for code, data in LANGUAGE_DATA.items()
            ],
            min_interval=MIN_INTERVAL_MINUTES,
            max_interval=MAX_INTERVAL_MINUTES,
        ),
    )


def row_out(item: CollectionItem) -> CollectionRow:
    return CollectionRow(id=item.id, value=item.value, reps=item.reps, lapses=item.lapses,
                         created_at=item.created_at)


def detail_out(detail: ItemDetail) -> CollectionDetail:
    return CollectionDetail(
        **row_out(detail.item).model_dump(),
        content=content_out(detail.card) if detail.card is not None else None,
        generated_at=detail.generated_at,
    )
