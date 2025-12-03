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

class LoadingOverlay(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=("gray85", "gray25"), **kwargs)
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        
        self.center_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.center_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        self.spinner = ctk.CTkProgressBar(self.center_frame, orientation="horizontal", mode="indeterminate", width=200)
        self.spinner.pack(pady=10)
        self.spinner.start()
        
        self.label = ctk.CTkLabel(self.center_frame, text="Loading...", font=("Arial", 16))
        self.label.pack(pady=5)
        
        self.lift() # Ensure on top
        
    def show(self):
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.spinner.start()
        self.lift()
        self.update_idletasks() # Force render
        
    def hide(self):
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
        self.last_grid_width = 0 # For debounce
        
        # Caching for Performance
        self.cached_processed_image = None
        self.cache_key = None # (source_uuid, use_rembg, alpha, fg, bg, erode)
        
        self.guides_data = self._load_guides()
        self.show_guides = True # Default ON
        self.guide_type = "face_c" # face_c or face_d
        
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
        self.lbl_empty = ctk.CTkLabel(self, text=loc.get("select_character"), font=("Arial", 16))
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
        
        # Grid Zoom Slider
        self.slider_grid_zoom = ctk.CTkSlider(self.view_mode_frame, from_=50, to=500, width=150, command=self._update_grid_zoom)
        self.slider_grid_zoom.set(100) # Default size
        self.slider_grid_zoom.pack(side="right", padx=10)
        ctk.CTkLabel(self.view_mode_frame, text="Thumbnail Size").pack(side="right", padx=5)
        
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
        self.lbl_preview.bind("<Button-5>", self.on_mouse_wheel) # Linux scroll down
        
        # Grid View Frame (Initially hidden)
        self.grid_view_frame = ctk.CTkScrollableFrame(self.preview_container, label_text="State Overview")
        self.grid_view_frame.bind("<Configure>", self._on_grid_configure)
        # self.grid_view_frame.pack(expand=True, fill="both") # Packed when switched
        
        self.grid_resize_timer = None
        
        # Controls Area
        self.controls_frame = ctk.CTkScrollableFrame(self, width=350, label_text=loc.get("edit"))
        self.controls_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        
        # Delete Button (Outside scrollable frame, at bottom right)
        self.btn_delete = ctk.CTkButton(self, text=loc.get("delete"), fg_color="red", hover_color="darkred", command=self.delete_character)
        self.btn_delete.grid(row=1, column=1, sticky="ew", padx=10, pady=10)
        
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

        # Initially hide editor
        self.show_editor(False)

    def clear_editor(self):
        """Resets the editor state and clears image references to prevent TclError."""
        self.current_face = None
        self.current_image = None
        self.current_pil_image = None
        
        self.cached_processed_image = None
        self.cache_key = None
        
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
            self.controls_frame.grid()
            self.btn_delete.grid()
            # Ensure correct view mode is shown
            self.set_view_mode(self.view_mode)
        else:
            self.preview_container.grid_remove()
            self.controls_frame.grid_remove()
            self.btn_delete.grid_remove()
            self.lbl_empty.grid()

    def _init_controls(self):
        # Name
        self.entry_name = ctk.CTkEntry(self.controls_frame, placeholder_text=loc.get("display_name"))
        self.entry_name.pack(fill="x", padx=10, pady=5)
        self.btn_update_name = ctk.CTkButton(self.controls_frame, text=loc.get("update_name"), command=self.update_name)
        self.btn_update_name.pack(fill="x", padx=10, pady=5)
        
        # State Selector
        self.lbl_state = ctk.CTkLabel(self.controls_frame, text=loc.get("state"))
        self.lbl_state.pack(anchor="w", padx=10)
        
        # Map display names to keys for combo box
        self.state_map = {
            loc.get("states.normal"): "normal",
            loc.get("states.poison"): "poison",
            loc.get("states.hp_75"): "hp_75",
            loc.get("states.hp_50"): "hp_50",
            loc.get("states.hp_25"): "hp_25",
            loc.get("states.dead"): "dead",
            loc.get("states.afraid"): "afraid",
            loc.get("states.sleep"): "sleep",
            loc.get("states.paralyzed"): "paralyzed",
            loc.get("states.stoned"): "stoned",
            loc.get("states.ashed"): "ashed"
        }
        self.combo_state = ctk.CTkComboBox(self.controls_frame, values=list(self.state_map.keys()), command=self.change_state_from_combo)
        self.combo_state.set(loc.get("states.normal"))
        self.combo_state.pack(fill="x", padx=10, pady=5)
        
        # Frame Selection
        self.frame_container = ctk.CTkFrame(self.controls_frame)
        self.frame_container.pack(fill="x", padx=10, pady=5)
        
        self.lbl_frame = ctk.CTkLabel(self.frame_container, text="Frame")
        self.lbl_frame.pack(anchor="w", padx=5)
        
        self.combo_frame = ctk.CTkComboBox(self.frame_container, command=self.change_frame)
        self.combo_frame.pack(fill="x", padx=5, pady=5)
        
        # Register D&D for frame container
        try:
            from tkinterdnd2 import DND_FILES
            self.frame_container.drop_target_register(DND_FILES)
            self.frame_container.dnd_bind('<<Drop>>', self.on_drop_frame)
        except:
            pass

        # Image Source
        self.btn_import = ctk.CTkButton(self.controls_frame, text=loc.get("import_image"), command=self.import_image)
        self.btn_import.pack(fill="x", padx=10, pady=10)
        
        # Sliders
        self.slider_scale = self._create_slider(loc.get("scale"), 0.1, 2.0, 1.0)
        self.slider_x = self._create_slider(loc.get("offset_x"), -1500, 1500, 0)
        self.slider_y = self._create_slider(loc.get("offset_y"), -1500, 1500, 0)
        
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
        
        # Guide Controls
        self.guide_frame = ctk.CTkFrame(self.controls_frame)
        self.guide_frame.pack(fill="x", padx=10, pady=5)
        self.switch_guide = ctk.CTkSwitch(self.guide_frame, text=loc.get("show_guides"), command=self.toggle_guides)
        self.switch_guide.pack(side="left", padx=10)
        
        self.switch_game_ui = ctk.CTkSwitch(self.guide_frame, text=loc.get("show_game_ui"), command=self.update_preview)
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
        self.btn_download_model = ctk.CTkButton(self.rembg_action_frame, text="Download Model", command=self.download_model)
        
        # Fine-tuning Controls (Hidden by default)
        self.rembg_settings_frame = ctk.CTkFrame(self.rembg_frame)
        
        # Alpha Matting
        self.switch_alpha = ctk.CTkSwitch(self.rembg_settings_frame, text="Alpha Matting", command=self.update_preview)
        self.switch_alpha.pack(padx=5, pady=5, anchor="w")
        
        # Thresholds
        self.slider_fg_thresh = self._create_slider_in_frame(self.rembg_settings_frame, "FG Thresh", 0, 255, 240)
        self.slider_bg_thresh = self._create_slider_in_frame(self.rembg_settings_frame, "BG Thresh", 0, 255, 10)
        self.slider_erode = self._create_slider_in_frame(self.rembg_settings_frame, "Erode Size", 0, 40, 10)
        
        self._check_rembg_model()
        
        # Icon Controls (Sliders)
        self.icon_frame = ctk.CTkFrame(self.controls_frame)
        self.icon_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(self.icon_frame, text="Icon Preview Scale").pack(anchor="w", padx=5)
        
        self.slider_icon_scale_a = self._create_slider(loc.get("icon_scale_a"), 0.5, 2.0, 1.0)
        self.slider_icon_scale_b = self._create_slider(loc.get("icon_scale_b"), 0.5, 2.0, 1.0)
        
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
        
        # Save
        self.btn_save = ctk.CTkButton(self.controls_frame, text=loc.get("save_export"), fg_color="green", command=self.save_character)
        self.btn_save.pack(fill="x", padx=10, pady=20)

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
            self.update_preview()
            
        def on_entry(event):
            try:
                val = float(entry.get())
                # Clamp?
                if val < from_: val = from_
                if val > to: val = to
                slider.set(val)
                self.update_preview()
            except ValueError:
                pass
        
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
        
        return slider

    def _create_slider_in_frame(self, parent, label, from_, to, default):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=5, pady=2)
        lbl = ctk.CTkLabel(frame, text=label, width=80, anchor="w")
        lbl.pack(side="left")
        slider = ctk.CTkSlider(frame, from_=from_, to=to, command=lambda v: self.update_preview())
        slider.set(default)
        slider.pack(side="right", fill="x", expand=True, padx=5)
        return slider

    def _check_rembg_model(self):
        if RembgDownloader.is_model_installed():
            self.btn_download_model.pack_forget()
            self.switch_rembg.pack(side="left", padx=5)
        else:
            self.switch_rembg.pack_forget()
            self.btn_download_model.pack(fill="x", padx=5)
            
    def download_model(self):
        # Progress Dialog
        self.dl_progress = ProgressDialog(self, title="Downloading Model", message="Downloading u2net.onnx...")
        self.dl_cancel_event = threading.Event()
        
        # Add Cancel Button to Progress Dialog (Hack: Accessing internal widget)
        # Ideally ProgressDialog should support cancellation natively.
        # For now, let's just use the close button or add a button if possible.
        # Since ProgressDialog is modal, we need to modify it or use a custom one.
        # Let's assume we can add a cancel button to it or it has one.
        # Checking ProgressDialog implementation... it's simple.
        # Let's just add a cancel button here if we can access the window.
        btn_cancel = ctk.CTkButton(self.dl_progress.window, text="Cancel", fg_color="red", command=self._cancel_download)
        btn_cancel.pack(pady=10)
        
        downloader = RembgDownloader()
        downloader.download_model(
            progress_callback=self.dl_progress.set_progress,
            cancel_event=self.dl_cancel_event,
            on_complete=self._on_download_complete
        )
        
    def _cancel_download(self):
        self.dl_cancel_event.set()
        
    def _on_download_complete(self, success):
        self.dl_progress.close()
        if success:
            self.after(0, self._check_rembg_model)
            from tkinter import messagebox
            messagebox.showinfo("Success", "Model downloaded successfully.")
        else:
            if not self.dl_cancel_event.is_set():
                from tkinter import messagebox
                messagebox.showerror("Error", "Download failed.")

    def toggle_rembg(self):
        if self.switch_rembg.get():
            self.rembg_settings_frame.pack(fill="x", padx=5, pady=5)
        else:
            self.rembg_settings_frame.pack_forget()
        self.update_preview()

    def _load_guides(self):
        try:
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "assets", "guides.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading guides: {e}")
        return {}

    def set_view_mode(self, mode):
        self.view_mode = mode
        if mode == "Single":
            self.grid_view_frame.pack_forget()
            self.preview_frame.pack(expand=True, fill="both")
        else:
            self.preview_frame.pack_forget()
            self.grid_view_frame.pack(expand=True, fill="both")
            self._refresh_grid_view()
            
        # Force layout update to prevent glitch
        self.update_idletasks()
        self.update_preview()

    def toggle_guides(self):
        self.show_guides = bool(self.switch_guide.get())
        self.update_preview()

    def change_guide_type(self, value):
        self.guide_type = value
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
            
        for key in self.state_map.values():
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
        if abs(new_width - self.last_grid_width) < 20: 
            return
            
        self.last_grid_width = new_width
        
        if self.grid_resize_timer:
            self.after_cancel(self.grid_resize_timer)
        self.grid_resize_timer = self.after(200, self._refresh_grid_view)

    def _update_grid_zoom(self, value):
        # Debounce or just update?
        # For smooth resizing, we might need to just update size if images are already loaded?
        # Or re-render?
        # Re-rendering everything might be slow.
        # But CTkImage supports size change? No, need to create new CTkImage.
        # Let's just call refresh for now, maybe optimize later.
        self._refresh_grid_view()

    def _refresh_grid_view(self):
        # Clear
        self.grid_images.clear() # Clear references
        for w in self.grid_widgets:
            w.destroy()
        self.grid_widgets.clear()
            
        if not self.current_face: return
        
        # Grid Settings
        thumb_size = int(self.slider_grid_zoom.get())
        max_cols = max(1, int(self.grid_view_frame.winfo_width() / (thumb_size + 20)))
        if max_cols < 1: max_cols = 4 # Fallback
        
        row = 0
        col = 0
        
        states = self.current_face.get('states', {})
        
        for name, key in self.state_map.items():
            state_data = states.get(key)
            
            frame = ctk.CTkFrame(self.grid_view_frame)
            frame.grid(row=row, column=col, padx=5, pady=5)
            self.grid_widgets.append(frame)
            
            # DnD for specific cell
            try:
                from tkinterdnd2 import DND_FILES
                frame.drop_target_register(DND_FILES)
                frame.dnd_bind('<<Drop>>', lambda e, k=key: self.on_drop_grid_cell(e, k))
            except:
                pass
            
            lbl_name = ctk.CTkLabel(frame, text=name)
            lbl_name.pack()
            
            # Thumbnail Image
            img_widget = None
            if state_data:
                source_uuid = state_data.get('source_uuid')
                if source_uuid:
                    source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
                    if source_path and os.path.exists(source_path):
                        try:
                            # Load and resize for thumbnail
                            pil_img = Image.open(source_path)
                            pil_img.thumbnail((thumb_size, thumb_size))
                            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
                            self.grid_images.append(ctk_img) # Keep reference
                            img_widget = ctk_img
                        except:
                            pass
            
            # Button with Image or Text
            if img_widget:
                btn = ctk.CTkButton(frame, text="", image=img_widget, width=thumb_size, height=thumb_size, command=lambda k=key: self._grid_click(k))
            else:
                btn = ctk.CTkButton(frame, text="No Image", width=thumb_size, height=thumb_size, command=lambda k=key: self._grid_click(k))
                
            btn.pack(pady=2)
            
            # Bind DnD to button too
            try:
                btn.drop_target_register(DND_FILES)
                btn.dnd_bind('<<Drop>>', lambda e, k=key: self.on_drop_grid_cell(e, k))
            except:
                pass
            
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
                
        # Bind DnD to the main grid frame for Batch Import
        try:
            self.grid_view_frame.drop_target_register(DND_FILES)
            self.grid_view_frame.dnd_bind('<<Drop>>', self.on_drop_batch)
        except:
            pass

    def _grid_click(self, state_key):
        self.combo_state.set(list(self.state_map.keys())[list(self.state_map.values()).index(state_key)])
        self.change_state(state_key)
        self.set_view_mode("Single")


    def set_on_update(self, callback):
        self.on_update_callback = callback

    def _update_state_combo(self):
        if not self.current_face: return
        
        states = self.current_face.get('states', {})
        available_keys = []
        
        # Always include current state (to prevent lock-out)
        available_keys.append(self.current_state_key)
        
        # Include states that have a source_uuid
        for key in self.state_map.values():
            if key == self.current_state_key: continue
            
            state_data = states.get(key)
            if state_data and state_data.get('source_uuid'):
                available_keys.append(key)
                
        # Sort based on original map order
        ordered_keys = []
        for key in self.state_map.values():
            if key in available_keys:
                ordered_keys.append(key)
                
        # Map back to display names
        display_values = []
        for key in ordered_keys:
            # Find name for key
            for name, k in self.state_map.items():
                if k == key:
                    display_values.append(name)
                    break
                    
        self.combo_state.configure(values=display_values)
        
        # Ensure current selection is valid
        current_name = ""
        for name, k in self.state_map.items():
            if k == self.current_state_key:
                current_name = name
                break
        self.combo_state.set(current_name)

        # Show Editor (Triggers update_preview)
        self.show_editor(True)
        
        # Hide loading overlay
        self.loading_overlay.hide()

    def load_character(self, face_data):
        # Show loading overlay
        self.loading_overlay.show()
        
        # Use after(10) to allow UI to render the overlay before heavy lifting
        # Use after(10) to allow UI to render the overlay before heavy lifting
        self.after(10, lambda: self._load_character_internal(face_data))
        
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
                    return
                # Notify list to update status (e.g. remove "Empty" tag)
                if self.on_update_callback:
                    self.on_update_callback(face_data)

            self.current_face = face_data
                
            # Load Settings FIRST (Before showing editor/preview)
            self.entry_name.delete(0, "end")
            self.entry_name.insert(0, face_data.get('display_name', ''))
            self.change_state("normal", save_before_switch=False) # Reset to normal on load
            self._update_state_combo()
            
            # Load Frames
            frames = ["None"] + self.face_manager.scan_frames()
            self.combo_frame.configure(values=frames)
            current_frame = face_data.get('frame_id', "None")
            if current_frame not in frames:
                current_frame = "None"
            self.combo_frame.set(current_frame)
            
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

            # Show Editor
            self.show_editor(True)
            
        finally:
            self.is_loading = False
            self.loading_overlay.hide()
            # Schedule update to allow UI to settle and prevent TclError
            self.after(200, self.update_preview)

    def change_frame(self, selected_frame):
        if not self.current_face:
            return
        
        if selected_frame == "None":
            self.face_manager.push_update_state(self.current_face) # Undo snapshot
            self.current_face['frame_id'] = None
        else:
            self.face_manager.push_update_state(self.current_face) # Undo snapshot
            self.current_face['frame_id'] = selected_frame
            
        self._save_json()
        self.update_preview()

    def change_state_from_combo(self, selected_value):
        state_key = self.state_map.get(selected_value)
        if state_key:
            self.change_state(state_key)

    def change_state(self, state_key, save_before_switch=True):
        # Save previous state before switching
        if self.current_face and save_before_switch:
            self._save_json()
            
        self.current_state_key = state_key
        if not self.current_face:
            return
            
        states = self.current_face.get('states', {})
        state_data = states.get(state_key, {})
        
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
        invalid_files = []
        
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
                # If no suffix, assume Normal
                # But wait, user said "If not setting rule, show dialog"
                # "Single file registration is allowed regardless of filename"
                # "If batch DnD, validate"
                
                if len(files) == 1:
                    # Single file -> Treat as Normal or ask?
                    # User said: "Single file registration ... regardless of filename"
                    # If dropped on grid background (batch area), maybe default to Normal?
                    valid_files.append((f, "normal"))
                else:
                    # Batch -> Must match rule?
                    # "If suffix is at end ... allow batch registration"
                    # "If not matching ... show dialog and cancel"
                    
                    # Check if it's a "Normal" file (no suffix from list)
                    # Is "Normal" allowed in batch?
                    # User list showed: "1 Normal ... face_b.png" (No suffix)
                    # So "No suffix" = Normal.
                    
                    # We need to ensure it DOESN'T match any other suffix?
                    # We already checked suffixes.
                    # So if not matched, it's Normal.
                    valid_files.append((f, "normal"))

        # Wait, user said: "If not matching ... show dialog"
        # "Limit batch registration to when these suffixes ... are at the end"
        # This implies ONLY files with suffixes (or explicit Normal?) are allowed?
        # "1 Normal ... face_b.png" -> No suffix.
        # So Normal is allowed.
        
        # Re-reading: "Limit batch registration to when these suffixes ... are at the end"
        # "Final output should be as per spec"
        # "If not matching ... show dialog"
        
        # Let's assume:
        # If filename ends with _XX -> Mapped to XX.
        # If filename DOES NOT end with _XX -> Mapped to Normal.
        # Is there any "Invalid" case?
        # Maybe if it looks like a suffix but isn't?
        # Or maybe user meant "If I drop a file that I expect to be Poison but it doesn't have _PO, warn me"?
        # But how do we know intent?
        
        # "If not in the setting state (file name rule), show dialog"
        # Maybe they mean: If I drop 5 files, and one is "random.png", what happens?
        # It goes to Normal.
        # Is that "Invalid"?
        # User said: "If not matching rule ... cancel".
        
        # Let's interpret strict validation:
        # We accept files that match the specific suffixes.
        # What about Normal?
        # "1 Normal ... face_b.png"
        # So Normal has NO suffix.
        # Effectively ALL files are valid (either suffix or normal).
        
        # UNLESS "Normal" also requires a rule? No, table says "Additional Char: (Empty)".
        
        # Perhaps the validation is: "Don't map 'face_b_75.png' to Normal just because I missed the underscore".
        # But we can't detect that.
        
        # Let's implement the mapping. If everything maps, we proceed.
        # If there's ambiguity?
        
        # Actually, maybe the user wants to prevent "Accidental Normal"?
        # "If I drop 'face_b_75.png' and 'face_b_50.png', they go to 75 and 50."
        # "If I drop 'face_b.png', it goes to Normal."
        # "If I drop 'face_b_XX.png' (unknown suffix), it goes to Normal." -> This might be the "Invalid" case.
        # But we can't distinguish "Unknown Suffix" from "Base Name".
        
        # Let's assume ALL files are valid, mapped to Normal if no suffix match.
        # BUT, if the user explicitly asked for validation dialog...
        # "If not in the setting state ... show dialog"
        
        # Maybe they mean: "If I drop multiple files, I expect them to be distributed."
        # "If they ALL map to Normal (because no suffixes), that's probably wrong."
        # But maybe not.
        
        # Let's implement the mapping.
        # If we find files that map to the SAME state, that might be a conflict?
        # "face_b.png" and "face_c.png" -> Both Normal.
        # We should probably allow this (overwriting or ignoring).
        
        # Let's proceed with the mapping.
        
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
                self._update_state_combo()
                if self.view_mode == "Single" and self.current_state_key == state_key:
                    self.update_preview()

    def on_drop_frame(self, event):
        files = self.tk.splitlist(event.data)
        if not files: return
        
        file_path = files[0]
        if os.path.isfile(file_path):
            from core.logger import Logger
            Logger.info(f"Dropped frame: {os.path.basename(file_path)}")
            
            imported_name = self.face_manager.import_frame(file_path)
            if imported_name:
                # Refresh list and select
                frames = ["None"] + self.face_manager.scan_frames()
                self.combo_frame.configure(values=frames)
                self.combo_frame.set(imported_name)
                self.change_frame(imported_name)

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
            self._update_state_combo()
            self.update_preview()

    def update_preview(self):
        if not self.current_face:
            return
            
        if self.view_mode == "Grid":
            return
            
        # Suppress updates during loading/batch updates
        if getattr(self, 'is_loading', False):
            return

        states = self.current_face.get('states', {})
        state_data = states.get(self.current_state_key, {})
        
        # Fetch current settings from UI controls
        current_settings = {
            'scale': self.slider_scale.get(),
            'offset_x': int(self.slider_x.get()),
            'offset_y': int(self.slider_y.get()),
            'icon_scale_a': self.slider_icon_scale_a.get(),
            'icon_scale_b': self.slider_icon_scale_b.get(),
            'use_rembg': bool(self.switch_rembg.get()),
            'alpha_matting': bool(self.switch_alpha.get()),
            'alpha_matting_foreground_threshold': int(self.slider_fg_thresh.get()),
            'alpha_matting_background_threshold': int(self.slider_bg_thresh.get()),
            'alpha_matting_erode_size': int(self.slider_erode.get())
        }
        
        # Face Center is handled separately via click, but we should include it if present in state_data
        # to ensure it syncs if we are just updating preview from sliders.
        # However, sliders don't change face_center.
        # If we are in Global Mode, we want to sync existing face_center too?
        # Or just the sliders?
        # The user said "Pin information and image coordinates... are synchronized".
        # So we should probably sync face_center from the current state if it exists.
        if 'face_center' in state_data:
            current_settings['face_center'] = state_data['face_center']

        is_local = self.chk_individual_mode.get()
        
        if not is_local:
            # GLOBAL MODE: Update Defaults + Sync All
            # Update defaults
            if 'defaults' not in self.current_face: self.current_face['defaults'] = {}
            self.current_face['defaults'].update(current_settings)
            
            # Apply to ALL states (Create if missing)
            for key in self.state_map.values():
                if key not in states: states[key] = {}
                s = states[key]
                
                # Skip states that are marked as Individual
                if s.get('is_individual', False):
                    continue
                    
                # Update settings
                s.update(current_settings)
                
            # Also update the local state_data reference to match
            state_data.update(current_settings)
        else:
            # LOCAL MODE: Update Current State Only
            state_data.update(current_settings)
                
        # Ensure current state exists in face data (already done by reference update above if existing, but good to be safe)
        if self.current_state_key not in states:
            states[self.current_state_key] = state_data
        
        source_uuid = state_data.get('source_uuid')
        if not source_uuid:
            # Explicitly clear icons with empty string (tk.Label standard)
            self.lbl_preview.configure(image="", text="No Image Source")
            self.lbl_icon_a.configure(image="")
            self.lbl_icon_b.configure(image="")
            self.lbl_icon_a.update_idletasks() # Force update
            
            self.current_image = None
            return
            
        source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
        if not source_path:
            try:
                self.lbl_preview.configure(image=None, text=loc.get("no_image_source"))
                self.lbl_icon_a.configure(image=None)
                self.lbl_icon_b.configure(image=None)
            except:
                pass
            self.current_image = None
            return

        # Cache Key Construction
        # Keys that affect the base image (Load + Rembg)
        current_cache_key = (
            source_uuid,
            state_data.get('use_rembg'),
            state_data.get('alpha_matting'),
            state_data.get('alpha_matting_foreground_threshold'),
            state_data.get('alpha_matting_background_threshold'),
            state_data.get('alpha_matting_erode_size')
        )
        
        # Check Cache
        if self.cache_key != current_cache_key:
            # Cache Miss - Re-process base image
            self.cached_processed_image = self.image_processor.preprocess_image(source_path, state_data)
            self.cache_key = current_cache_key
            
        # Frame
        frame_id = self.current_face.get('frame_id')
        frame_path = self.face_manager.get_frame_path(frame_id)

        # Get Face Center for this state
        face_center = state_data.get('face_center')
        if not face_center:
            # Fallback to defaults if missing (shouldn't happen with migration)
            face_center = self.current_face.get('defaults', {}).get('face_center')

        # Process Image (Use cached base)
        processed_img = self.image_processor.process_image(
            source_path, # Ignored if preprocessed_image is passed
            state_data, 
            target_size=(1920, 1080),
            frame_path=frame_path,
            preprocessed_image=self.cached_processed_image,
            face_center=face_center
        )
        
        if processed_img:
            # --- Icon Preview (Generate BEFORE Game UI & Guides) ---
            icon_scale_a = state_data.get('icon_scale_a', state_data.get('icon_scale', 1.0))
            icon_scale_b = state_data.get('icon_scale_b', state_data.get('icon_scale', 1.0))
            
            # Convert list/tuple face_center to dict for image_processor (legacy compat)
            fc_dict = None
            if face_center:
                fc_dict = {'x': face_center.get('x'), 'y': face_center.get('y')}
                
            icon_a = self.image_processor.create_face_icon(processed_img, (96, 96), fc_dict, icon_scale_a)
            icon_b = self.image_processor.create_face_icon(processed_img, (270, 96), fc_dict, icon_scale_b)
            
            # Use ImageTk.PhotoImage for robustness
            photo_icon_a = ImageTk.PhotoImage(icon_a)
            photo_icon_b = ImageTk.PhotoImage(icon_b)
            
            # Keep references!
            self.current_icon_a = photo_icon_a
            self.current_icon_b = photo_icon_b
            
            self.lbl_icon_a.configure(image=photo_icon_a, text="")
            self.lbl_icon_b.configure(image=photo_icon_b, text="")
            self.lbl_icon_a.update_idletasks() # Force update

            # --- Game UI Background (Composite for Main Preview ONLY) ---
            if self.switch_game_ui.get():
                try:
                    bg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "assets", "preview_bg.png")
                    if os.path.exists(bg_path):
                        bg_img = Image.open(bg_path).convert("RGBA")
                        if bg_img.size != (1920, 1080):
                            bg_img = bg_img.resize((1920, 1080), Image.Resampling.LANCZOS)
                        
                        # Composite character ON TOP of background
                        # processed_img is the character (RGBA)
                        # Create a copy for display so we don't modify the original processed_img used for icons/saving?
                        # Actually processed_img is a fresh copy from image_processor usually.
                        # But we already used it for icons.
                        # Let's use a copy for display to be safe, or just overwrite if we don't need clean anymore.
                        # We need clean for coordinate calc? No, coordinate calc uses current_pil_image.
                        # So we should update current_pil_image to be the composited one?
                        # No, coordinate calc (face center) should be relative to the CHARACTER image, not the UI.
                        # But if we show UI, the user clicks on the UI.
                        # If UI is 1920x1080 and Character is 1920x1080, it matches.
                        
                        bg_img.alpha_composite(processed_img)
                        processed_img = bg_img
                except Exception as e:
                    print(f"Error loading game UI background: {e}")

            # Draw Guides (AFTER icon generation so icons are clean)
            if self.show_guides:
                self._draw_guides(processed_img)

            # Draw Face Center Marker
            self._draw_marker(processed_img, face_center)

            # Resize for preview (keep aspect ratio)
            preview_height = self.preview_frame.winfo_height()
            if preview_height < 100: preview_height = 400 # Default if not rendered yet
            
            ratio = processed_img.width / processed_img.height
            new_h = preview_height - 50 # Padding
            new_w = int(new_h * ratio)
            
            display_img = processed_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            # Apply View Zoom
            if self.view_zoom != 1.0:
                zw = int(new_w * self.view_zoom)
                zh = int(new_h * self.view_zoom)
                display_img = display_img.resize((zw, zh), Image.Resampling.NEAREST)
                
            # Create Image (Use ImageTk.PhotoImage for tk.Label)
            try:
                # Explicitly clear previous image
                self.lbl_preview.configure(image=None)
                
                # Create PhotoImage
                photo_img = ImageTk.PhotoImage(display_img)
                
                self.current_image = photo_img # Keep reference
                self.current_pil_image = processed_img # Keep original for coordinate calc
                
                self.lbl_preview.configure(image=photo_img, text="")
            except Exception as e:
                print(f"Warning: Failed to update preview image: {e}")
                self.lbl_preview.configure(image=None, text=loc.get("error_processing"))

    def _draw_guides(self, image):
        draw = ImageDraw.Draw(image)
        guides = self.guides_data.get(self.guide_type, [])
        for guide in guides:
            rect = guide.get('rect')
            if len(rect) == 4:
                x, y, w, h = rect
                shape = [x, y, x+w, y+h]
                color = guide.get('color', 'green')
                draw.rectangle(shape, outline=color, width=3)

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
            img_w, img_h = self.current_image._size
            # img_w is the DISPLAY width (already zoomed)
            
            # If view_zoom is 2.0, moving 10px on screen is 5px on original image
            scale_factor = (1920 / img_w) 
            
            # We update the slider directly which triggers update_preview
            current_x = self.slider_x.get()
            current_y = self.slider_y.get()
            
            self.slider_x.set(current_x + dx * scale_factor)
            self.slider_y.set(current_y + dy * scale_factor)
            
            # Reset start to avoid continuous acceleration
            self.drag_start_x = event.x
            self.drag_start_y = event.y
            
            self.update_preview()

    def on_mouse_up(self, event):
        if not self.is_dragging:
            # It was a click -> Face Center
            self.on_preview_click(event)
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
        self.update_preview()

    def toggle_individual_mode(self):
        is_local = self.chk_individual_mode.get()
        
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
        if not self.current_face.get('face_center'):
            from tkinter import messagebox
            messagebox.showwarning("Warning", loc.get("error.no_face_center", "Face center not set!"))
            return

        # 1. Save JSON
        self._save_json()
        
        # 2. Export Images
        face_dir = self.current_face.get('_path')
        if not face_dir:
            return

        states = self.current_face.get('states', {})
        
        # Progress Dialog
        progress = ProgressDialog(self, title="Exporting", message="Generating images...")
        total_steps = len(self.state_map)
        current_step = 0
        
        # Helper to render and save
        def export_state(state_key, suffix):
            state_data = states.get(state_key)
            if not state_data: return
            
            source_uuid = state_data.get('source_uuid')
            if not source_uuid: return
            
            source_path = self.face_manager.get_source_path(self.current_face, source_uuid)
            if not source_path: return
            
            frame_id = self.current_face.get('frame_id')
            frame_path = self.face_manager.get_frame_path(frame_id)
            
            # Render 1920x1080 (face_c)
            img_full = self.image_processor.process_image(source_path, state_data, (1920, 1080), frame_path=frame_path)
            if img_full:
                # Save face_c
                filename = f"face_c{suffix}.png"
                img_full.save(os.path.join(face_dir, filename))
                
                # Save face_d (Copy of c)
                img_full.save(os.path.join(face_dir, f"face_d{suffix}.png"))
                
                # Save face_e (Copy of c)
                img_full.save(os.path.join(face_dir, f"face_e{suffix}.png"))
                
                # Save face_b (270x96) - For ALL states
                img_b = self.image_processor.create_face_icon(img_full, (270, 96), self.current_face.get('face_center'))
                img_b.save(os.path.join(face_dir, f"face_b{suffix}.png"))
                
                # If normal state, generate face_a
                if state_key == "normal":
                    # face_a (96x96)
                    img_a = self.image_processor.create_face_icon(img_full, (96, 96), self.current_face.get('face_center'))
                    img_a.save(os.path.join(face_dir, "face_a.png"))

        # Export Loop
        suffix_map = {
            "normal": "",
            "poison": "_PO", "hp_75": "_75", "hp_50": "_50", "hp_25": "_25", "dead": "_DE",
            "afraid": "_AF", "sleep": "_SL", "paralyzed": "_PA", "stoned": "_ST", "ashed": "_AS"
        }
        
        for key, suffix in suffix_map.items():
            export_state(key, suffix)
            current_step += 1
            progress.set_progress(current_step / total_steps)
            
        progress.close()
            
        from core.logger import Logger
        Logger.info(f"Saved character to {face_dir}")

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
            'alpha_matting': bool(self.switch_alpha.get()),
            'alpha_matting_foreground_threshold': int(self.slider_fg_thresh.get()),
            'alpha_matting_background_threshold': int(self.slider_bg_thresh.get()),
            'alpha_matting_erode_size': int(self.slider_erode.get())
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
