import customtkinter as ctk
import os
from core.face_manager import FaceManager
from core.image_processor import ImageProcessor
# Imports for frames will be added as files are created
# from gui.frames.character_list import CharacterListFrame
# from gui.frames.editor_panel import EditorPanelFrame

from core.localization import loc

class App(ctk.CTk):
    def __init__(self, config):
        super().__init__()
        
        self.config = config
        
        # Initialize Localization
        lang = config.get("language", "JP")
        loc.load_language(lang)
        
        self.title(loc.get("app_title"))
        self.geometry(config.get("window_geometry", "1200x800"))
        
        # Initialize Core
        default_path = r"C:\Program Files (x86)\Steam\steamapps\common\Wizardry The Five Ordeals\Data\User\face"
        # Use config path if available and valid, else default
        base_path = config.get("last_open_path")
        
        # Validation Logic
        if not base_path or not os.path.exists(base_path):
            # Try default
            if os.path.exists(default_path):
                base_path = default_path
            else:
                # Ask user to select
                base_path = self.ask_for_directory()
                if not base_path:
                    # User cancelled, exit or show error
                    print("No directory selected. Exiting.")
                    self.destroy()
                    return

        # Update config with valid path
        self.config["last_open_path"] = base_path
        self.save_config()

        self.face_manager = FaceManager(base_path)
        self.image_processor = ImageProcessor()
        
        # Grid Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0) # Footer
        
        self.init_ui()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def init_ui(self):
        # Initialize Frames (Lazy import to avoid circular dependency issues during creation if any)
        from gui.frames.character_list import CharacterListFrame
        from gui.frames.editor_panel import EditorPanelFrame
        
        self.character_list = CharacterListFrame(self, self.face_manager)
        self.character_list.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        self.editor_panel = EditorPanelFrame(self, self.face_manager, self.image_processor)
        self.editor_panel.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        # Bind events
        self.character_list.set_on_select(self.editor_panel.load_character)
        self.editor_panel.set_on_update(self.character_list.refresh_card)
        
        # Footer for Language Switcher
        self.footer_frame = ctk.CTkFrame(self, height=30, fg_color="transparent")
        self.footer_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        
        self.lbl_lang = ctk.CTkLabel(self.footer_frame, text="Language:")
        self.lbl_lang.pack(side="right", padx=5)
        
        current_lang = self.config.get("language", "JP")
        self.combo_lang = ctk.CTkComboBox(self.footer_frame, values=["JP", "EN"], width=70, command=self.change_language)
        self.combo_lang.set(current_lang)
        self.combo_lang.pack(side="right", padx=5)

    def ask_for_directory(self):
        from tkinter import filedialog
        # Show a dialog explaining why
        # Since we can't easily show a message box before the main window, 
        # we'll just open the dialog.
        # Ideally we would show a small splash or message.
        return filedialog.askdirectory(title="Select Wizardry 'face' directory (Data/User/face)")

    def change_language(self, new_lang):
        if new_lang == self.config.get("language"):
            return
            
        # Update config
        self.config["language"] = new_lang
        loc.load_language(new_lang)
        self.title(loc.get("app_title"))
        
        # Save config immediately
        self.save_config()
        
        # Refresh UI
        # Destroy current frames and re-init
        self.character_list.destroy()
        self.editor_panel.destroy()
        self.footer_frame.destroy()
        
        self.init_ui()

    def save_config(self):
        import json
        try:
            with open("app_config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def on_closing(self):
        self.save_config()
        self.destroy()
