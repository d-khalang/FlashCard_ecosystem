import json
from pathlib import Path
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
    Loads the API keys from the configuration file.
    The file is expected to be at src/flashcard/resources/llm_key.json.
    """
    # Resolve path relative to this file: schemas/api_key.py -> ../resources/llm_key.json
    base_path = Path(__file__).parent.parent
    key_file = base_path / "resources" / "llm_key.json"
    
    if not key_file.exists():
        raise FileNotFoundError(f"API key file not found at {key_file}")
        
    with open(key_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    return APIKeyConfig(**data)

apikeys = load_api_keys()
