import customtkinter as ctk
import os
import subprocess
from core.localization import loc
from gui.fonts import get_ui_font_family

class FaceDirErrorDialog(ctk.CTkToplevel):
    def __init__(self, master, game_exe_path, face_dir_path, on_retry=None, on_create=None, on_exit=None, on_lang_change=None):
        super().__init__(master)
        self.title("Setup Required")
        self.geometry("500x350")
        self.resizable(False, False)
        
        self.game_exe_path = game_exe_path
        self.face_dir_path = face_dir_path
        self.on_retry = on_retry
        self.on_create = on_create
        self.on_exit = on_exit
        self.on_lang_change = on_lang_change
        
        # Center on screen
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")
        
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_exit)
        
        self._init_ui()
        
    def _init_ui(self):
        # Language Switcher (Top Right)
        self.lang_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.lang_frame.pack(fill="x", padx=10, pady=5)
        
        available_langs = loc.get_available_languages()
        self.combo_lang = ctk.CTkComboBox(self.lang_frame, values=available_langs, width=70, command=self._change_language)
        # Assuming loc.current_lang exists or we pass it. For now, try to infer or default.
        # We can't easily get current lang from loc if it's private, but loc.get works.
        # Let's assume the caller sets the correct lang before creating this.
        self.combo_lang.set("JP" if loc.get("app_title") == "WFO Portrait Maker" and loc.get("edit") == "編集" else "EN")
        if loc.get("edit") == "Edit": self.combo_lang.set("EN") # Simple heuristic
        
        self.combo_lang.pack(side="right")
        ctk.CTkLabel(self.lang_frame, text=loc.get("language", "Language:")).pack(side="right", padx=5)

        # Message
        self.lbl_title = ctk.CTkLabel(self, text=loc.get("setup.title", "Setup Required"), font=(get_ui_font_family(), 20, "bold"))
        self.lbl_title.pack(pady=(10, 10))
        
        msg = loc.get("setup.message", "Face directory not found.\n\nPath: {}\n\nPlease choose an action:").format(self.face_dir_path)
        self.lbl_msg = ctk.CTkLabel(self, text=msg, justify="left", wraplength=450)
        self.lbl_msg.pack(pady=10, padx=20)
        
        # Buttons
        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # 1. Launch Game
        self.btn_launch = ctk.CTkButton(self.btn_frame, text=loc.get("setup.launch_game", "1. Launch Game"), command=self._on_launch)
        self.btn_launch.pack(fill="x", pady=5)
        
        # 2. Create Folder
        self.btn_create = ctk.CTkButton(self.btn_frame, text=loc.get("setup.create_folder", "2. Create Folder Automatically"), command=self._on_create)
        self.btn_create.pack(fill="x", pady=5)
        
        # 3. Exit
        self.btn_exit = ctk.CTkButton(self.btn_frame, text=loc.get("setup.exit", "3. Exit"), fg_color="gray", command=self._on_exit)
        self.btn_exit.pack(fill="x", pady=5)

    def _change_language(self, lang):
        if self.on_lang_change:
            self.on_lang_change(lang)
            # Refresh UI text
            self.lbl_title.configure(text=loc.get("setup.title", "Setup Required"))
            msg = loc.get("setup.message", "Face directory not found.\n\nPath: {}\n\nPlease choose an action:").format(self.face_dir_path)
            self.lbl_msg.configure(text=msg)
            self.btn_launch.configure(text=loc.get("setup.launch_game", "1. Launch Game"))
            self.btn_create.configure(text=loc.get("setup.create_folder", "2. Create Folder Automatically"))
            self.btn_exit.configure(text=loc.get("setup.exit", "3. Exit"))

    def _on_launch(self):
        try:
            # Launch via Steam Protocol
            os.startfile("steam://run/1308700")
            
            # We could wait or just close this dialog and ask user to retry?
            # Ideally, we wait for user to say "I did it".
            # But for now, let's just trigger retry callback which might check again.
            if self.on_retry: self.on_retry()
        except Exception as e:
            print(f"Error launching game: {e}")

    def _on_create(self):
        if self.on_create:
            self.on_create()

    def _on_exit(self):
        if self.on_exit:
            self.on_exit()
