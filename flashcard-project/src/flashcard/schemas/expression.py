from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field
from typing import List, Literal, Optional

from flashcard.utils.time import UtcDatetime

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
