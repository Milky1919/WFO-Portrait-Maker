import json
import os

class LocalizationManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(LocalizationManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.language = "JP"
            self.translations = {}
            self.initialized = True

    def load_language(self, language_code: str):
        """Loads the language file for the given code (e.g., 'JP', 'EN')."""
        self.language = language_code
        
        # Map code to filename
        filename = "jp.json" if language_code == "JP" else "en.json"
        
        # Path relative to this file: ../../assets/locales/
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        locales_path = os.path.join(base_path, "assets", "locales", filename)
        
        if os.path.exists(locales_path):
            try:
                with open(locales_path, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
            except Exception as e:
                print(f"Error loading locale {filename}: {e}")
                self.translations = {}
        else:
            print(f"Locale file not found: {locales_path}")
            self.translations = {}

    def get(self, key: str, default: str = None) -> str:
        """Retrieves a localized string."""
        keys = key.split('.')
        value = self.translations
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default or key
        
        if value is None:
            return default or key
        return str(value)

# Global instance
loc = LocalizationManager()
