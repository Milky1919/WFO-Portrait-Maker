import os
import sys
import customtkinter as ctk
import json

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

def load_config():
    config_path = "app_config.json"
    default_config = {
        "language": "JP",
        "window_geometry": "1200x800",
        "last_open_path": ""
    }
    
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4)
        return default_config
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return default_config

def main():
    config = load_config()
    
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    
    from gui.app import App
    
    app = App(config)
    app.mainloop()

if __name__ == "__main__":
    main()
