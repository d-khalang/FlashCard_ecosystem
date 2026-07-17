import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel

class KeyEntry(BaseModel):
    name: str
    api_key: str
    provider: str = "google"

class APIKeyConfig(BaseModel):
    core: List[KeyEntry]
    reminder: List[KeyEntry]
    users: Dict[str, List[str]]

@lru_cache()
def load_api_keys(key_file: Optional[Union[str, Path]] = None) -> APIKeyConfig:
    """
    Load API keys from an external file or the packaged resource fallback.
    """
    resource_path = (
        Path(key_file).expanduser()
        if key_file
        else files("flashcard").joinpath("resources/llm_key.json")
    )

    try:
        data = json.loads(resource_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"API key file not found at {resource_path}"
        ) from exc

    return APIKeyConfig.model_validate(data)
