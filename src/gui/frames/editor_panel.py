import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk, ImageDraw
from core.face_manager import FaceManager
from core.image_processor import ImageProcessor
import os
import json
from gui.dialogs.progress_dialog import ProgressDialog

from core.localization import loc
from core.rembg_downloader import RembgDownloader
import threading
from core.logger import Logger
import traceback
from gui.fonts import get_ui_font_family

class LoadingOverlay(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=("gray85", "gray25"), **kwargs)
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        self.center_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.center_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        self.spinner = ctk.CTkProgressBar(self.center_frame, orientation="horizontal", mode="indeterminate", width=200)
        self.spinner.pack(pady=10)
        self.spinner.start()
        
        self.label = ctk.CTkLabel(self.center_frame, text=loc.get("loading", "Loading..."), font=(get_ui_font_family(), 16))
        self.label.pack(pady=5)
        
        self.lift() # Ensure on top
        
    def show(self):
        Logger.info("LoadingOverlay.show called")
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.spinner.start()
        self.lift()
        # Explicitly lift above siblings if possible
        try:
            if hasattr(self.master, 'right_panel'):
                self.lift(self.master.right_panel)
            if hasattr(self.master, 'preview_container'):
                self.lift(self.master.preview_container)
        except:
            pass
        self.update_idletasks() # Force render
        
    def hide(self):
        Logger.info("LoadingOverlay.hide called")
        self.place_forget()
        self.spinner.stop()

class EditorPanelFrame(ctk.CTkFrame):
    def __init__(self, master, face_manager: FaceManager, image_processor: ImageProcessor, **kwargs):
        super().__init__(master, **kwargs)
        self.face_manager = face_manager
        self.image_processor = image_processor
        self.current_face = None
        self.current_state_key = "normal"
        self.on_update_callback = None
        self.on_update_callback = None
        self.view_mode = "Grid" # Default Grid
        self.grid_images = [] # Keep references to grid images
        self.grid_widgets = [] # Keep references to grid widgets for clearing
        self.last_window_width = 0 # For resize debounce
        self.ignore_slider_event = False # Flag to prevent loop
        
        # Caching for Performance
        self.cached_processed_image = None
        self.cache_key = None # (source_uuid, use_rembg, alpha, fg, bg, erode)
        
        self.cached_clean_image = None
        self.clean_cache_key = None # (cache_key, scale, offset_x, offset_y, face_center)
        
        self.cached_composited_image = None # Deprecated/Removed in favor of clean cache + dynamic UI
        self.composited_cache_key = None
        
        self.pin_mode = "Global" # Global or Local
        
        self.view_zoom = 1.0 # View Zoom
        
        # Drag State
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_dragging = False
        self.drag_threshold = 5
        
        # Layout
        self.grid_columnconfigure(0, weight=1) # Preview
        self.grid_columnconfigure(1, weight=0) # Controls
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0) # Delete button area
        
        # Placeholder (Empty State)
        self.lbl_empty = ctk.CTkLabel(self, text=loc.get("select_character"), font=(get_ui_font_family(), 16))
        self.lbl_empty.grid(row=0, column=0, columnspan=2, sticky="nsew")
        
        # Preview Area
        self.preview_container = ctk.CTkFrame(self)
        self.preview_container.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # View Mode Switcher
        self.view_mode_frame = ctk.CTkFrame(self.preview_container, height=30)
        self.view_mode_frame.pack(fill="x", padx=5, pady=5)
        self.btn_view_single = ctk.CTkButton(self.view_mode_frame, text=loc.get("single_view"), width=100, command=lambda: self.set_view_mode("Single"))
        self.btn_view_single.pack(side="left", padx=5)
        self.btn_view_grid = ctk.CTkButton(self.view_mode_frame, text=loc.get("grid_view"), width=100, command=lambda: self.set_view_mode("Grid"))
        self.btn_view_grid.pack(side="left", padx=5)
        
        # Zoom Slider (Shared for Grid and Single View)
        self.slider_zoom = ctk.CTkSlider(self.view_mode_frame, from_=0.1, to=5.0, width=150, command=self._on_zoom_slider_change)
        self.slider_zoom.set(1.0) 
        self.slider_zoom.pack(side="right", padx=10)
        self.lbl_zoom = ctk.CTkLabel(self.view_mode_frame, text=loc.get("zoom", "Zoom"))
        self.lbl_zoom.pack(side="right", padx=5)
        
        # Single View Frame
        self.preview_frame = ctk.CTkFrame(self.preview_container)
        self.preview_frame.pack(expand=True, fill="both")
        
        # Use standard tk.Label for robustness against CTkImage TclErrors
        self.lbl_preview = tk.Label(self.preview_frame, text="", bg="gray20") # Match dark theme roughly
        self.lbl_preview.place(relx=0.5, rely=0.5, anchor="center")
        
        # Individual Adjust Indicator (Overlay)
        self.lbl_individual_indicator = ctk.CTkLabel(self.preview_frame, text=loc.get("individual_adjust"), 
                                                     fg_color="red", text_color="white", corner_radius=5, padx=5, pady=2)
        # Initially hidden, placed at top-left
        
        # Bindings
        self.lbl_preview.bind("<ButtonPress-1>", self.on_mouse_down)
        self.lbl_preview.bind("<B1-Motion>", self.on_mouse_drag)
        self.lbl_preview.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.lbl_preview.bind("<MouseWheel>", self.on_mouse_wheel) # Windows
        self.lbl_preview.bind("<Button-4>", self.on_mouse_wheel) # Linux scroll up
        self.lbl_preview.bind("<Button-4>", self.on_mouse_wheel) # Linux scroll up
        self.lbl_preview.bind("<Button-5>", self.on_mouse_wheel) # Linux scroll down
        
        # Middle Click Pan
        self.lbl_preview.bind("<ButtonPress-2>", self.on_pan_start)
        self.lbl_preview.bind("<B2-Motion>", self.on_pan_drag)
        self.lbl_preview.bind("<ButtonRelease-2>", self.on_pan_end)
        
        # Grid View Frame (Initially hidden)
        self.grid_view_frame = ctk.CTkScrollableFrame(self.preview_container, label_text="State Overview")
        self.grid_view_frame.bind("<Configure>", self._on_grid_configure)
        # self.grid_view_frame.pack(expand=True, fill="both") # Packed when switched
        
        self.grid_resize_timer = None
        
        # Right Panel (Container for Save, Controls, Delete)
        self.right_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.right_panel.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=5, pady=5)
        
        # Save Button (Floating at Top)
        self.btn_save = ctk.CTkButton(self.right_panel, text=loc.get("save_export"), fg_color="green", command=self.save_character)
        self.btn_save.pack(fill="x", padx=5, pady=(0, 5))
        
        # Controls Area (Scrollable)
        self.controls_frame = ctk.CTkScrollableFrame(self.right_panel, width=350, label_text=loc.get("edit"))
        self.controls_frame.pack(fill="both", expand=True, padx=0, pady=5)
        
        # Delete Button (Floating at Bottom)
        self.btn_delete = ctk.CTkButton(self.right_panel, text=loc.get("delete"), fg_color="red", hover_color="darkred", command=self.delete_character)
        self.btn_delete.pack(fill="x", padx=5, pady=(5, 0))
        
        self._init_controls()
        
        # Register D&D
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)
        except Exception as e:
            print(f"D&D setup failed: {e}")
        
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()
        self.is_loading = False
        
        self.preview_timer = None # For debounce

        # Initially hide editor
        self.show_editor(False)

    def set_on_update(self, callback):
        self.on_update_callback = callback

    def clear_editor(self):
        """Resets the editor state and clears image references to prevent TclError."""
        self.current_face = None
        self.current_image = None
        self.current_pil_image = None
        
        self.cached_processed_image = None
        self.cache_key = None
        
        self.cached_clean_image = None
        self.clean_cache_key = None
        
        self.view_pan_x = 0
        self.view_pan_y = 0
        self._update_preview_position()
        
        self.grid_images.clear()
        
        # Clear Preview Label
        try:
            self.lbl_preview.configure(image=None, text="")
            self.lbl_icon_a.configure(image=None)
            self.lbl_icon_b.configure(image=None)
        except:
            pass
            
        # Clear Grid
        for w in self.grid_widgets:
            w.destroy()
        self.grid_widgets.clear()
            
        self.show_editor(False)
        self.entry_name.delete(0, "end")

    def show_editor(self, show: bool):
        if show:
            self.lbl_empty.grid_remove()
            self.preview_container.grid() # Show container
            self.right_panel.grid() # Show right panel
            # Ensure correct view mode is shown
            self.set_view_mode(self.view_mode)
        else:
            self.preview_container.grid_remove()
            self.right_panel.grid_remove()
            self.lbl_empty.grid()

    def _init_controls(self):
        # Name
        self.entry_name = ctk.CTkEntry(self.controls_frame, placeholder_text=loc.get("display_name"))
        self.entry_name.pack(fill="x", padx=10, pady=5)
        self.btn_update_name = ctk.CTkButton(self.controls_frame, text=loc.get("update_name"), command=self.update_name)
        self.btn_update_name.pack(fill="x", padx=10, pady=5)
        
        # State Selector (Grid Buttons)
        self.lbl_state = ctk.CTkLabel(self.controls_frame, text=loc.get("state"))
        self.lbl_state.pack(anchor="w", padx=10)
        
        self.state_buttons_frame = ctk.CTkFrame(self.controls_frame, fg_color="transparent")
        self.state_buttons_frame.pack(fill="x", padx=5, pady=5)
        
        # Define states order
        self.state_keys = [
            "normal", "poison", "hp_75",
            "hp_50", "hp_25", "dead",
            "afraid", "sleep", "paralyzed",
            "stoned", "ashed"
        ]
        
        self.state_buttons = {}
        # Buttons will be created dynamically in _update_state_buttons
        


        # Image Source (Removed as per user request - use Grid View DnD)
        # self.btn_import = ctk.CTkButton(self.controls_frame, text=loc.get("import_image"), command=self.import_image)
        # self.btn_import.pack(fill="x", padx=10, pady=10)
        
        # Sliders
        self.slider_scale, self.entry_scale = self._create_slider(loc.get("scale"), 0.1, 2.0, 1.0)
        self.slider_x, self.entry_x = self._create_slider(loc.get("offset_x"), -1500, 1500, 0)
        self.slider_y, self.entry_y = self._create_slider(loc.get("offset_y"), -1500, 1500, 0)
        
        # Face Center Controls
        self.fc_frame = ctk.CTkFrame(self.controls_frame)
        self.fc_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(self.fc_frame, text=loc.get("face_center")).pack(anchor="w", padx=5)
        
        self.spin_fc_x = ctk.CTkEntry(self.fc_frame, width=60, placeholder_text="X")
        self.spin_fc_x.pack(side="left", padx=5)
        self.spin_fc_x.bind("<Return>", self.update_face_center_from_entry)
        
        self.spin_fc_y = ctk.CTkEntry(self.fc_frame, width=60, placeholder_text="Y")
        self.spin_fc_y.pack(side="left", padx=5)
        self.spin_fc_y.bind("<Return>", self.update_face_center_from_entry)
        
        ctk.CTkButton(self.fc_frame, text=loc.get("set"), width=40, command=self.update_face_center_from_entry).pack(side="left", padx=5)
        
        # Individual Adjust Mode (Replaces Pin Mode & Sync All)
        self.pin_mode_frame = ctk.CTkFrame(self.controls_frame)
        self.pin_mode_frame.pack(fill="x", padx=10, pady=5)
        
        self.chk_individual_mode = ctk.CTkSwitch(self.pin_mode_frame, text=loc.get("individual_adjust"), command=self.toggle_individual_mode)
        self.chk_individual_mode.pack(side="left", padx=10)
        
        # UI Options
        self.ui_options_frame = ctk.CTkFrame(self.controls_frame)
        self.ui_options_frame.pack(fill="x", padx=10, pady=5)
        
        self.switch_game_ui = ctk.CTkSwitch(self.ui_options_frame, text=loc.get("show_game_ui"), command=self.update_preview)
        self.switch_game_ui.pack(side="left", padx=10)
        
        # RemBG Controls
        self.rembg_frame = ctk.CTkFrame(self.controls_frame)
        self.rembg_frame.pack(fill="x", padx=10, pady=10)
        
        self.lbl_rembg = ctk.CTkLabel(self.rembg_frame, text=loc.get("remove_background"))
        self.lbl_rembg.pack(anchor="w", padx=5)
        
        # Container for Switch or Download Button
        self.rembg_action_frame = ctk.CTkFrame(self.rembg_frame, fg_color="transparent")
        self.rembg_action_frame.pack(fill="x", padx=5, pady=2)
        
        self.switch_rembg = ctk.CTkSwitch(self.rembg_action_frame, text=loc.get("enable"), command=self.toggle_rembg)
        self.btn_download_model = ctk.CTkButton(self.rembg_action_frame, text=loc.get("download_model", "Download Model"), command=self.download_model)
        
        # Fine-tuning Controls (Hidden by default)
        self.rembg_settings_frame = ctk.CTkFrame(self.rembg_frame)
        
        # Alpha Matting
        self.switch_alpha = ctk.CTkSwitch(self.rembg_settings_frame, text=loc.get("alpha_matting", "Alpha Matting"), command=self.toggle_alpha)
        self.switch_alpha.pack(padx=5, pady=5, anchor="w")
        
        # Thresholds
        # Thresholds (Presets)
        self.lbl_presets = ctk.CTkLabel(self.rembg_settings_frame, text=loc.get("removal_strength", "Removal Strength"))
        self.lbl_presets.pack(anchor="w", padx=5)
        
        self.preset_var = ctk.StringVar(value="3")
        self.preset_buttons = ctk.CTkSegmentedButton(
            self.rembg_settings_frame,
            values=["1", "2", "3", "4", "5"],
            variable=self.preset_var,
            command=self.on_preset_change
        )
        self.preset_buttons.pack(fill="x", padx=5, pady=5)
        
        self._check_rembg_model()
        
        # Icon Controls (Sliders)
        self.icon_frame = ctk.CTkFrame(self.controls_frame)
        self.icon_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(self.icon_frame, text=loc.get("icon_preview_scale", "Icon Preview Scale")).pack(anchor="w", padx=5)
        
        self.slider_icon_scale_a, self.entry_icon_scale_a = self._create_slider(loc.get("icon_scale_a"), 0.5, 2.0, 1.0)
        self.slider_icon_scale_b, self.entry_icon_scale_b = self._create_slider(loc.get("icon_scale_b"), 0.5, 2.0, 1.0)
        
        # Icon Overlay (Bottom-Right of Preview)
        self.icon_overlay_frame = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        self.icon_overlay_frame.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)
        
        # Icon B (Wide) - Rightmost? Or Left of A? Usually B is wider.
        # Let's put them side-by-side.
        # Frame for Border
        self.frame_icon_b = ctk.CTkFrame(self.icon_overlay_frame, border_width=2, border_color="gray")
        self.frame_icon_b.pack(side="right", padx=5)
        self.lbl_icon_b = tk.Label(self.frame_icon_b, bg="gray20")
        self.lbl_icon_b.pack(padx=2, pady=2)
        
        # Icon A (Square)
        self.frame_icon_a = ctk.CTkFrame(self.icon_overlay_frame, border_width=2, border_color="gray")
        self.frame_icon_a.pack(side="right", padx=5)
        self.lbl_icon_a = tk.Label(self.frame_icon_a, bg="gray20")
        self.lbl_icon_a.pack(padx=2, pady=2)
        


    def _create_slider(self, label, from_, to, default):
        frame = ctk.CTkFrame(self.controls_frame)
        frame.pack(fill="x", padx=10, pady=5)
        
        # Label
        lbl = ctk.CTkLabel(frame, text=label, width=80, anchor="w")
        lbl.pack(side="left")
        
        # Entry for Value
        entry = ctk.CTkEntry(frame, width=50)
        entry.pack(side="right", padx=5)
        
        # Slider
        slider = ctk.CTkSlider(frame, from_=from_, to=to)
        slider.set(default)
        slider.pack(side="right", fill="x", expand=True, padx=5)
        
        # Bind click to push undo state
        slider.bind("<ButtonPress-1>", lambda e: self.face_manager.push_update_state(self.current_face) if self.current_face else None)
        
        # Callbacks
        # Callbacks
        def on_slider(v):
            # Update Entry
            val = float(v)
            if isinstance(default, int):
                entry.delete(0, "end")
                entry.insert(0, str(int(val)))
            else:
                entry.delete(0, "end")
                entry.insert(0, f"{val:.2f}")
            
            # Fast Update (Immediate, Low Quality)
            if not getattr(self, 'ignore_slider_event', False):
                self.update_preview(fast_mode=True)
            
        def on_release(event):
            # Full Update (Async, High Quality)
            self._perform_full_render()
            
        def on_entry(event):
            try:
                val = float(entry.get())
                # Clamp?
                if val < from_: val = from_
                if val > to: val = to
                slider.set(val)
                self._perform_full_render()
            except ValueError:
                pass

        slider.configure(command=on_slider)
        slider.bind("<ButtonRelease-1>", on_release)
        
        slider.configure(command=on_slider)
        entry.bind("<Return>", on_entry)
        entry.bind("<FocusOut>", on_entry)
        
        # Init Entry
        if isinstance(default, int):
            entry.insert(0, str(default))
        else:
            entry.insert(0, f"{default:.2f}")
            
        # Store entry reference on slider for easy access if needed?
        # Or just return slider and let the caller handle it?
        # The caller (init) assigns self.slider_scale = ...
        # If we want to update the entry programmatically later (e.g. in change_state),
        # we need access to the entry.
        # Let's attach it to the slider object.
        slider.entry_widget = entry
        
        return slider, entry



    def _update_state_buttons(self):
        # Clear existing
        for btn in self.state_buttons.values():
            btn.destroy()
        self.state_buttons.clear()
        
        if not self.current_face: return
        
        states = self.current_face.get('states', {})
        
        # Determine which states have data (for visual feedback)
        # User request: Hide empty states instead of graying them out.
        # Always show "normal".
        
        visible_keys = []
        for key in self.state_keys:
            if key == "normal":
                visible_keys.append(key)
            else:
                # Check if state has data
                state_data = states.get(key)
                if state_data and (state_data.get('source_uuid') or state_data.get('image_path')):
                    visible_keys.append(key)
        
        # Create buttons for visible keys
        for i, key in enumerate(visible_keys):
            row = i // 3
            col = i % 3
            
            btn = ctk.CTkButton(
                self.state_buttons_frame, 
                text=loc.get(f"states.{key}"), 
                font=(get_ui_font_family(), 11),
                width=80,
                height=28,
                fg_color="gray40", # Default inactive
                command=lambda k=key: self.change_state(k)
            )
            
            # Highlight
            if key == self.current_state_key:
                btn.configure(fg_color="#1F6AA5")
            else:
                # It's visible, so it has data (or is normal)
                # If it's normal and empty, it might be gray30, but we want to show it.
                # If it has data, gray50.
                if key in states and (states[key].get('source_uuid') or states[key].get('image_path')):
                    btn.configure(fg_color="gray50")
                else:
                    btn.configure(fg_color="gray30")
                
            btn.grid(row=row, column=col, padx=2, pady=2, sticky="ew")
            self.state_buttons_frame.grid_columnconfigure(col, weight=1)
            self.state_buttons[key] = btn

    def change_state(self, state_key, save_before_switch=True):
        # Save previous state before switching
        if self.current_face and save_before_switch:
            self._save_json()
            
        self.current_state_key = state_key
        if not self.current_face:
            return
            
        states = self.current_face.get('states', {})
        state_data = states.get(state_key, {})
        
        # Suppress slider events to prevent multiple preview updates
        self.ignore_slider_event = True
        try:
            # 1. Update Individual Adjust Mode Switch
            # 1. Update Individual Adjust Mode Switch
            is_individual = state_data.get('is_individual', False)
            if is_individual:
                self.chk_individual_mode.select()
                self.lbl_individual_indicator.place(x=10, y=10)
                self.lbl_individual_indicator.lift()
            else:
                self.chk_individual_mode.deselect()
                self.lbl_individual_indicator.place_forget()
                
            # 2. Load Settings (Sliders)
            self.slider_scale.set(state_data.get('scale', 1.0))
            self.slider_x.set(state_data.get('offset_x', 0))
            self.slider_y.set(state_data.get('offset_y', 0))
            
            # Icon Scales
            self.slider_icon_scale_a.set(state_data.get('icon_scale_a', state_data.get('icon_scale', 1.0)))
            self.slider_icon_scale_b.set(state_data.get('icon_scale_b', state_data.get('icon_scale', 1.0)))
            
            # RemBG Settings
            if state_data.get('use_rembg', False):
                self.switch_rembg.select()
                self.rembg_settings_frame.pack(fill="x", padx=5, pady=5)
            else:
                self.switch_rembg.deselect()
                self.rembg_settings_frame.pack_forget()
                
            self.switch_alpha.deselect()
            if state_data.get('alpha_matting', False):
                self.switch_alpha.select()
                
            # Load Presets
            fg = state_data.get('alpha_matting_foreground_threshold', 240)
            bg = state_data.get('alpha_matting_background_threshold', 10)
            erode = state_data.get('alpha_matting_erode_size', 10)
            
            # Determine closest preset
            # Level 1: 240, 10, 0
            # Level 2: 240, 10, 5
            # Level 3: 240, 10, 10
            # Level 4: 240, 20, 10
            # Level 5: 240, 40, 15
            
            # Simple heuristic: Check erode and bg
            preset = "3"
            if erode <= 2: preset = "1"
            elif erode <= 7: preset = "2"
            elif bg <= 15: preset = "3"
            elif bg <= 30: preset = "4"
            else: preset = "5"
                
            self.preset_var.set(preset)
            
            # Load Face Center
            face_center = state_data.get('face_center')
            if not face_center:
                # Fallback to defaults/global
                face_center = self.current_face.get('defaults', {}).get('face_center')
                if not face_center:
                    face_center = self.current_face.get('face_center')
            
            if face_center:
                self.spin_fc_x.delete(0, "end")
                self.spin_fc_x.insert(0, str(face_center.get('x', 0)))
                self.spin_fc_y.delete(0, "end")
                self.spin_fc_y.insert(0, str(face_center.get('y', 0)))
            else:
                self.spin_fc_x.delete(0, "end")
                self.spin_fc_y.delete(0, "end")
            
        finally:
            self.ignore_slider_event = False
            
        # Update Button Highlights
        self._update_state_buttons()
        
        self.update_preview()

    def update_name(self):
        if self.current_face:
            self.face_manager.push_update_state(self.current_face) # Undo snapshot
            self.current_face['display_name'] = self.entry_name.get()
            self._save_json()
            if self.on_update_callback:
                self.on_update_callback(self.current_face)

    def import_image(self):
        if not self.current_face:
            return
        
        file_path = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp")])
        if file_path:
            self._import_file(file_path)

    def on_drop(self, event):
        if not self.current_face:
            return
            
        files = self.tk.splitlist(event.data)
        if not files: return
        
        file_path = files[0] # Take first file
        if os.path.isfile(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.png', '.jpg', '.jpeg', '.webp', '.bmp']:
                from core.logger import Logger
                Logger.info(f"Dropped image on editor: {os.path.basename(file_path)}")
                self._import_file(file_path)

    def on_drop_grid_cell(self, event, state_key):
        files = self.tk.splitlist(event.data)
        if not files: return
        
        file_path = files[0]
        if os.path.isfile(file_path):
            self._import_file_to_state(file_path, state_key)

    def on_drop_batch(self, event):
        files = self.tk.splitlist(event.data)
        if not files: return
        
        # Suffix Map
        suffix_map = {
            "_75": "hp_75", "_50": "hp_50", "_25": "hp_25",
            "_DE": "dead", "_PO": "poison", "_AF": "afraid",
            "_SL": "sleep", "_PA": "paralyzed", "_ST": "stoned",
            "_AS": "ashed"
        }
        
        # Validation
        valid_files = []
        
        for f in files:
            if not os.path.isfile(f): continue
            name = os.path.splitext(os.path.basename(f))[0].upper()
            
            # Check suffix
            matched = False
            for suffix, key in suffix_map.items():
                if name.endswith(suffix):
                    valid_files.append((f, key))
                    matched = True
                    break
            
            if not matched:
                valid_files.append((f, "normal"))

        # Batch Import
        self.face_manager.push_update_state(self.current_face)
        
        count = 0
        for f, key in valid_files:
            self._import_file_to_state(f, key, save=False)
            count += 1
            
        if count > 0:
            self._save_json()
            self._refresh_grid_view() # Refresh thumbnails
            from tkinter import messagebox
            messagebox.showinfo("Batch Import", f"Imported {count} files.")

    def _import_file_to_state(self, file_path, state_key, save=True):
        self.face_manager.push_update_state(self.current_face) # Undo snapshot
        uuid = self.face_manager.import_source_image(self.current_face, file_path)
        if uuid:
            if 'states' not in self.current_face:
                self.current_face['states'] = {}
            if state_key not in self.current_face['states']:
                self.current_face['states'][state_key] = {}
                
            self.current_face['states'][state_key]['source_uuid'] = uuid
            
            # Apply Global Defaults if available
            defaults = self.current_face.get('defaults')
            if defaults:
                self.current_face['states'][state_key]['scale'] = defaults.get('scale', 1.0)
                self.current_face['states'][state_key]['offset_x'] = defaults.get('offset_x', 0)
                self.current_face['states'][state_key]['offset_y'] = defaults.get('offset_y', 0)
                self.current_face['states'][state_key]['face_center'] = defaults.get('face_center')
                self.current_face['states'][state_key]['icon_scale_a'] = defaults.get('icon_scale_a')
                self.current_face['states'][state_key]['icon_scale_b'] = defaults.get('icon_scale_b')
                self.current_face['states'][state_key]['use_rembg'] = defaults.get('use_rembg', False)
                self.current_face['states'][state_key]['alpha_matting'] = defaults.get('alpha_matting', False)
                self.current_face['states'][state_key]['alpha_matting_foreground_threshold'] = defaults.get('alpha_matting_foreground_threshold', 240)
                self.current_face['states'][state_key]['alpha_matting_background_threshold'] = defaults.get('alpha_matting_background_threshold', 10)
                self.current_face['states'][state_key]['alpha_matting_erode_size'] = defaults.get('alpha_matting_erode_size', 10)
                
                # Ensure it's linked to Global
                self.current_face['states'][state_key]['is_individual'] = False
            else:
                # Auto-Fit (Fallback)
                try:
                    with Image.open(file_path) as img:
                        w, h = img.size
                        scale = 1.0
                        if h > 1080: scale = 1080 / h
                        if w * scale > 1920: scale = 1920 / w
                        
                        self.current_face['states'][state_key]['scale'] = round(scale, 2)
                        self.current_face['states'][state_key]['offset_x'] = 0
                        self.current_face['states'][state_key]['offset_y'] = 0
                except:
                    pass

            if save:
                self._save_json()
                self._refresh_grid_view()
                self._update_state_buttons()
                if self.view_mode == "Single" and self.current_state_key == state_key:
                    self.update_preview()

    def _import_file(self, file_path):
        self.face_manager.push_update_state(self.current_face) # Undo snapshot
        uuid = self.face_manager.import_source_image(self.current_face, file_path)
        if uuid:
            # Update current state source
            if 'states' not in self.current_face:
                self.current_face['states'] = {}
            if self.current_state_key not in self.current_face['states']:
                self.current_face['states'][self.current_state_key] = {}
                
            self.current_face['states'][self.current_state_key]['source_uuid'] = uuid
            
            # Auto-Fit Logic OR Global Defaults
            defaults = self.current_face.get('defaults')
            use_defaults = defaults and not self.chk_individual_mode.get() 
            
            # Initialize is_individual (Default False)
            self.current_face['states'][self.current_state_key]['is_individual'] = False
            
            if use_defaults:
                self.current_face['states'][self.current_state_key]['scale'] = defaults.get('scale', 1.0)
                self.current_face['states'][self.current_state_key]['offset_x'] = defaults.get('offset_x', 0)
                self.current_face['states'][self.current_state_key]['offset_y'] = defaults.get('offset_y', 0)
                self.current_face['states'][self.current_state_key]['face_center'] = defaults.get('face_center')
                # Rembg?
                self.current_face['states'][self.current_state_key]['use_rembg'] = defaults.get('use_rembg', False)
                
                # Update sliders
                self.slider_scale.set(defaults.get('scale', 1.0))
                self.slider_x.set(defaults.get('offset_x', 0))
                self.slider_y.set(defaults.get('offset_y', 0))
            else:
                try:
                    with Image.open(file_path) as img:
                        w, h = img.size
                        scale = 1.0
                        if h > 1080: scale = 1080 / h
                        if w * scale > 1920: scale = 1920 / w
                        
                        self.current_face['states'][self.current_state_key]['scale'] = round(scale, 2)
                        self.current_face['states'][self.current_state_key]['offset_x'] = 0
                        self.current_face['states'][self.current_state_key]['offset_y'] = 0
                        
                        # Update sliders
                        self.slider_scale.set(scale)
                        self.slider_x.set(0)
                        self.slider_y.set(0)
                except Exception as e:
                    print(f"Error auto-fitting: {e}")

            self._save_json()
            self._update_state_buttons()
            self.update_preview()

    def update_preview(self, *args, fast_mode=False):
        # Logger.info(f"update_preview called. Fast: {fast_mode}. Stack: {''.join(traceback.format_stack()[-3:])}")
        # Main Thread Synchronous Update (Fast Mode or Sync Full)
        try:
            if not self.current_face: return

            # Sync Sliders to Data
            self._commit_ui_to_data()
            
            # Check Cache for Instant Update (e.g. Undo/Redo)
            if not fast_mode and self.current_face:
                try:
                    states = self.current_face.get('states', {})
                    state_data = states.get(self.current_state_key)
                    if state_data:
                        source_uuid = state_data.get('source_uuid')
                        source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
                        if source_path:
                            # Check if we have a cached render
                            if self.image_processor.get_cached_render(source_path, state_data):
                                fast_mode = True
                except:
                    pass

            # If fast_mode, run synchronously
            if fast_mode:
                result = self._generate_preview_image_internal(fast_mode=True)
                # Update UI directly without touching overlay
                display_img, processed_img, icon_a, icon_b = result
                if display_img:
                    self.lbl_preview.configure(image=None)
                    photo_img = ImageTk.PhotoImage(display_img)
                    self.current_image = photo_img
                    self.current_pil_image = processed_img
                    self.lbl_preview.configure(image=photo_img, text="")
                    self._update_preview_position()

                # Update Icons (Fast Mode)
                if icon_a:
                    photo_icon_a = ImageTk.PhotoImage(icon_a)
                    self.current_icon_a = photo_icon_a
                    self.lbl_icon_a.configure(image=photo_icon_a, text="")
                
                if icon_b:
                    photo_icon_b = ImageTk.PhotoImage(icon_b)
                    self.current_icon_b = photo_icon_b
                    self.lbl_icon_b.configure(image=photo_icon_b, text="")
            else:
                # If called without fast_mode (e.g. load), run async
                self._perform_full_render()
                
        except Exception as e:
            Logger.error(f"Critical error in update_preview: {e}\n{traceback.format_exc()}")

    def _deprecated_update_preview(self, *args, fast_mode=False):
        pass




                


                



            

                

                












                            

    



    def _refresh_grid_view(self):
        try:
            # Clear existing
            for w in self.grid_widgets:
                w.destroy()
            self.grid_widgets.clear()
            self.grid_images.clear()
            
            if not self.current_face: return
            
            states = self.current_face.get('states', {})
            
            # Calculate Grid Layout
            # Width of container?
            container_width = self.grid_view_frame.winfo_width()
            if container_width < 100: container_width = 800 # Default
            
            # Thumb Size from Slider
            try:
                # Read slider value directly to avoid stale state
                slider_val = self.slider_zoom.get()
                # Map 0.5-3.0 -> 80-300px?
                # Base size 100px * slider
                thumb_size = int(100 * slider_val)
                thumb_size = max(50, min(500, thumb_size))
            except Exception as e:
                Logger.error(f"Error reading slider in grid refresh: {e}")
                thumb_size = 100
            
            padding = 10
            # How many cols?
            max_cols = max(1, (container_width - 20) // (thumb_size + padding))
            
            # Filter states to show? All defined states?
            # Show all keys defined in self.state_keys
            
            row = 0
            col = 0
            
            for key in self.state_keys:
                # Frame for Item
                item_frame = ctk.CTkFrame(self.grid_view_frame, fg_color="transparent")
                item_frame.grid(row=row, column=col, padx=5, pady=5)
                self.grid_widgets.append(item_frame)
                
                # Label
                lbl_name = ctk.CTkLabel(item_frame, text=loc.get(f"states.{key}"), font=(get_ui_font_family(), 10))
                lbl_name.pack()
                
                # Image/Button
                # If state has image, show it. Else show placeholder.
                state_data = states.get(key)
                img = None
                
                if state_data:
                    source_uuid = state_data.get('source_uuid')
                    if source_uuid:
                        source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
                        if source_path and os.path.exists(source_path):
                            # Process small thumb
                            # Use image processor to get a small version?
                            # Just load and resize for speed?
                            # Better to use processor to respect crop/rembg if possible, but slow for grid?
                            # Let's just load raw for speed first?
                            # Or use cache?
                            try:
                                # Simple load & resize
                                pil_img = Image.open(source_path)
                                pil_img.thumbnail((thumb_size, thumb_size))
                                img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
                                self.grid_images.append(img) # Keep ref
                            except Exception as e:
                                Logger.error(f"Error loading thumb for {key}: {e}")
                
                btn = ctk.CTkButton(
                    item_frame, 
                    text="+" if not img else "", 
                    image=img,
                    width=thumb_size, 
                    height=thumb_size,
                    fg_color="gray30",
                    command=lambda k=key, has_img=bool(img): self._on_grid_click(k, has_img)
                )
                btn.pack()
                
                # D&D for this cell
                try:
                    btn.drop_target_register('DND_Files')
                    btn.dnd_bind('<<Drop>>', lambda e, k=key: self.on_drop_grid_cell(e, k))
                except:
                    pass
                
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1
            
            # Force update of scroll region
            self.grid_view_frame.update_idletasks()
            
        except Exception as e:
            Logger.error(f"Critical error in _refresh_grid_view: {e}\n{traceback.format_exc()}")

    def _on_grid_click(self, key, has_img):
        if has_img:
            self.change_state(key)
        else:
            # Open file dialog to import
            from tkinter import filedialog
            file_path = filedialog.askopenfilename(
                title=f"Select Image for {loc.get(f'states.{key}')}",
                filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp")]
            )
            if file_path:
                self._import_file_to_state(file_path, key)
                self.change_state(key) # Switch to it after import
                self._refresh_grid_view() # Refresh grid to show new image

    def _check_rembg_model(self):
        if RembgDownloader.is_model_installed():
            self.btn_download_model.pack_forget()
            self.switch_rembg.pack(side="left", padx=5)
        else:
            self.switch_rembg.pack_forget()
            self.btn_download_model.pack(fill="x", padx=5)
            
    def download_model(self):
        from tkinter import messagebox
        if not messagebox.askyesno("Confirm Download", "This will download the u2net.onnx model (approx. 170MB) for background removal.\n\nContinue?"):
            return

        # Show Dimmer
        self.root_window = self.winfo_toplevel()
        if hasattr(self.root_window, 'show_dimmer'):
            self.root_window.show_dimmer()

        # Progress Dialog
        # Master is root_window (App)
        self.dl_progress = ProgressDialog(self.root_window, title="Downloading Model", message="Downloading u2net.onnx...")
        # self.dl_progress.attributes("-topmost", True) # Removed topmost
        self.dl_progress.lift() 
        self.dl_progress.focus_force()
        self.dl_cancel_event = threading.Event()
        
        # Intercept Main Window Close Event
        self.original_close_handler = self.root_window.protocol("WM_DELETE_WINDOW")
        self.root_window.protocol("WM_DELETE_WINDOW", self._on_try_close_during_download)

        # Add Cancel Button to Progress Dialog
        btn_cancel = ctk.CTkButton(self.dl_progress, text="Cancel", fg_color="red", command=self._cancel_download)
        btn_cancel.pack(pady=10)
        
        downloader = RembgDownloader()
        
        # Thread-safe wrappers
        def safe_progress(val):
            self.after(0, lambda: self.dl_progress.set_progress(val))
            
        def safe_complete(success):
            self.after(0, lambda: self._on_download_complete(success))
            
        downloader.download_model(
            progress_callback=safe_progress,
            cancel_event=self.dl_cancel_event,
            on_complete=safe_complete
        )
        
    def _on_try_close_during_download(self):
        from tkinter import messagebox
        messagebox.showwarning("Download in Progress", "Please cancel the download before closing the application.")

    def _restore_close_handler(self):
        if hasattr(self, 'root_window') and hasattr(self, 'original_close_handler'):
            self.root_window.protocol("WM_DELETE_WINDOW", self.original_close_handler)

    def _cancel_download(self):
        self.dl_cancel_event.set()
        # Cleanup happens in _on_download_complete because download worker calls it regardless of success/fail
        
    def _on_download_complete(self, success):
        self.dl_progress.close()
        self._restore_close_handler()
        
        # Hide Dimmer
        if hasattr(self, 'root_window') and hasattr(self.root_window, 'hide_dimmer'):
            self.root_window.hide_dimmer()
        
        if success:
            self.after(0, self._check_rembg_model)
            from tkinter import messagebox
            messagebox.showinfo("Success", "Model downloaded successfully.")
        else:
            if not self.dl_cancel_event.is_set():
                from tkinter import messagebox
                messagebox.showerror("Error", "Download failed.")

    def toggle_rembg(self):
        if self.current_face:
            self.face_manager.push_update_state(self.current_face)
            
        if self.switch_rembg.get():
            self.rembg_settings_frame.pack(fill="x", padx=5, pady=5)
        else:
            self.rembg_settings_frame.pack_forget()
        self.update_preview()
        
    def toggle_alpha(self):
        if self.current_face:
            self.face_manager.push_update_state(self.current_face)
        self.update_preview()

    def set_view_mode(self, mode):
        self.view_mode = mode
        if mode == "Single":
            self.grid_view_frame.pack_forget()
            self.preview_frame.pack(expand=True, fill="both")
            self.btn_view_single.configure(fg_color=("gray75", "gray25"))
            self.btn_view_grid.configure(fg_color="transparent")
            self.lbl_zoom.configure(text="Zoom")
            self.slider_zoom.configure(from_=0.1, to=5.0)
            self.slider_zoom.set(self.view_zoom)
            self.update_preview()
        else:
            self.preview_frame.pack_forget()
            self.grid_view_frame.pack(expand=True, fill="both")
            self.btn_view_grid.configure(fg_color=("gray75", "gray25"))
            self.btn_view_single.configure(fg_color="transparent")
            self.lbl_zoom.configure(text="Thumb Size")
            self.slider_zoom.configure(from_=0.5, to=3.0) # Adjust range for grid?
            self.slider_zoom.set(1.0) # Reset or keep?
            self._refresh_grid_view()
            
        # Force layout update to prevent glitch
        self.update_idletasks()
        self.update_preview()



    def copy_from_normal(self):
        if not self.current_face or self.current_state_key == "normal": return
        states = self.current_face.get('states', {})
        normal_state = states.get('normal')
        if not normal_state: return
        
        # Copy values
        self.face_manager.push_update_state(self.current_face) # Undo snapshot
        
        current_state = states.get(self.current_state_key, {})
        current_state['scale'] = normal_state.get('scale', 1.0)
        current_state['offset_x'] = normal_state.get('offset_x', 0)
        current_state['offset_y'] = normal_state.get('offset_y', 0)
        current_state['use_rembg'] = normal_state.get('use_rembg', False)
        
        # Ensure state exists
        states[self.current_state_key] = current_state
        self._save_json()
        self.change_state(self.current_state_key) # Refresh UI

    def apply_to_all(self):
        if not self.current_face: return
        states = self.current_face.get('states', {})
        current_state = states.get(self.current_state_key)
        if not current_state: return
        
        from tkinter import messagebox
        if not messagebox.askyesno("Confirm", loc.get("confirm_apply_all")):
            return
            
        self.face_manager.push_update_state(self.current_face) # Undo snapshot
            
        for key in self.state_keys:
            if key == self.current_state_key: continue
            if key not in states: states[key] = {}
            
            s = states[key]
            s['scale'] = current_state.get('scale', 1.0)
            s['offset_x'] = current_state.get('offset_x', 0)
            s['offset_y'] = current_state.get('offset_y', 0)
            s['use_rembg'] = current_state.get('use_rembg', False)
            # Source UUID is NOT copied usually, as states might have different images
            
        self._save_json()
        from core.logger import Logger
        Logger.info(f"Applied settings to all states for {self.current_face.get('display_name')}")

    def _on_grid_configure(self, event):
        new_width = self.grid_view_frame.winfo_width()
        # Ignore small changes (e.g. scrollbar appearance) to prevent loops
        if abs(new_width - self.last_window_width) < 20: 
            return
            
        self.last_window_width = new_width
        
        if self.grid_resize_timer:
            self.after_cancel(self.grid_resize_timer)
        self.grid_resize_timer = self.after(200, self._refresh_grid_view)

    def _on_grid_scroll(self, event):
        try:
            # Scroll the canvas of the scrollable frame
            self.grid_view_frame._parent_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        except:
            pass

    def _on_zoom_slider_change(self, value):
        if self.ignore_slider_event: return
        
        val = float(value)
        if self.view_mode == "Grid":
            # Map 0.1-5.0 to 50-500
            # 1.0 -> 100
            # grid_size = int(val * 100) # Not needed here, refresh will read slider
            
            # Debounce with timer
            if self.grid_resize_timer:
                self.after_cancel(self.grid_resize_timer)
            
            # Delay refresh
            self.grid_resize_timer = self.after(100, self._refresh_grid_view)
            
        else:
            # Single View Zoom
            self.view_zoom = val
            self.update_preview()

    def load_character(self, face_data):
        # Check if we are reloading the same character (e.g. Undo/Redo)
        if self.current_face and face_data and self.current_face.get('uuid') == face_data.get('uuid'):
            # Smooth reload (Update values only)
            self.current_face = face_data
            self._reload_current_character_values(face_data)
            return

        # Remove loading overlay to prevent flickering on fast loads
        # self.loading_overlay.show()
        
        # Use after(10) to allow UI to update
        self.after(10, lambda: self._load_character_internal(face_data))
        
    def _reload_current_character_values(self, face_data):
        """Updates UI values from face_data without clearing the editor (Smooth Reload)."""
        try:
            # Update Name
            if self.entry_name.get() != face_data.get('display_name', ''):
                self.entry_name.delete(0, "end")
                self.entry_name.insert(0, face_data.get('display_name', ''))
            
            # Update Face Center
            fc = face_data.get('face_center')
            if fc:
                if self.spin_fc_x.get() != str(fc.get('x', 0)):
                    self.spin_fc_x.delete(0, "end")
                    self.spin_fc_x.insert(0, str(fc.get('x', 0)))
                if self.spin_fc_y.get() != str(fc.get('y', 0)):
                    self.spin_fc_y.delete(0, "end")
                    self.spin_fc_y.insert(0, str(fc.get('y', 0)))
            else:
                self.spin_fc_x.delete(0, "end")
                self.spin_fc_y.delete(0, "end")

            # Update Preview Settings (Zoom/Pan)
            # We might NOT want to reset Zoom/Pan on Undo if it wasn't part of the undo?
            # But undo restores the ENTIRE state, including preview settings if they were saved.
            # Actually, preview settings are saved in _save_json.
            # So if we undo, we restore previous zoom/pan.
            # This is correct behavior.
            preview_settings = face_data.get('preview_settings', {})
            self.view_zoom = preview_settings.get('view_zoom', 1.0)
            self.view_pan_x = preview_settings.get('view_pan_x', 0)
            self.view_pan_y = preview_settings.get('view_pan_y', 0)
            
            # Update Slider (if single view)
            if self.view_mode == "Single":
                self.ignore_slider_event = True
                self.slider_zoom.set(self.view_zoom)
                self.ignore_slider_event = False
            
            # Refresh State Buttons (in case status changed)
            self._update_state_buttons()
            
            # Refresh Current State UI (Sliders, etc.)
            # We need to force a refresh of the current state tab
            self.change_state(self.current_state_key, save_before_switch=False)
            
            # Update Preview
            self.update_preview()
            
        except Exception as e:
            Logger.error(f"Error in smooth reload: {e}")

    def _load_character_internal(self, face_data):
        self.is_loading = True
        try:
            # Save previous character if exists
            if self.current_face:
                self._save_json()
                
            # Clear previous state to avoid TclError
            self.clear_editor()
                
            if not face_data:
                return

            # Initialize if not managed
            status = face_data.get('_status', 'managed')
            if status != 'managed':
                # Initialize it
                face_data = self.face_manager.initialize_face(face_data)
                if not face_data:
                    # Failed to init
                    Logger.error("Failed to initialize face data")
                    return
                # Notify list to update status (e.g. remove "Empty" tag)
                if self.on_update_callback:
                    self.on_update_callback(face_data)

            self.current_face = face_data
                
            # Load Settings FIRST (Before showing editor/preview)
            self.entry_name.delete(0, "end")
            self.entry_name.insert(0, face_data.get('display_name', ''))
            self.change_state("normal", save_before_switch=False) # Reset to normal on load
            self._update_state_buttons()
            
            # Load Face Center
            fc = face_data.get('face_center')
            if fc:
                self.spin_fc_x.delete(0, "end")
                self.spin_fc_x.insert(0, str(fc.get('x', 0)))
                self.spin_fc_y.delete(0, "end")
                self.spin_fc_y.insert(0, str(fc.get('y', 0)))
            else:
                self.spin_fc_x.delete(0, "end")
                self.spin_fc_y.delete(0, "end")

            # Load Preview Settings
            preview_settings = face_data.get('preview_settings', {})
            self.view_zoom = preview_settings.get('view_zoom', 1.0)
            self.view_pan_x = preview_settings.get('view_pan_x', 0)
            self.view_pan_y = preview_settings.get('view_pan_y', 0)
            self.view_mode = preview_settings.get('view_mode', "Grid")
            
            show_ui = preview_settings.get('show_game_ui', False)
            if show_ui:
                self.switch_game_ui.select()
            else:
                self.switch_game_ui.deselect()

            # Show Editor
            self.show_editor(True)
            
        except Exception as e:
            Logger.error(f"Critical error in load_character: {e}\n{traceback.format_exc()}")
            from tkinter import messagebox
            messagebox.showerror("Load Error", f"Failed to load character: {e}")
            
        finally:
            self.is_loading = False
            # self.loading_overlay.hide()
            # Schedule update to allow UI to settle and prevent TclError
            self.after(200, self.update_preview)

    def _draw_marker(self, image, face_center):
        if face_center:
            x, y = face_center.get('x'), face_center.get('y')
            draw = ImageDraw.Draw(image)
            r = 20
            # Color depends on whether this is a Global or Local setting
            # But we only know the current mode.
            # If we are in Local mode, we might be viewing a Local pin.
            # If we are in Global mode, we are viewing a Global pin.
            # Let's use the current mode switch to decide color for now.
            is_individual = bool(self.chk_individual_mode.get())
            color = "#3B8ED0" if is_individual else "red" # Blue for Local, Red for Global
            
            draw.line((x-r, y, x+r, y), fill=color, width=3)
            draw.line((x, y-r, x, y+r), fill=color, width=3)
            draw.ellipse((x-r, y-r, x+r, y+r), outline=color, width=2)

    def on_mouse_down(self, event):
        if self.current_face:
            self.face_manager.push_update_state(self.current_face)
            
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.is_dragging = False

    def on_mouse_drag(self, event):
        if not self.current_face: return
        
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        
        if abs(dx) > self.drag_threshold or abs(dy) > self.drag_threshold:
            self.is_dragging = True
            
        if self.is_dragging:
            # Update offset
            # Need to scale dx/dy based on current zoom? 
            # Actually, moving the image by 1 pixel on screen should move it 1 pixel in offset?
            # No, offset is in original image coordinates? 
            # Wait, offset_x/y in state_data is "shift from center".
            # If we drag right, we want the image to move right -> offset_x increases.
            
            # Sensitivity factor
            # Convert screen pixels to target pixels (1920x1080)
            # Adjust for View Zoom
            img_w = self.current_image.width()
            img_h = self.current_image.height()
            # img_w is the DISPLAY width (already zoomed)
            
            # If view_zoom is 2.0, moving 10px on screen is 5px on original image
            scale_factor = (1920 / img_w) 
            
            # We update the slider directly which triggers update_preview
            current_x = self.slider_x.get()
            current_y = self.slider_y.get()
            
            self.slider_x.set(current_x + dx * scale_factor)
            self.slider_y.set(current_y + dy * scale_factor)
            
            # Update Entries Manually
            self.entry_x.delete(0, "end")
            self.entry_x.insert(0, str(int(self.slider_x.get())))
            self.entry_y.delete(0, "end")
            self.entry_y.insert(0, str(int(self.slider_y.get())))
            
            # Reset start to avoid continuous acceleration
            self.drag_start_x = event.x
            self.drag_start_y = event.y
            
            self.update_preview(fast_mode=True)

    def on_mouse_up(self, event):
        if not self.is_dragging:
            # It was a click -> Face Center
            self.on_preview_click(event)
        else:
            # Drag finished -> Full Render
            self._perform_full_render()
        self.is_dragging = False

    def on_mouse_wheel(self, event):
        if not self.current_face: return
        
        # View Zoom (Preview Only)
        current_zoom = self.view_zoom
        
        if event.num == 5 or event.delta < 0:
            # Zoom out
            new_zoom = max(0.1, current_zoom - 0.1)
        else:
            # Zoom in
            new_zoom = min(5.0, current_zoom + 0.1)
            
        self.view_zoom = new_zoom
        
        # Sync Slider (Use flag to prevent loop)
        if self.view_mode == "Single":
            self.ignore_slider_event = True
            self.slider_zoom.set(new_zoom)
            self.ignore_slider_event = False
            
        self.update_preview(fast_mode=True)
        
        # Debounce Full Render
        if self.preview_timer:
            self.after_cancel(self.preview_timer)
        self.preview_timer = self.after(500, self._perform_full_render)

    def on_pan_start(self, event):
        self.is_panning = True
        self.pan_start_x = event.x_root
        self.pan_start_y = event.y_root

    def on_pan_drag(self, event):
        if not self.is_panning: return
        
        dx = event.x_root - self.pan_start_x
        dy = event.y_root - self.pan_start_y
        
        self.view_pan_x += dx
        self.view_pan_y += dy
        
        self.pan_start_x = event.x_root
        self.pan_start_y = event.y_root
        
        self._update_preview_position()

    def on_pan_end(self, event):
        self.is_panning = False

    def _update_preview_position(self):
        # Update label position based on pan
        self.lbl_preview.place(relx=0.5, rely=0.5, anchor="center", x=self.view_pan_x, y=self.view_pan_y)

    def toggle_individual_mode(self):
        if self.current_face:
            self.face_manager.push_update_state(self.current_face)
            
        is_local = bool(self.chk_individual_mode.get())
        
        # Save mode to current state
        if self.current_face and self.current_state_key:
            states = self.current_face.get('states', {})
            state_data = states.get(self.current_state_key, {})
            state_data['is_individual'] = is_local
            # Ensure state exists
            if self.current_state_key not in states:
                states[self.current_state_key] = state_data
        
        # Update Indicator Visibility
        if is_local:
            self.lbl_individual_indicator.place(x=10, y=10)
            self.lbl_individual_indicator.lift()
        else:
            self.lbl_individual_indicator.place_forget()
        
        if not is_local:
            # Transition: Local -> Global
            # Check if defaults exist
            defaults = self.current_face.get('defaults')
            
            if defaults:
                # Case A: Defaults Exist -> Confirm Revert
                from tkinter import messagebox
                if messagebox.askokcancel("Confirm", loc.get("confirm_revert_global")):
                    # Revert to Global Defaults
                    self._apply_settings(defaults)
                    self.update_preview() # This will trigger global sync
                else:
                    # Cancel -> Revert Checkbox
                    self.chk_individual_mode.select()
            return
            
        self.update_preview()
        
    def on_preview_click(self, event):
        if not self.current_face or not self.current_image: return
        
        click_x = event.x
        click_y = event.y
        
        # Get current display size
        img_w = self.current_image.width()
        img_h = self.current_image.height()
        
        # Scale back to original resolution (1920x1080)
        scale_x = 1920 / img_w
        scale_y = 1080 / img_h
        
        real_x = int(click_x * scale_x)
        real_y = int(click_y * scale_y)
        
        real_x = max(0, min(1920, real_x))
        real_y = max(0, min(1080, real_y))
        
        if self.pin_mode == "Global":
            self.update_face_center(real_x, real_y)
        else:
            # Local Mode: Move image so that clicked point aligns with Face Center
            fc = self.current_face.get('face_center')
            if not fc: return # Should not happen if we are editing
            
            target_x, target_y = fc.get('x', 960), fc.get('y', 540)
            
            # Shift needed = Target - Clicked
            shift_x = target_x - real_x
            shift_y = target_y - real_y
            
            # Update sliders (which updates offset)
            current_offset_x = int(self.slider_x.get())
            current_offset_y = int(self.slider_y.get())
            
            self.slider_x.set(current_offset_x + shift_x)
            self.slider_y.set(current_offset_y + shift_y)
            self.update_preview()

    def update_face_center_from_entry(self, event=None):
        try:
            x = int(self.spin_fc_x.get())
            y = int(self.spin_fc_y.get())
            self.update_face_center(x, y)
        except ValueError:
            pass

    def update_face_center(self, x, y):
        if not self.current_face: return
        
        self.face_manager.push_update_state(self.current_face) # Undo snapshot
        
        is_individual = bool(self.chk_individual_mode.get())
        
        if not is_individual:
            # Global Mode: Update Defaults and ALL states
            if 'defaults' not in self.current_face: self.current_face['defaults'] = {}
            self.current_face['defaults']['face_center'] = {'x': x, 'y': y}
            
            # Update Global Face Center (Legacy/Fallback)
            self.current_face['face_center'] = {'x': x, 'y': y}
            
            states = self.current_face.get('states', {})
            for key in states:
                if states[key]:
                    # Skip states that are marked as Individual
                    if states[key].get('is_individual', False):
                        continue
                    states[key]['face_center'] = {'x': x, 'y': y}
        else:
            # Local Mode: Update ONLY current state
            states = self.current_face.get('states', {})
            if self.current_state_key not in states:
                states[self.current_state_key] = {}
            states[self.current_state_key]['face_center'] = {'x': x, 'y': y}
        
        self.spin_fc_x.delete(0, "end")
        self.spin_fc_x.insert(0, str(x))
        self.spin_fc_y.delete(0, "end")
        self.spin_fc_y.insert(0, str(y))
        
        self._save_json()
        self.update_preview()

    def save_character(self):
        if not self.current_face:
            return
            
        # Validation
        # Removed blocking check for face_center. 
        # The save thread handles missing face_center by defaulting to image center.
        # Also, in Local Mode, the global face_center might not be set, which caused this check to fail incorrectly.
        
        # if not self.current_face.get('face_center'):
        #     from tkinter import messagebox
        #     messagebox.showwarning("Warning", loc.get("error.no_face_center", "Face center not set!"))
        #     return

        # Show Loading Overlay
        Logger.info("Showing loading overlay for save...")
        self.loading_overlay.label.configure(text=loc.get("saving", "Saving..."))
        self.loading_overlay.show()
        
        # Run in thread (Delay slightly to allow UI to update)
        Logger.info("Starting save thread...")
        self.after(10, lambda: threading.Thread(target=self._save_character_thread, daemon=True).start())
        
    def _save_character_thread(self):
        try:
            Logger.info(f"Starting save process for: {self.current_face.get('display_name')}")
            
            # 1. Save JSON (Thread-safe enough for file I/O, but careful with shared state)
            # Ideally we should clone the data before passing to thread, but for now we assume no concurrent edits.
            self._save_json()
            Logger.info("JSON saved.")
            
            # 2. Export Images
            face_dir = self.current_face.get('_path')
            Logger.info(f"Face directory: {face_dir}")
            
            if not face_dir:
                Logger.error("Face directory is missing!")
                self.after(0, self._on_save_complete)
                return

            states = self.current_face.get('states', {})
            Logger.info(f"States found: {list(states.keys())}")
            
            suffix_map = {
                "normal": "",
                "poison": "_PO", "hp_75": "_75", "hp_50": "_50", "hp_25": "_25", "dead": "_DE",
                "afraid": "_AF", "sleep": "_SL", "paralyzed": "_PA", "stoned": "_ST", "ashed": "_AS"
            }
            
            count_saved = 0
            
            for key, suffix in suffix_map.items():
                state_data = states.get(key)
                if not state_data: 
                    # Logger.debug(f"Skipping {key}: No state data")
                    continue
                
                source_uuid = state_data.get('source_uuid')
                if not source_uuid: 
                    Logger.info(f"Skipping {key}: No source UUID")
                    continue
                
                source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
                if not source_path: 
                    Logger.warning(f"Skipping {key}: Source path not found for UUID {source_uuid}")
                    continue
                
                frame_id = self.current_face.get('frame_id')
                frame_path = self.face_manager.get_frame_path(frame_id)
                
                # Resolve Face Center for this state
                face_center = state_data.get('face_center')
                if not face_center:
                    # Fallback to defaults/global
                    face_center = self.current_face.get('defaults', {}).get('face_center')
                    if not face_center:
                        face_center = self.current_face.get('face_center')
                
                Logger.info(f"Processing {key}...")
                
                # Render 1920x1080 (face_c)
                img_full = self.image_processor.process_image(source_path, state_data, (1920, 1080), frame_path=frame_path)
                if img_full:
                    # Save face_c
                    filename = f"face_c{suffix}.png"
                    save_path = os.path.join(face_dir, filename)
                    img_full.save(save_path)
                    Logger.info(f"Saved {filename}")
                    
                    # Save face_d (Copy of c)
                    img_full.save(os.path.join(face_dir, f"face_d{suffix}.png"))
                    
                    # Save face_e (Copy of c)
                    img_full.save(os.path.join(face_dir, f"face_e{suffix}.png"))
                    
                    # Save face_b (270x96) - For ALL states
                    img_b = self.image_processor.create_face_icon(img_full, (270, 96), face_center)
                    img_b.save(os.path.join(face_dir, f"face_b{suffix}.png"))
                    
                    # If normal state, generate face_a
                    if key == "normal":
                        # face_a (96x96)
                        img_a = self.image_processor.create_face_icon(img_full, (96, 96), face_center)
                        img_a.save(os.path.join(face_dir, "face_a.png"))
                        Logger.info("Saved face_a.png")
                        
                    count_saved += 1
                else:
                    Logger.error(f"Failed to process image for {key}")
            
            Logger.info(f"Saved character to {face_dir}. Total states processed: {count_saved}")
            
        except Exception as e:
            Logger.error(f"Error saving character: {e}\n{traceback.format_exc()}")
            print(f"Error saving character: {e}")
            
        finally:
            self.after(0, self._on_save_complete)

    def _on_save_complete(self):
        self.loading_overlay.hide()
        self._show_save_success()
        if self.on_update_callback:
            self.on_update_callback(self.current_face)

    def _show_save_success(self):
        original_text = self.btn_save.cget("text")
        original_color = self.btn_save.cget("fg_color")
        
        self.btn_save.configure(text=loc.get("saved", "Saved!"), fg_color="#2CC985") # Brighter green
        
        def revert():
            try:
                self.btn_save.configure(text=original_text, fg_color=original_color)
            except:
                pass
                
        self.after(2000, revert)

    def delete_character(self):
        if not self.current_face:
            return
            
        from tkinter import messagebox
        if messagebox.askyesno(loc.get("delete"), loc.get("confirm_delete")):
            if self.face_manager.delete_face(self.current_face):
                # Notify App to refresh list
                if self.on_update_callback:
                    self.on_update_callback(None)
                
                # Clear editor
                self.clear_editor()
            else:
                messagebox.showerror("Error", loc.get("error_delete_failed", "Failed to delete character. Check logs."))

    def _save_json(self):
        # Capture Preview Settings
        if self.current_face:
            self.current_face['preview_settings'] = {
                'view_zoom': self.view_zoom,
                'view_pan_x': self.view_pan_x,
                'view_pan_y': self.view_pan_y,
                'show_game_ui': bool(self.switch_game_ui.get()),
                'view_mode': self.view_mode
            }
            
        face_dir = self.current_face.get('_path')
        if face_dir:
            self.face_manager.save_project_data(face_dir, self.current_face)

    def _commit_ui_to_data(self):
        """Saves current UI settings to the current state data (or global defaults)."""
        if not self.current_face:
            return

        # Gather current UI values
        current_settings = {
            'scale': self.slider_scale.get(),
            'offset_x': int(self.slider_x.get()),
            'offset_y': int(self.slider_y.get()),
            'icon_scale_a': self.slider_icon_scale_a.get(),
            'icon_scale_b': self.slider_icon_scale_b.get(),
            'use_rembg': bool(self.switch_rembg.get()),
            'alpha_matting': bool(self.switch_alpha.get())
            # Presets are updated directly via on_preset_change, so we don't overwrite them here.
            # Existing values in state_data will be preserved.
        }
        
        # Add Face Center from spinboxes if valid
        try:
            fc_x = int(self.spin_fc_x.get())
            fc_y = int(self.spin_fc_y.get())
            current_settings['face_center'] = {'x': fc_x, 'y': fc_y}
        except ValueError:
            pass

        # Determine target(s)
        states = self.current_face.get('states', {})
        
        # If Global Mode (Individual Adjust OFF), update Defaults and ALL states
        # The switch self.chk_individual_mode determines this.
        is_individual = bool(self.chk_individual_mode.get())
        
        if not is_individual:
            # Update Global Defaults
            defaults = self.current_face.get('defaults', {})
            defaults.update(current_settings)
            self.current_face['defaults'] = defaults
            
            # Update ALL states to match (Sync)
            for key in states:
                if states[key]:
                    # Skip states that are marked as Individual
                    if states[key].get('is_individual', False):
                        continue
                    states[key].update(current_settings)
        else:
            # Update ONLY current state
            # Ensure state exists
            if self.current_state_key not in states:
                states[self.current_state_key] = {}
                
            state_data = states.get(self.current_state_key)
            if state_data is not None:
                state_data.update(current_settings)

    def on_preset_change(self, value):
        # Level 1: 240, 10, 0
        # Level 2: 240, 10, 5
        # Level 3: 240, 10, 10
        # Level 4: 240, 20, 10
        # Level 5: 240, 40, 15
        presets = {
            "1": (240, 10, 0),
            "2": (240, 10, 5),
            "3": (240, 10, 10),
            "4": (240, 20, 10),
            "5": (240, 40, 15)
        }
        fg, bg, erode = presets.get(value, (240, 10, 10))
        
        # Prepare settings dict
        settings = {
            'alpha_matting_foreground_threshold': fg,
            'alpha_matting_background_threshold': bg,
            'alpha_matting_erode_size': erode
        }

        if not self.current_face: return

        self.face_manager.push_update_state(self.current_face) # Undo snapshot

        # Check Individual Mode
        is_individual = bool(self.chk_individual_mode.get())
        
        states = self.current_face.get('states', {})
        
        if not is_individual:
            # Global Update
            # Update Defaults
            defaults = self.current_face.get('defaults', {})
            defaults.update(settings)
            self.current_face['defaults'] = defaults
            
            # Update ALL states (except those marked individual)
            for key in states:
                if states[key]:
                    if states[key].get('is_individual', False):
                        continue
                    states[key].update(settings)
        else:
            # Local Update
            state_data = states.get(self.current_state_key)
            if state_data:
                state_data.update(settings)
                
        # Trigger Preview Update (Full render if not fast mode, which is default)
        self.update_preview()

    def _perform_full_render(self):
        """Async full render (Background)"""
        # Logger.info(f"_perform_full_render called. Stack: {''.join(traceback.format_stack()[-3:])}")
        if getattr(self, 'is_loading', False): return
        
        # self.loading_overlay.show() # Removed to prevent flicker
        self.is_loading = True
        
        def run():
            try:
                # Generate image in thread
                result = self._generate_preview_image_internal(fast_mode=False)
                
                # Schedule update on main thread
                self.after(0, lambda: self._on_full_render_complete(result))
                
            except Exception as e:
                Logger.error(f"Error in full render thread: {e}")
                # self.after(0, lambda: self.loading_overlay.hide())
                self.is_loading = False

        threading.Thread(target=run, daemon=True).start()

    def _on_full_render_complete(self, result):
        try:
            display_img, processed_img, icon_a, icon_b = result
            
            # Update UI
            if display_img:
                # Clear previous
                self.lbl_preview.configure(image=None)
                
                # Create PhotoImage
                photo_img = ImageTk.PhotoImage(display_img)
                self.current_image = photo_img
                self.current_pil_image = processed_img
                
                self.lbl_preview.configure(image=photo_img, text="")
                self._update_preview_position()
                
            if icon_a and icon_b:
                photo_icon_a = ImageTk.PhotoImage(icon_a)
                photo_icon_b = ImageTk.PhotoImage(icon_b)
                self.current_icon_a = photo_icon_a
                self.current_icon_b = photo_icon_b
                self.lbl_icon_a.configure(image=photo_icon_a, text="")
                self.lbl_icon_b.configure(image=photo_icon_b, text="")
                
        except Exception as e:
            Logger.error(f"Error updating UI after full render: {e}")
            
        finally:
            # self.loading_overlay.hide()
            self.is_loading = False

    def _generate_preview_image_internal(self, fast_mode=False):
        """Internal generation logic. 
        WARNING: If running in thread, DO NOT access Tkinter widgets/vars directly.
        """
        # Get Data
        states = self.current_face.get('states', {})
        state_data = states.get(self.current_state_key)
        if not state_data: return (None, None, None, None)
        
        source_uuid = state_data.get('source_uuid')
        if not source_uuid: return (None, None, None, None)
            
        source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
        if not source_path or not os.path.exists(source_path): return (None, None, None, None)

        resample_filter = Image.Resampling.NEAREST if fast_mode else Image.Resampling.LANCZOS

        # Cache Key
        current_cache_key = (
            source_uuid,
            state_data.get('use_rembg'),
            state_data.get('alpha_matting'),
            state_data.get('alpha_matting_foreground_threshold'),
            state_data.get('alpha_matting_background_threshold'),
            state_data.get('alpha_matting_erode_size')
        )
        
        # Preprocess (Thread-safe if image_processor is)
        if self.cache_key != current_cache_key:
            # Logger.info(f"Cache Key Mismatch! Old: {self.cache_key}, New: {current_cache_key}")
            self.cached_processed_image = self.image_processor.preprocess_image(source_path, state_data)
            self.cache_key = current_cache_key
            
        face_center = state_data.get('face_center')
        if not face_center:
            face_center = self.current_face.get('defaults', {}).get('face_center')

        # Clean Image
        current_clean_key = (
            self.cache_key,
            state_data.get('scale'),
            state_data.get('offset_x'),
            state_data.get('offset_y'),
            face_center.get('x') if face_center else None,
            face_center.get('y') if face_center else None
        )
        
        clean_img = None
        if self.clean_cache_key == current_clean_key and self.cached_clean_image:
            clean_img = self.cached_clean_image
        else:
            clean_img = self.image_processor.process_image(
                source_path, 
                state_data, 
                target_size=(1920, 1080),
                preprocessed_image=self.cached_processed_image,
                face_center=face_center
            )
            if not fast_mode:
                self.cached_clean_image = clean_img
                self.clean_cache_key = current_clean_key
            
        icon_a = None
        icon_b = None
        processed_img = None
        
        if clean_img:
            # Icons
            icon_scale_a = state_data.get('icon_scale_a', state_data.get('icon_scale', 1.0))
            icon_scale_b = state_data.get('icon_scale_b', state_data.get('icon_scale', 1.0))
            
            fc_dict = None
            if face_center:
                fc_dict = {'x': face_center.get('x'), 'y': face_center.get('y')}
                
            icon_a = self.image_processor.create_face_icon(clean_img, (96, 96), fc_dict, icon_scale_a)
            icon_b = self.image_processor.create_face_icon(clean_img, (270, 96), fc_dict, icon_scale_b)

            # Game UI Background
            processed_img = clean_img.copy()
            
            # Safe access to switch_game_ui
            show_ui = False
            try:
                # If running in thread, this might be risky but usually works for reading.
                # Ideally pass as arg.
                show_ui = self.switch_game_ui.get()
            except:
                pass
            
            if show_ui:
                try:
                    assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "assets")
                    bg01_path = os.path.join(assets_dir, "preview_bg_01.png")
                    bg02_path = os.path.join(assets_dir, "preview_bg_02.png")
                    
                    if os.path.exists(bg01_path):
                        base_img = Image.open(bg01_path).convert("RGBA")
                        if base_img.size != (1920, 1080):
                            base_img = base_img.resize((1920, 1080), resample_filter)
                    else:
                        base_img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))

                    base_img.alpha_composite(clean_img)
                    
                    if os.path.exists(bg02_path):
                        fg_img = Image.open(bg02_path).convert("RGBA")
                        if fg_img.size != (1920, 1080):
                            fg_img = fg_img.resize((1920, 1080), resample_filter)
                        base_img.alpha_composite(fg_img)
                        
                    processed_img = base_img
                except Exception as e:
                    Logger.error(f"Error loading game UI background: {e}")

            # Draw Marker
            self._draw_marker(processed_img, face_center)
        
        # Resize for preview
        display_img = None
        if processed_img:
            try:
                preview_height = self.preview_frame.winfo_height()
            except:
                preview_height = 400
                
            if preview_height < 100: preview_height = 400
            
            ratio = processed_img.width / processed_img.height
            new_h = preview_height - 50
            new_w = int(new_h * ratio)
            
            display_img = processed_img.resize((new_w, new_h), resample_filter)
            
            # View Zoom
            if self.view_zoom != 1.0:
                zw = int(new_w * self.view_zoom)
                zh = int(new_h * self.view_zoom)
                display_img = display_img.resize((zw, zh), Image.Resampling.NEAREST)
                
        return (display_img, processed_img, icon_a, icon_b)
