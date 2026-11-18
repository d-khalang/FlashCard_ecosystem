"""
What the conjugator v2 answers (docs/verbs/contract.md, sections 1-3). The verb object passes
to the Mini App unchanged, so these models are also part of the Mini App API.

Unknown fields are ignored, so a newer conjugator that adds one does not break the bot;
the fixture test checks that every field the contract names is read and written back.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

Mood = Literal["indicativo", "congiuntivo", "condizionale", "imperativo"]
Person = Literal["1s", "2s", "3s", "1p", "2p", "3p"]
PERSONS: tuple[Person, ...] = ("1s", "2s", "3s", "1p", "2p", "3p")

# The 15 tense ids in canonical order (the order of Verb.tenses).
TENSE_IDS: tuple[str, ...] = (
    "indicativo-presente", "indicativo-imperfetto", "indicativo-passato_remoto", "indicativo-futuro_semplice",
    "indicativo-passato_prossimo", "indicativo-trapassato_prossimo", "indicativo-trapassato_remoto",
    "indicativo-futuro_anteriore",
    "congiuntivo-presente", "congiuntivo-imperfetto", "congiuntivo-passato", "congiuntivo-trapassato",
    "condizionale-presente", "condizionale-passato", "imperativo-presente",
)
TenseId = Literal[
    "indicativo-presente", "indicativo-imperfetto", "indicativo-passato_remoto", "indicativo-futuro_semplice",
    "indicativo-passato_prossimo", "indicativo-trapassato_prossimo", "indicativo-trapassato_remoto",
    "indicativo-futuro_anteriore",
    "congiuntivo-presente", "congiuntivo-imperfetto", "congiuntivo-passato", "congiuntivo-trapassato",
    "condizionale-presente", "condizionale-passato", "imperativo-presente",
]


class SimpleParts(BaseModel):
    kind: Literal["simple"]
    clitic: Optional[str]
    stem: str
    ending: str
    irregular_stem: bool
    irregular_ending: bool


class CompoundParts(BaseModel):
    kind: Literal["compound"]
    clitic: Optional[str]
    auxiliary_verb: Literal["essere", "avere"]
    auxiliary: str
    participle: str
    irregular_participle: bool


class Form(BaseModel):
    text: str
    primary: bool
    tags: list[str]
    tts: str
    irregular: bool
    parts: Annotated[Union[SimpleParts, CompoundParts], Field(discriminator="kind")]


class Slot(BaseModel):
    person: Person
    # Empty: the form does not exist (defective verb).
    forms: list[Form]

    @property
    def primary(self) -> Optional[Form]:
        return next((form for form in self.forms if form.primary), self.forms[0] if self.forms else None)


class Tense(BaseModel):
    id: TenseId
    mood: Mood
    tense: str
    compound: bool
    slots: list[Slot]


class Auxiliary(BaseModel):
    verb: Literal["essere", "avere"]
    primary: bool
    note: Optional[str]


class PrincipalForms(BaseModel):
    gerund: Optional[str]
    past_participle: Optional[str]
    present_participle: Optional[str]


class Verb(BaseModel):
    infinitive: str
    pronominal: Optional[str]
    auxiliaries: list[Auxiliary]
    principal_forms: PrincipalForms
    irregular: bool
    data_version: str
    tenses: list[Tense]

    def tense(self, tense_id: str) -> Optional[Tense]:
        return next((tense for tense in self.tenses if tense.id == tense_id), None)


class MatchSlot(BaseModel):
    tense_id: TenseId
    person: Person


class Match(BaseModel):
    query: str
    kind: Literal["infinitive", "form", "fuzzy"]
    slots: list[MatchSlot]
    candidates: list[str]


class Conjugation(BaseModel):
    """200 of GET /v2/conjugate."""
    match: Match
    verb: Verb


class ErrorBody(BaseModel):
    code: str
    message: str


class VerbNotFound(BaseModel):
    """404 of GET /v2/conjugate."""
    error: ErrorBody
    suggestions: list[str]


class Suggestions(BaseModel):
    """200 of GET /v2/suggest."""
    items: list[str]


class InfinitivesRequest(BaseModel):
    """Body of POST /v2/infinitives (at most 500 words)."""
    words: list[str]


class Infinitives(BaseModel):
    """200 of POST /v2/infinitives: word -> infinitive, or null for anything but an infinitive."""
    infinitives: dict[str, Optional[str]]
