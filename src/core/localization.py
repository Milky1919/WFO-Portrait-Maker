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

    def get_locales_path(self):
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(base_path, "assets", "locales")

    def get_available_languages(self):
        """Scans the locales directory and returns a list of available language codes (uppercase)."""
        locales_path = self.get_locales_path()
        if not os.path.exists(locales_path):
            return ["JP"] # Fallback
            
        langs = []
        import glob
        for file in glob.glob(os.path.join(locales_path, "*.json")):
            basename = os.path.basename(file)
            lang_code = os.path.splitext(basename)[0].upper()
            langs.append(lang_code)
            
        if not langs:
            return ["JP"]
            
        # Sort: JP first, then EN, then others alphabetically
        langs.sort()
        if "EN" in langs:
            langs.remove("EN")
            langs.insert(0, "EN")
        if "JP" in langs:
            langs.remove("JP")
            langs.insert(0, "JP")
            
        return langs

    def load_language(self, language_code: str):
        """Loads the language file for the given code (e.g., 'JP', 'EN')."""
        self.language = language_code
        
        # Map code to filename (case insensitive search)
        locales_path = self.get_locales_path()
        target_file = f"{language_code.lower()}.json"
        target_path = os.path.join(locales_path, target_file)
        
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
            except Exception as e:
                print(f"Error loading locale {target_file}: {e}")
                self.translations = {}
        else:
            print(f"Locale file not found: {target_path}")
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
