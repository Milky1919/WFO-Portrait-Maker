import customtkinter as ctk
from tkinter import filedialog
from PIL import Image, ImageTk
from core.face_manager import FaceManager
from core.image_processor import ImageProcessor
import os

class EditorPanelFrame(ctk.CTkFrame):
    def __init__(self, master, face_manager: FaceManager, image_processor: ImageProcessor, **kwargs):
        super().__init__(master, **kwargs)
        self.face_manager = face_manager
        self.image_processor = image_processor
        self.current_face = None
        self.current_state_key = "normal"
        self.on_update_callback = None
        
        # Layout
        self.grid_columnconfigure(0, weight=1) # Preview
        self.grid_columnconfigure(1, weight=0) # Controls
        self.grid_rowconfigure(0, weight=1)
        
        # Preview Area
        self.preview_frame = ctk.CTkFrame(self)
        self.preview_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.lbl_preview = ctk.CTkLabel(self.preview_frame, text="Select a character")
        self.lbl_preview.pack(expand=True, fill="both")
        
        # Controls Area
        self.controls_frame = ctk.CTkScrollableFrame(self, width=350, label_text="Edit")
        self.controls_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        
        self._init_controls()

    def _init_controls(self):
        # Name
        self.entry_name = ctk.CTkEntry(self.controls_frame, placeholder_text="Display Name")
        self.entry_name.pack(fill="x", padx=10, pady=5)
        self.btn_update_name = ctk.CTkButton(self.controls_frame, text="Update Name", command=self.update_name)
        self.btn_update_name.pack(fill="x", padx=10, pady=5)
        
        # State Selector
        self.lbl_state = ctk.CTkLabel(self.controls_frame, text="State:")
        self.lbl_state.pack(anchor="w", padx=10)
        self.combo_state = ctk.CTkComboBox(self.controls_frame, values=[
            "normal", "poison", "hp_75", "hp_50", "hp_25", "dead", 
            "afraid", "sleep", "paralyzed", "stoned", "ashed"
        ], command=self.change_state)
        self.combo_state.set("normal")
        self.combo_state.pack(fill="x", padx=10, pady=5)
        
        # Image Source
        self.btn_import = ctk.CTkButton(self.controls_frame, text="Import Image", command=self.import_image)
        self.btn_import.pack(fill="x", padx=10, pady=10)
        
        # Sliders
        self.slider_scale = self._create_slider("Scale", 0.1, 2.0, 1.0)
        self.slider_x = self._create_slider("Offset X", -500, 500, 0)
        self.slider_y = self._create_slider("Offset Y", -500, 500, 0)
        
        # Switches
        self.switch_rembg = ctk.CTkSwitch(self.controls_frame, text="Remove Background", command=self.update_preview)
        self.switch_rembg.pack(padx=10, pady=10)
        
        # Save
        self.btn_save = ctk.CTkButton(self.controls_frame, text="Save (Export)", fg_color="green", command=self.save_character)
        self.btn_save.pack(fill="x", padx=10, pady=20)

    def _create_slider(self, label, from_, to, default):
        frame = ctk.CTkFrame(self.controls_frame)
        frame.pack(fill="x", padx=10, pady=5)
        lbl = ctk.CTkLabel(frame, text=label)
        lbl.pack(side="left")
        slider = ctk.CTkSlider(frame, from_=from_, to=to, command=lambda v: self.update_preview())
        slider.set(default)
        slider.pack(side="right", fill="x", expand=True, padx=5)
        return slider

    def set_on_update(self, callback):
        self.on_update_callback = callback

    def load_character(self, face_data):
        self.current_face = face_data
        self.entry_name.delete(0, "end")
        self.entry_name.insert(0, face_data.get('display_name', ''))
        self.change_state("normal") # Reset to normal on load
        self.combo_state.set("normal")

    def change_state(self, state_key):
        self.current_state_key = state_key
        if not self.current_face:
            return
            
        states = self.current_face.get('states', {})
        state_data = states.get(state_key, {})
        
        # Load values to sliders
        self.slider_scale.set(state_data.get('scale', 1.0))
        self.slider_x.set(state_data.get('offset_x', 0))
        self.slider_y.set(state_data.get('offset_y', 0))
        self.switch_rembg.select() if state_data.get('use_rembg') else self.switch_rembg.deselect()
        
        self.update_preview()

    def update_name(self):
        if self.current_face:
            self.current_face['display_name'] = self.entry_name.get()
            self._save_json()
            if self.on_update_callback:
                self.on_update_callback(self.current_face)

    def import_image(self):
        if not self.current_face:
            return
        
        file_path = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp")])
        if file_path:
            uuid = self.face_manager.import_source_image(self.current_face, file_path)
            if uuid:
                # Update current state source
                if 'states' not in self.current_face:
                    self.current_face['states'] = {}
                if self.current_state_key not in self.current_face['states']:
                    self.current_face['states'][self.current_state_key] = {}
                    
                self.current_face['states'][self.current_state_key]['source_uuid'] = uuid
                self._save_json()
                self.update_preview()

    def update_preview(self):
        if not self.current_face:
            return
            
        states = self.current_face.get('states', {})
        state_data = states.get(self.current_state_key, {})
        
        # Update state data from controls
        state_data['scale'] = self.slider_scale.get()
        state_data['offset_x'] = int(self.slider_x.get())
        state_data['offset_y'] = int(self.slider_y.get())
        state_data['use_rembg'] = bool(self.switch_rembg.get())
        
        # Ensure state exists in face data
        if self.current_state_key not in states:
            states[self.current_state_key] = state_data
        
        source_uuid = state_data.get('source_uuid')
        if not source_uuid:
            self.lbl_preview.configure(image=None, text="No Image Source")
            return

        source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
        if not source_path:
            self.lbl_preview.configure(image=None, text="Image Not Found")
            return

        # Process Image
        # Note: In a real app, run this in a thread to avoid UI freeze
        processed_img = self.image_processor.process_image(
            source_path, 
            state_data, 
            target_size=(1920, 1080)
        )
        
        if processed_img:
            # Resize for preview (keep aspect ratio)
            preview_height = self.preview_frame.winfo_height()
            if preview_height < 100: preview_height = 400 # Default if not rendered yet
            
            ratio = processed_img.width / processed_img.height
            new_height = preview_height - 20
            new_width = int(new_height * ratio)
            
            preview_img = processed_img.resize((new_width, new_height), Image.Resampling.BILINEAR)
            
            ctk_img = ctk.CTkImage(light_image=preview_img, dark_image=preview_img, size=(new_width, new_height))
            self.lbl_preview.configure(image=ctk_img, text="")
        else:
            self.lbl_preview.configure(image=None, text="Error Processing")

    def save_character(self):
        if not self.current_face:
            return
            
        # 1. Save JSON
        self._save_json()
        
        # 2. Export Images
        face_dir = self.current_face.get('_path')
        if not face_dir:
            return

        states = self.current_face.get('states', {})
        
        # Helper to render and save
        def export_state(state_key, suffix):
            state_data = states.get(state_key)
            if not state_data: return
            
            source_uuid = state_data.get('source_uuid')
            if not source_uuid: return
            
            source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
            if not source_path: return
            
            # Render 1920x1080 (face_c)
            # Use a thread or just sync for now (Export is usually blocking but fast enough)
            img_full = self.image_processor.process_image(source_path, state_data, (1920, 1080))
            if img_full:
                # Save face_c
                filename = f"face_c{suffix}.png"
                img_full.save(os.path.join(face_dir, filename))
                
                # If normal state, generate face_a, face_b
                if state_key == "normal":
                    # face_a (96x96)
                    img_a = self.image_processor.create_face_icon(img_full, (96, 96))
                    img_a.save(os.path.join(face_dir, "face_a.png"))
                    
                    # face_b (270x96)
                    img_b = self.image_processor.create_face_icon(img_full, (270, 96))
                    img_b.save(os.path.join(face_dir, "face_b.png"))

        # Export Normal
        export_state("normal", "")
        
        # Export others
        suffix_map = {
            "poison": "_PO", "hp_75": "_75", "hp_50": "_50", "hp_25": "_25", "dead": "_DE",
            "afraid": "_AF", "sleep": "_SL", "paralyzed": "_PA", "stoned": "_ST", "ashed": "_AS"
        }
        
        for key, suffix in suffix_map.items():
            export_state(key, suffix)
            
        print(f"Saved character to {face_dir}") 

    def _save_json(self):
        face_dir = self.current_face.get('_path')
        if face_dir:
            self.face_manager.save_project_data(face_dir, self.current_face)
