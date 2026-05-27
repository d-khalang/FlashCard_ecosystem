from __future__ import annotations
import os
from fastapi import Header, HTTPException
from typing import Optional
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .db_core import get_conjugations
from .filters import apply_filters
from .models import ConjugateQuery, APIResponse, ConjugationResponse, Mood, Tense, Person

API_KEY = os.getenv("SCRAPER_API_KEY")  # set via Docker env
app = FastAPI(title="WR Italian Conjugation API", version="0.3.0")

@app.get("/health")
def health() -> dict:
    return {"ok": True}

def _csv_to_list(s: Optional[str]) -> Optional[list[str]]:
    if not s:
        return None
    return [part.strip() for part in s.split(",") if part.strip()]

@app.get("/conjugate", response_model=APIResponse)
def conjugate(
    v: str = Query(..., min_length=1, description="Italian verb (infinitive)"),
    full: bool = Query(True, description="If true, return full JSON and ignore filters"),
    moods: Optional[str] = Query(None, description="CSV moods (Literal): indicativo,tempi composti,congiuntivo,condizionale,imperativo"),
    tenses: Optional[str] = Query(None, description="CSV tenses (Literal)"),
    persons: Optional[str] = Query(None, description="CSV persons (Literal)"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    # ---- API key check (one liner) ----
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

    """
    Query params are CSV, but validated against Literal sets via a Pydantic model.
    If an invalid value is provided, we return HTTP 400 with a clear message.
    """
    try:
        req = ConjugateQuery(
            v=v,
            full=full,
            moods=_csv_to_list(moods),
            tenses=_csv_to_list(tenses),
            persons=_csv_to_list(persons),
        )
    except ValidationError as ve:
        return JSONResponse(
            status_code=400,
            content=APIResponse(success=False, error=ve.errors()[0]["msg"]).model_dump()
        )

    try:
        data = get_conjugations(req.v)
        if not data or not data.get("conjugations"):
            return APIResponse(success=False, error="Verb not found in offline database", requested=req)

        filtered = apply_filters(data,
                                 ",".join(req.moods) if req.moods else None,
                                 ",".join(req.tenses) if req.tenses else None,
                                 ",".join(req.persons) if req.persons else None,
                                 req.full)

        if not filtered.get("conjugations"):
            return APIResponse(
                success=True,
                note="Lookup OK, but filters returned no items.",
                requested=req,
                data=ConjugationResponse(**filtered),
            )

        return APIResponse(success=True, requested=req, data=ConjugationResponse(**filtered))

    except Exception as e:
        return APIResponse(success=False, error=str(e), requested=req)
