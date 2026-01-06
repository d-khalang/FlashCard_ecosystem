from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional 


class TranslationLine(BaseModel):
    label: str = Field(..., description='Line label, e.g. "🇩🇪 DE" or "🇬🇧 EN"')
    text: str = Field(..., description="1–2 common translations in that language")

class ExpressionCard(BaseModel):
    # Core outcome
    success: bool = Field(..., description="True if input was understood")

    # Normalization result (typo-fix + normalization rules)
    norm: str = Field(..., description="Normalized + typo-corrected intended Italian token/phrase")

    # When success=true
    # When success=true
    def_it: Optional[str] = Field(description="Italian definition at user level")
    translations: List[TranslationLine] = Field(description="Exactly two items, in user order")
    example_it: Optional[str] = Field(description='Italian example sentence, no translation')

    # When success=false
    note_it: Optional[str] = Field(description='E.g. "Parola non chiara"')
    suggestions: List[str] = Field(description="Candidate intended tokens")