from typing import Optional
from flashcard.schemas.api_key import load_api_keys, APIKeyConfig

class LLMKeyProvider:
    def __init__(self):
        self._config: APIKeyConfig = load_api_keys()
        
    def get_core_key(self, name: str) -> Optional[str]:
        """
        Retrieves a core API key by name.
        """
        for entry in self._config.core:
            if entry.name == name:
                return entry.api_key
        return None

    def get_all_core_keys(self) -> dict[str, str]:
        """
        Retrieves all core API keys as a dictionary of name: api_key.
        """
        return {entry.name: entry.api_key for entry in self._config.core}

    def get_core_entries(self, provider: Optional[str] = None):
        """
        Retrieves configured core key entries, optionally filtered by provider.
        """
        if provider is None:
            return list(self._config.core)
        return [entry for entry in self._config.core if entry.provider == provider]

    def get_reminder_key(self, name: str) -> Optional[str]:
        """
        Retrieves a reminder API key by name.
        """
        for entry in self._config.reminder:
            if entry.name == name:
                return entry.api_key
        return None
        
    def get_user_keys(self, user_id: str) -> list[str]:
        """
        Retrieves keys for a specific user.
        """
        return self._config.users.get(user_id, [])

    # Example method for future client creation
    def create_client(self, provider: str = "core", name: str = "mey"):
        api_key = None
        if provider == "core":
            api_key = self.get_core_key(name)
        elif provider == "reminder":
            api_key = self.get_reminder_key(name)
            
        if not api_key:
            raise ValueError(f"API Key not found for provider {provider} and name {name}")
            
        # Placeholder for actual client creation (e.g., OpenAI, Anthropic, Google)
        # return GenericClient(api_key=api_key)
        return {"provider": provider, "api_key_masked": api_key[:5] + "..."}

# Singleton instance?
# llm_service = LLMService()
