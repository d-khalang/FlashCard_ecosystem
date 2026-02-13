from typing import Annotated, Any, Dict, List, Optional, Literal
from pydantic import BeforeValidator

# -------------------------------------------------------------------------
# 1. Master Data Dictionary
# -------------------------------------------------------------------------
LANGUAGE_DATA: Dict[str, Dict[str, Any]] = {
    # --- Tier 1 (Native-Level) ---
    "en": {"name": "English", "flag": "🇬🇧", "aliases": ["english", "eng", "en", "us", "uk"]},
    "es": {"name": "Spanish", "flag": "🇪🇸", "aliases": ["spanish", "espanol", "es", "sp"]},
    "fr": {"name": "French", "flag": "🇫🇷", "aliases": ["french", "francais", "fr"]},
    "de": {"name": "German", "flag": "🇩🇪", "aliases": ["german", "deutsch", "de", "ger"]},
    "it": {"name": "Italian", "flag": "🇮🇹", "aliases": ["italian", "italiano", "it"]},
    "pt": {"name": "Portuguese", "flag": "🇧🇷", "aliases": ["portuguese", "portugues", "pt", "br"]},
    "ru": {"name": "Russian", "flag": "🇷🇺", "aliases": ["russian", "russkiy", "ru"]},
    "zh": {"name": "Chinese", "flag": "🇨🇳", "aliases": ["chinese", "mandarin", "zh", "cn"]},
    "ja": {"name": "Japanese", "flag": "🇯🇵", "aliases": ["japanese", "nihongo", "ja", "jp"]},
    "ko": {"name": "Korean", "flag": "🇰🇷", "aliases": ["korean", "hangul", "ko", "kr"]},
    "ar": {"name": "Arabic", "flag": "🇸🇦", "aliases": ["arabic", "arabiyya", "ar"]},
    "hi": {"name": "Hindi", "flag": "🇮🇳", "aliases": ["hindi", "hi", "in"]},
    
    # --- Tier 2 / Special Support ---
    "fa": {"name": "Persian", "flag": "🇮🇷", "aliases": ["farsi", "persian", "fa", "ir"]},
    "tr": {"name": "Turkish", "flag": "🇹🇷", "aliases": ["turkish", "turkce", "tr"]},
    "nl": {"name": "Dutch", "flag": "🇳🇱", "aliases": ["dutch", "nederlands", "nl"]},
    "pl": {"name": "Polish", "flag": "🇵🇱", "aliases": ["polish", "polski", "pl"]},
    "vi": {"name": "Vietnamese", "flag": "🇻🇳", "aliases": ["vietnamese", "tieng viet", "vi"]},
    "id": {"name": "Indonesian", "flag": "🇮🇩", "aliases": ["indonesian", "bahasa", "id"]},
    "sv": {"name": "Swedish", "flag": "🇸🇪", "aliases": ["swedish", "svenska", "sv"]},
}

NONE_LANG : Dict[str, Dict[str, Any]] = {
    "none": {"name": "None", "flag": "⚪", "aliases": ["none", "no", "none"]}
}

# -------------------------------------------------------------------------
# 2. Inverted Index for O(1) Lookup
# -------------------------------------------------------------------------
ALIAS_MAP: Dict[str, str] = {}
for code, data in LANGUAGE_DATA.items():
    ALIAS_MAP[code] = code  # Map self
    for alias in data.get("aliases", []):
        ALIAS_MAP[alias.lower()] = code

NONE_MAP: Dict[str, str] = {}
for code, data in NONE_LANG.items():
    NONE_MAP[code] = code  # Map self
    for alias in data.get("aliases", []):
        NONE_MAP[alias.lower()] = code

# -------------------------------------------------------------------------
# 3. Normalization Logic
# -------------------------------------------------------------------------
def normalize_language_input(v: Any, none_allowed: bool = False) -> str:
    """
    Normalizes a language input string to its canonical ISO code.
    Example: "Farsi" -> "fa", "EN" -> "en"
    """
    if not isinstance(v, str):
        return v  # Let Pydantic handle non-string errors if necessary, or fail later
    
    clean_v = v.strip().lower()
    
    # Check if it's already a valid key
    if clean_v in LANGUAGE_DATA:
        return clean_v
        
    # Check alias map
    if clean_v in ALIAS_MAP:
        return ALIAS_MAP[clean_v]
    
    if none_allowed and (clean_v in NONE_MAP):
        return NONE_MAP[clean_v]
        
    # If strictly required, raise error. 
    # For now, we raise ValueError so Pydantic catches it.
    raise ValueError(f"Unsupported language: {v}")

# -------------------------------------------------------------------------
# 4. Pydantic Type
# -------------------------------------------------------------------------
LanguageCode = Annotated[str, BeforeValidator(lambda v: normalize_language_input(v, none_allowed=True))]
LanguageLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

# -------------------------------------------------------------------------
# 5. Helper Functions
# -------------------------------------------------------------------------
def get_language_flag(code: str|None) -> str:
    """Returns the flag emoji for a given language code, or a default globe."""
    return LANGUAGE_DATA.get(code, {}).get("flag", "🌍")

def get_language_name(code: str) -> str:
    """Returns the display name for a given language code."""
    return LANGUAGE_DATA.get(code, {}).get("name", code.upper())
