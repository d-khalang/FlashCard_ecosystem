"""Quota results shared by use cases that call the LLM."""
from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaExceeded:
    tier: str
    limit: int
