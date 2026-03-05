import json
from importlib.resources import files
from typing import Dict, List
from functools import lru_cache

from pydantic import BaseModel

class KeyEntry(BaseModel):
    name: str
    api_key: str

class APIKeyConfig(BaseModel):
    core: List[KeyEntry]
    reminder: List[KeyEntry]
    users: Dict[str, List[str]]

@lru_cache()
def load_api_keys() -> APIKeyConfig:
    """
    Load API keys from packaged resource data.
    """
    resource_path = files("flashcard").joinpath("resources/llm_key.json")

    try:
        data = json.loads(resource_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"API key file not found in package resources at {resource_path}"
        ) from exc
        
    return APIKeyConfig(**data)
