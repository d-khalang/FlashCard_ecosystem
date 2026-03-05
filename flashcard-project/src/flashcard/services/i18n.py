import json
import os
from importlib.resources import files
from typing import Dict, Any

class I18nService:
    def __init__(self, locales_dir: str = None):
        self.locales_dir = locales_dir
        self.translations: Dict[str, Dict[str, Any]] = {}
        self.default_lang = "en"
        self._load_locales()

    def _load_locales(self):
        """Load locale JSON either from a custom directory or package resources."""
        if self.locales_dir:
            self._load_locales_from_dir(self.locales_dir)
            return

        try:
            locales_root = files("flashcard").joinpath("resources/locales")
            for resource in locales_root.iterdir():
                if resource.name.endswith(".json"):
                    lang_code = resource.name[:-5]
                    try:
                        self.translations[lang_code] = json.loads(
                            resource.read_text(encoding="utf-8")
                        )
                    except Exception as e:
                        print(f"Error loading locale {lang_code}: {e}")
        except Exception:
            return

    def _load_locales_from_dir(self, locales_dir: str):
        if not os.path.exists(locales_dir):
            return

        for filename in os.listdir(locales_dir):
            if filename.endswith(".json"):
                lang_code = filename[:-5]
                file_path = os.path.join(locales_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self.translations[lang_code] = json.load(f)
                except Exception as e:
                    print(f"Error loading locale {lang_code}: {e}")

    def get(self, key: str, locale: str = "en", **kwargs) -> str:
        """
        Retrieves a translation string.
        Supports nested keys using dot notation (e.g., 'start.welcome').
        """
        if locale not in self.translations:
            # Try default if locale not found, but we might just use default_lang
            locale = self.default_lang
        
        keys = key.split(".")
        value = self.translations.get(locale, {})
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                value = None
                break
        
        if value is None:
            # Fallback to default lang
            if locale != self.default_lang:
                return self.get(key, locale=self.default_lang, **kwargs)
            return key  # Return key if not found
            
        if isinstance(value, str) and kwargs:
            try:
                return value.format(**kwargs)
            except KeyError:
                return value
                
        return value

# Singleton instance
i18n = I18nService()
