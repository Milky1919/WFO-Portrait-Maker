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
        base_path = self.validate_environment()
        
        if not base_path:
            # User cancelled or failed validation
            self.destroy()
            return

        self.face_manager = FaceManager(base_path)
        self.image_processor = ImageProcessor()
        
        # Grid Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0) # Footer
        
        self.init_ui()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def validate_environment(self):
        """
        Validates the game installation and returns the path to the 'face' directory.
        Checks for executable -> resolves 'Data/User/face'.
        """
        from tkinter import filedialog, messagebox
        
        from core.steam_finder import SteamFinder
        
        # Helper to check if a path looks like a valid game root
        def is_valid_game_root(path):
            # Check for either V1 or V2 exe
            v1 = os.path.exists(os.path.join(path, "WizardryFO.exe"))
            v2 = os.path.exists(os.path.join(path, "WizardryFoV2.exe"))
            return v1 or v2

        # 1. Check Configured Path (Reverse lookup)
        last_path = self.config.get("last_open_path")
        target_exe_path = None
        
        if last_path and os.path.exists(last_path):
            # Try to deduce game root from face path: .../Data/User/face
            # Go up 3 levels
            potential_root = os.path.dirname(os.path.dirname(os.path.dirname(last_path)))
            if is_valid_game_root(potential_root):
                return last_path
        
        # 2. Auto-Detect via Steam
        # Look for "Wizardry The Five Ordeals" folder and "WizardryFoV2.exe"
        detected_exe = SteamFinder.find_game_executable("Wizardry The Five Ordeals", "WizardryFoV2.exe")
        if detected_exe:
            target_exe_path = detected_exe
        
        # 3. If not found, ask user to select Executable
        if not target_exe_path:
            messagebox.showinfo("Setup", "Wizardry The Five Ordeals installation not found.\nPlease select the game executable (WizardryFoV2.exe).")
            target_exe_path = filedialog.askopenfilename(
                title="Select WizardryFoV2.exe",
                filetypes=[("Executable", "*.exe")]
            )
            
        if not target_exe_path:
            return None # User cancelled

        # 4. Resolve 'face' directory
        game_dir = os.path.dirname(target_exe_path)
        face_dir = os.path.join(game_dir, "Data", "User", "face")
        
        # 5. Validate 'face' directory
        if not os.path.exists(face_dir):
            # Show error as requested
            messagebox.showerror("Error", f"Face directory not found at expected location:\n{face_dir}\n\nPlease ensure the game is installed correctly and you have launched it at least once.")
            return None
            
        # Success
        self.config["last_open_path"] = face_dir
        self.save_config()
        return face_dir

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
        
        # Footer for Language Switcher and Open Folder
        self.footer_frame = ctk.CTkFrame(self, height=30, fg_color="transparent")
        self.footer_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        
        # Open Folder Button (Left)
        self.btn_open_folder = ctk.CTkButton(self.footer_frame, text=loc.get("open_folder"), width=120, command=self.open_face_folder)
        self.btn_open_folder.pack(side="left", padx=5)
        
        # Language Switcher (Right)
        self.lbl_lang = ctk.CTkLabel(self.footer_frame, text="Language:")
        self.lbl_lang.pack(side="right", padx=5)
        
        current_lang = self.config.get("language", "JP")
        self.combo_lang = ctk.CTkComboBox(self.footer_frame, values=["JP", "EN"], width=70, command=self.change_language)
        self.combo_lang.set(current_lang)
        self.combo_lang.pack(side="right", padx=5)

    def open_face_folder(self):
        path = self.config.get("last_open_path")
        if path and os.path.exists(path):
            os.startfile(path)
        else:
            print("Face folder path invalid.")

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
