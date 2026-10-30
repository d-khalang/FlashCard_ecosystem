from __future__ import annotations

from typing import List, Literal, Optional

from bson import ObjectId
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator

from flashcard.utils.logger import get_logger
from flashcard.utils.time import UtcDatetime

logger = get_logger(__name__)

# Grading rules, enforced by ExpressionService.grade_expression.
MIN_GRADE = 0
MAX_GRADE = 5
Direction = Literal["forward", "reverse"]


class TranslationLine(BaseModel):
    label: str = Field(..., description='Line label, e.g. "🇮🇷 FA" or "🇬🇧 EN"')
    text: str = Field(..., description="1–2 common translations in that language")

class ExpressionCard(BaseModel):
    # Core outcome
    success: bool = Field(..., description="True if input was understood")

    # Normalization result (typo-fix + normalization rules)
    norm: str = Field(..., description="Normalized + typo-corrected intended learning-language token/phrase")

    # When success=true
    learning_definition: Optional[str] = Field(
        description="Learning-language definition at user level",
        validation_alias=AliasChoices("learning_definition", "def_it"),
    )
    translations: List[TranslationLine] = Field(description="List of translations matching the requested languages (1 or 2 items).")
    learning_example: Optional[str] = Field(
        description="Learning-language example sentence, no translation",
        validation_alias=AliasChoices("learning_example", "example_it"),
    )

    # When success=false
    note: Optional[str] = Field(
        description='E.g. "Word/expression not clear"',
        validation_alias=AliasChoices("note", "note_it"),
    )
    suggestions: List[str] = Field(description="Candidate intended tokens")


class CardSettings(BaseModel):
    """User settings a card was generated with."""
    level: str
    primary_language: str
    secondary_language: Optional[str] = None


class StoredCard(BaseModel):
    """The latest successful card of an expression: the fallback when all providers fail."""
    card: ExpressionCard
    settings: CardSettings
    generated_at: UtcDatetime


# Counters a stored document may hold as null; they read as 0.
_STATS_FIELDS = ("reps", "lapses", "success_streak", "ewma_grade", "last_grade")


def _null_as_zero(value):
    return 0 if value is None else value


class ExpressionStats(BaseModel):
    """
    Stats for a specific direction (Forward or Reverse).
    """
    reps: int = 0
    lapses: int = 0
    success_streak: int = 0
    ewma_grade: float = 0.0
    last_grade: int = 0
    last_review_at: Optional[UtcDatetime] = None
    # next_review_at: Optional[str] = None # Calculated next review time

    _stats_null_as_zero = field_validator(*_STATS_FIELDS, mode="before")(_null_as_zero)

class ExpressionDB(BaseModel):
    user_id: str = Field(..., description="Stored user id (text); services write it with stored_user_id")
    value: str = Field(..., description="The expression text")
    created_at: UtcDatetime = Field(..., description="Creation time")
    last_sent_at: Optional[UtcDatetime] = Field(None, description="Last send of either side")
    last_interaction_at: Optional[UtcDatetime] = Field(None, description="Last review of the forward side")
    last_activity_at: Optional[UtcDatetime] = Field(None, description="Last send/grade event (global cooldown)")
    
    # Forward Stats (Root Level - Backward Compatibility)
    reps: int = 0
    lapses: int = 0
    success_streak: int = 0
    ewma_grade: float = 0.0
    last_grade: int = 0
    
    # Dual Mode
    reverse_stats: Optional[ExpressionStats] = None
    
    pending_message_id: Optional[int] = None  # Telegram message id
    status: str = "active"

    # Overwritten by each successful review; one card, no history.
    last_card: Optional[StoredCard] = None


class Expression(ExpressionDB):
    """
    A stored expression as read back, with its id. Reading is forgiving where a legacy
    document may lack a value the bot can do without; anything else makes it unreadable,
    and readers skip it (one bad card never blocks a user's other cards).
    """
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., alias="_id", min_length=1)
    value: str = Field(..., min_length=1, description="The expression text; an empty one is unreadable")
    created_at: Optional[UtcDatetime] = Field(None, description="Missing on some legacy cards")

    _stats_null_as_zero = field_validator(*_STATS_FIELDS, mode="before")(_null_as_zero)

    @field_validator("status", mode="before")
    @classmethod
    def _null_status_is_active(cls, value):
        """Missing or null status counts as active, as in ExpressionService.ACTIVE."""
        return "active" if value is None else value

    @field_validator("id", mode="before")
    @classmethod
    def _object_id_as_text(cls, value):
        return str(value) if isinstance(value, ObjectId) else value

    @field_validator("last_card", mode="before")
    @classmethod
    def _unreadable_stored_card_reads_as_none(cls, value):
        """The stored card is only a fallback: an unreadable one is dropped, not the expression."""
        if value is None or isinstance(value, StoredCard):
            return value
        try:
            return StoredCard.model_validate(value)
        except ValidationError:
            logger.warning("Unreadable stored card dropped", exc_info=True)
            return None

    @property
    def forward_stats(self) -> ExpressionStats:
        """The forward direction's stats, stored at the root (`last_interaction_at` is its review time)."""
        return ExpressionStats(reps=self.reps, lapses=self.lapses, success_streak=self.success_streak,
                               ewma_grade=self.ewma_grade, last_grade=self.last_grade,
                               last_review_at=self.last_interaction_at)

    def stats(self, direction: Direction) -> ExpressionStats:
        """Stats for one direction; a reverse side never reviewed starts empty."""
        if direction == "forward":
            return self.forward_stats
        return self.reverse_stats or ExpressionStats()


class ReviewCandidate(BaseModel):
    """The card and direction picked for the next review."""
    expression: Expression
    direction: Direction
