import customtkinter as ctk
import os
from core.face_manager import FaceManager
from core.image_processor import ImageProcessor
from core.localization import loc

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False
    # Dummy class for inheritance if missing
    class TkinterDnD:
        class DnDWrapper: pass

class App(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, config):
        super().__init__()
        if HAS_DND:
            self.TkdndVersion = TkinterDnD._require(self)
        
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
            messagebox.showinfo(loc.get("setup.title"), loc.get("setup.game_not_found"))
            target_exe_path = filedialog.askopenfilename(
                title=loc.get("setup.select_exe_title"),
                filetypes=[("Executable", "*.exe")]
            )
            
        if not target_exe_path:
            return None # User cancelled

        # 4. Resolve 'face' directory
        game_dir = os.path.dirname(target_exe_path)
        face_dir = os.path.join(game_dir, "Data", "User", "face")
        
        # 5. Validate 'face' directory
        if not os.path.exists(face_dir):
            # Show custom setup dialog
            from gui.dialogs.setup_dialog import FaceDirErrorDialog
            
            # We need a way to wait for the dialog result.
            # Since we are in __init__, we can't easily use wait_window if mainloop hasn't started?
            # Actually, we are in __init__ of App, but mainloop is called after.
            # We can create a temporary root or use the App window (which is created but not shown fully?).
            # App inherits CTk, so it is a root.
            
            self.setup_action = None
            
            def on_retry():
                self.setup_action = "retry"
                dlg.destroy()
                
            def on_create():
                self.setup_action = "create"
                dlg.destroy()
                
            def on_exit():
                self.setup_action = "exit"
                dlg.destroy()
                
            def on_lang_change(lang):
                self.change_language(lang)

            while True:
                dlg = FaceDirErrorDialog(self, target_exe_path, face_dir, on_retry, on_create, on_exit, on_lang_change)
                self.wait_window(dlg)
                
                if self.setup_action == "retry":
                    # Check again
                    if os.path.exists(face_dir):
                        break
                    else:
                        continue # Show dialog again
                elif self.setup_action == "create":
                    try:
                        os.makedirs(face_dir)
                        from core.logger import Logger
                        Logger.info(f"Created face directory: {face_dir}")
                        break
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to create directory: {e}")
                        return None
                else:
                    # Exit or closed
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
        
        from core.logger import Logger
        
        # Footer for Language Switcher and Open Folder
        self.footer_frame = ctk.CTkFrame(self, height=30, fg_color="transparent")
        self.footer_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 5))
        
        # Open Folder Button (Left)
        self.btn_open_folder = ctk.CTkButton(self.footer_frame, text=loc.get("open_folder"), width=120, command=self.open_face_folder)
        self.btn_open_folder.pack(side="left", padx=5)

        # Undo/Redo Buttons (Left, next to Open Folder)
        self.btn_undo = ctk.CTkButton(self.footer_frame, text=loc.get("undo", "Undo"), width=60, command=self.undo_action, state="disabled")
        self.btn_undo.pack(side="left", padx=5)
        
        self.btn_redo = ctk.CTkButton(self.footer_frame, text=loc.get("redo", "Redo"), width=60, command=self.redo_action, state="disabled")
        self.btn_redo.pack(side="left", padx=5)
        
        # Language Switcher (Right)
        self.lbl_lang = ctk.CTkLabel(self.footer_frame, text=loc.get("language", "Language:"))
        self.lbl_lang.pack(side="right", padx=5)
        
        current_lang = self.config.get("language", "JP")
        available_langs = loc.get_available_languages()
        self.combo_lang = ctk.CTkComboBox(self.footer_frame, values=available_langs, width=70, command=self.change_language)
        self.combo_lang.set(current_lang)
        self.combo_lang.pack(side="right", padx=5)

        # Log Area (Bottom)
        self.log_textbox = ctk.CTkTextbox(self, height=100, state="disabled")
        self.log_textbox.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        
        # Subscribe to Logger
        Logger.add_listener(self.append_log)
        Logger.info("Application started.")
        
        # Bind Undo
        # Bind Undo/Redo
        self.bind("<Control-z>", self.undo_action)
        self.bind("<Control-y>", self.redo_action)
        self.bind("<Control-Shift-z>", self.redo_action) # Alternative Redo

    def undo_action(self, event=None):
        restored_data = self.face_manager.undo()
        self._handle_history_update(restored_data)

    def redo_action(self, event=None):
        restored_data = self.face_manager.redo()
        self._handle_history_update(restored_data)

    def _handle_history_update(self, restored_data):
        # Update button states
        self.update_history_buttons()
        
        if restored_data:
            if isinstance(restored_data, bool):
                # Boolean True means list refresh needed (e.g. delete/restore)
                self.character_list.refresh()
            elif isinstance(restored_data, dict):
                # Dictionary means face data restored
                self.character_list.refresh() # Refresh list to show changes
                # If the restored data matches the currently edited face, reload it
                if self.editor_panel.current_face and self.editor_panel.current_face.get('_path') == restored_data.get('_path'):
                    self.editor_panel.load_character(restored_data)

    def update_history_buttons(self):
        if hasattr(self, 'btn_undo'):
            self.btn_undo.configure(state="normal" if self.face_manager.can_undo else "disabled")
        if hasattr(self, 'btn_redo'):
            self.btn_redo.configure(state="normal" if self.face_manager.can_redo else "disabled")

    def append_log(self, message):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def open_face_folder(self):
        from core.logger import Logger
        path = self.config.get("last_open_path")
        if path and os.path.exists(path):
            os.startfile(path)
            Logger.info(f"Opened face folder: {path}")
        else:
            Logger.warning("Face folder path invalid.")

    def ask_for_directory(self):
        from tkinter import filedialog
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
        if hasattr(self, 'character_list') and self.character_list:
            self.character_list.destroy()
        if hasattr(self, 'editor_panel') and self.editor_panel:
            self.editor_panel.destroy()
        if hasattr(self, 'footer_frame') and self.footer_frame:
            self.footer_frame.destroy()
            
        # Only re-init if we have a valid face manager (meaning environment is valid)
        if hasattr(self, 'face_manager') and self.face_manager:
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

    def show_dimmer(self):
        if hasattr(self, 'dimmer') and self.dimmer:
            return
            
        from core.logger import Logger
        Logger.info("App.show_dimmer called (Transient)")
        
        import tkinter
        self.dimmer = tkinter.Toplevel(self)
        self.dimmer.withdraw() # Hide initially
        
        # Overrideredirect (Frameless)
        self.dimmer.overrideredirect(True)
        self.dimmer.configure(bg="black")
        
        # Add a Frame to ensure content exists
        self.dimmer_frame = tkinter.Frame(self.dimmer, bg="black")
        self.dimmer_frame.pack(fill="both", expand=True)
        
        # Initial Position
        self._update_dimmer_position()
        
        self.dimmer.deiconify() # Show
        
        # Wait for visibility BEFORE setting transient to avoid "invisible window" bug on Windows
        try:
            self.dimmer.wait_visibility(self.dimmer)
            
            # Now apply transient and alpha
            self.dimmer.transient(self)
            self.dimmer.lift()
            self.dimmer.attributes("-alpha", 0.5)
            
            Logger.info("Dimmer visibility confirmed. Transient set, Alpha=0.5")
        except tkinter.TclError as e:
            Logger.error(f"Error waiting for dimmer visibility: {e}")
        
        # Bind Configure to track main window
        self.bind("<Configure>", self._update_dimmer_position, add="+")
        
    def hide_dimmer(self):
        if hasattr(self, 'dimmer') and self.dimmer:
            from core.logger import Logger
            Logger.info("App.hide_dimmer called")
            self.dimmer.destroy()
            self.dimmer = None
            self.unbind("<Configure>") 
            
    def _update_dimmer_position(self, event=None):
        if hasattr(self, 'dimmer') and self.dimmer:
            # Match client area size/pos
            x = self.winfo_rootx()
            y = self.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            
            if w <= 1 or h <= 1: return
            
            geom = f"{w}x{h}+{x}+{y}"
            # from core.logger import Logger
            # Logger.info(f"Updating dimmer geometry: {geom}")
            
            self.dimmer.geometry(geom)
            # Do NOT lift here, otherwise it covers other topmost windows (like the dialog)
