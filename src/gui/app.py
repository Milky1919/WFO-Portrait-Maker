import customtkinter as ctk
import os
from core.face_manager import FaceManager
from core.image_processor import ImageProcessor
# Imports for frames will be added as files are created
# from gui.frames.character_list import CharacterListFrame
# from gui.frames.editor_panel import EditorPanelFrame

class App(ctk.CTk):
    def __init__(self, config):
        super().__init__()
        
        self.config = config
        self.title("WFO Portrait Maker")
        self.geometry(config.get("window_geometry", "1200x800"))
        
        # Initialize Core
        default_path = r"C:\Program Files (x86)\Steam\steamapps\common\Wizardry The Five Ordeals\Data\User\face"
        # Use config path if available and valid, else default
        base_path = config.get("last_open_path")
        if not base_path or not os.path.exists(base_path):
            base_path = default_path
            
        self.face_manager = FaceManager(base_path)
        self.image_processor = ImageProcessor()
        
        # Grid Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
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

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        # Save config (geometry, path)
        # For now just destroy
        self.destroy()
