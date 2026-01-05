from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, constr

# ---- Literals: exactly what we scrape from WR ----
Mood = Literal[
    "indicativo",
    "tempi composti",
    "congiuntivo",
    "condizionale",
    "imperativo",
]

TenseIndicativo = Literal["presente", "imperfetto", "passato remoto", "futuro semplice"]
TenseTempiComposti = Literal["passato prossimo", "trapassato prossimo", "trapassato remoto", "futuro anteriore"]
TenseCongiuntivo = Literal["presente", "imperfetto", "passato", "trapassato"]
TenseCondizionale = Literal["presente", "passato"]
TenseImperativo = Literal["presente"]

# Union of all tenses
Tense = Literal[
    "presente", "imperfetto", "passato remoto", "futuro semplice",
    "passato prossimo", "trapassato prossimo", "trapassato remoto", "futuro anteriore",
    "passato", "trapassato",
]

PersonDefault = Literal["io", "tu", "lui, lei, Lei, egli", "noi", "voi", "loro, Loro, essi"]
PersonImperative = Literal["", "(tu)", "(Lei)", "(noi)", "(voi)", "(Loro)"]
Person = Literal["", "(tu)", "(Lei)", "(noi)", "(voi)", "(Loro)",
                 "io", "tu", "lui, lei, Lei, egli", "noi", "voi", "loro, Loro, essi"]

# ---- Request / Response models ----
class ConjugationQuery(BaseModel):
    v: constr(min_length=1) = Field(..., description="Italian verb (infinitive)")
    full: bool = Field(True, description="If true, return full JSON and ignore filters")
    moods: Optional[List[Mood]] = Field(None, description="Allowed: indicativo, tempi composti, congiuntivo, condizionale, imperativo")
    tenses: Optional[List[Tense]] = Field(None, description="Allowed: presente, imperfetto, passato remoto, futuro semplice, passato prossimo, trapassato prossimo, trapassato remoto, futuro anteriore, passato, trapassato")
    persons: Optional[List[Person]] = Field(None, description="Allowed: io/tu/... or '', (tu), (Lei), (noi), (voi), (Loro)")

class ConjugationResponse(BaseModel):
    queried: str
    url: str
    model: Optional[str] = None
    principal_forms: Dict[str, Any]
    auxiliary: Optional[str] = None
    conjugations: Dict[str, Dict[str, Dict[str, str]]]

class ConjugationAPIResponse(BaseModel):
    success: bool
    requested: Optional[ConjugationQuery] = None
    note: Optional[str] = None
    error: Optional[str] = None
    data: Optional[ConjugationResponse] = None

class ConjugationDBResponse(BaseModel):
    verb: str
    data: ConjugationResponse