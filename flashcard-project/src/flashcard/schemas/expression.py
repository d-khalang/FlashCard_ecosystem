from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional 


class TranslationLine(BaseModel):
    label: str = Field(..., description='Line label, e.g. "🇮🇷 FA" or "🇬🇧 EN"')
    text: str = Field(..., description="1–2 common translations in that language")

class ExpressionCard(BaseModel):
    # Core outcome
    success: bool = Field(..., description="True if input was understood")

    # Normalization result (typo-fix + normalization rules)
    norm: str = Field(..., description="Normalized + typo-corrected intended Italian token/phrase")

    # When success=true
    def_it: Optional[str] = Field(description="Italian definition at user level")
    translations: List[TranslationLine] = Field(description="Exactly two items, in user order")
    example_it: Optional[str] = Field(description='Italian example sentence, no translation')

    # When success=false
    note_it: Optional[str] = Field(description='E.g. "Parola non chiara"')
    suggestions: List[str] = Field(description="Candidate intended tokens")


class ExpressionStats(BaseModel):
    """
    Stats for a specific direction (Forward or Reverse).
    """
    reps: int = 0
    lapses: int = 0
    success_streak: int = 0
    ewma_grade: float = 0.0
    last_grade: int = 0
    last_review_at: Optional[str] = None
    # next_review_at: Optional[str] = None # Calculated next review time

class ExpressionDB(BaseModel):
    user_id: str = Field(..., description="User ID as string")
    value: str = Field(..., description="The expression text")
    created_at: str = Field(..., description="Creation timestamp ISO")
    last_sent_at: Optional[str] = Field(None, description="Timestamp of last send of both sides")
    last_interaction_at: Optional[str] = Field(None, description="Timestamp of last review of the forward side")
    last_activity_at: Optional[str] = Field(None, description="Timestamp of last send/grade event (global cooldown)")
    
    # Forward Stats (Root Level - Backward Compatibility)
    reps: int = 0
    lapses: int = 0
    success_streak: int = 0
    ewma_grade: float = 0.0
    last_grade: int = 0
    
    # Dual Mode
    reverse_stats: Optional[ExpressionStats] = None
    
    pending_message_id: Optional[str] = None
    status: str = "active"
