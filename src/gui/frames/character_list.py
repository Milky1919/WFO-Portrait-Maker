import customtkinter as ctk
from core.face_manager import FaceManager
import os
from PIL import Image
import tkinter
from core.localization import loc
from core.logger import Logger

class CharacterListFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, face_manager: FaceManager, **kwargs):
        super().__init__(master, label_text=loc.get("characters"), **kwargs)
        self.face_manager = face_manager
        self.on_select_callback = None
        self.cards = []
        self.selected_faces = []
        
        # Drag state
        self.drag_source_face = None
        self.drag_start_x = 0
        self.drag_start_y = 0

        self.refresh()

    def set_on_select(self, callback):
        self.on_select_callback = callback

    def refresh(self):
        # Clear existing
        for widget in self.winfo_children():
            widget.destroy()
        self.cards = []
        self.selected_faces = [] 
        
        faces = self.face_manager.scan_faces()
        for face in faces:
            card = CharacterCard(self, face)
            card.pack(fill="x", pady=5, padx=5)
            # Bind click and drag
            self._bind_events(card, face)
            self.cards.append(card)
            
        # Add "New" button at bottom -> Removed as per request (Slot management)
        # add_btn = ctk.CTkButton(self, text=loc.get("new_character"), command=self.add_character)
        # add_btn.pack(pady=10)
        
        # Register D&D (External files)
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.on_drop)
        except Exception as e:
            print(f"D&D setup failed: {e}")

    def _bind_events(self, widget, face):
        # Click (Selection)
        widget.bind("<Button-1>", lambda e, f=face: self.on_card_click(f, e))
        # Context Menu
        widget.bind("<Button-3>", lambda e, f=face: self.show_context_menu(e, f))
        # Drag Start
        widget.bind("<ButtonPress-1>", lambda e, f=face: self.on_drag_start(e, f), add="+")
        # Drag End
        widget.bind("<ButtonRelease-1>", lambda e: self.on_drag_end(e), add="+")
        
        for child in widget.winfo_children():
            self._bind_events(child, face)

    def on_drop(self, event):
        files = self.tk.splitlist(event.data)
        Logger.info(f"Dropped files: {files}")
        
        count = 0
        for file_path in files:
            if os.path.isfile(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ['.png', '.jpg', '.jpeg', '.webp', '.bmp']:
                    name = os.path.splitext(os.path.basename(file_path))[0]
                    new_face = self.face_manager.create_new_face(display_name=name)
                    if new_face:
                        uuid = self.face_manager.import_source_image(new_face, file_path)
                        if uuid:
                            new_face['states']['normal']['source_uuid'] = uuid
                            self.face_manager.save_project_data(new_face['_path'], new_face)
                            count += 1
        
        if count > 0:
            self.refresh()
            Logger.info(f"Imported {count} characters via D&D.")

    def on_card_click(self, face, event=None):
        # Handle Multi-selection
        is_ctrl = False
        is_shift = False
        if event:
            is_ctrl = (event.state & 0x0004) != 0 # Control key
            is_shift = (event.state & 0x0001) != 0 # Shift key
            
        if is_ctrl:
            if face in self.selected_faces:
                self.selected_faces.remove(face)
            else:
                self.selected_faces.append(face)
        elif is_shift and self.selected_faces:
            all_faces = [c.face_data for c in self.cards]
            try:
                last_face = self.selected_faces[-1]
                start_idx = all_faces.index(last_face)
                end_idx = all_faces.index(face)
                
                step = 1 if start_idx <= end_idx else -1
                for i in range(start_idx, end_idx + step, step):
                    f = all_faces[i]
                    if f not in self.selected_faces:
                        self.selected_faces.append(f)
            except ValueError:
                self.selected_faces = [face]
        else:
            self.selected_faces = [face]

        # Update Visuals
        for card in self.cards:
            card.set_selected(card.face_data in self.selected_faces)
            
        # Notify callback
        if self.on_select_callback:
            target = face if face in self.selected_faces else (self.selected_faces[-1] if self.selected_faces else None)
            self.on_select_callback(target)

    # --- Smart Merge Logic ---
    def on_drag_start(self, event, face):
        self.drag_source_face = face
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root

    def on_drag_end(self, event):
        if not self.drag_source_face:
            return
            
        # Check if moved enough to consider drag
        dx = abs(event.x_root - self.drag_start_x)
        dy = abs(event.y_root - self.drag_start_y)
        if dx < 5 and dy < 5:
            self.drag_source_face = None
            return

        # Find target card
        x, y = event.x_root, event.y_root
        target_widget = self.winfo_containing(x, y)
        
        # Traverse up to find CharacterCard
        target_card = None
        current = target_widget
        while current:
            if isinstance(current, CharacterCard):
                target_card = current
                break
            current = current.master
            if current == self: break # Don't go past frame
            
        if target_card and target_card.face_data != self.drag_source_face:
            self.merge_faces(self.drag_source_face, target_card.face_data)
        
        self.drag_source_face = None

    def merge_faces(self, source, target):
        from tkinter import messagebox
        if messagebox.askyesno(loc.get("merge"), f"Merge '{source.get('display_name')}' into '{target.get('display_name')}'?"):
            # Copy states from source to target
            source_states = source.get('states', {})
            target_states = target.get('states', {})
            
            merged_count = 0
            for key, val in source_states.items():
                # If target doesn't have this state or we overwrite?
                # Requirement: "Integrate as state difference"
                # Let's overwrite/add
                if key != "normal" or "normal" not in target_states:
                     target_states[key] = val
                     merged_count += 1
            
            target['states'] = target_states
            self.face_manager.save_project_data(target['_path'], target)
            Logger.info(f"Merged {merged_count} states from {source.get('display_name')} to {target.get('display_name')}")
            
            # Delete source? Usually yes in merge.
            # But maybe user wants to keep it?
            # Let's ask or just delete. "Merge" implies consuming.
            # I'll delete source for "Smart Merge".
            self.face_manager.delete_face(source)
            self.refresh()

    def show_context_menu(self, event, face):
        if face not in self.selected_faces:
            self.on_card_click(face)
        
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label=loc.get("delete"), command=self.delete_selected)
        menu.post(event.x_root, event.y_root)

    def delete_selected(self):
        if not self.selected_faces:
            return
            
        from tkinter import messagebox
        count = len(self.selected_faces)
        if messagebox.askyesno(loc.get("delete"), f"Delete {count} characters?"):
            success_count = 0
            for face in list(self.selected_faces):
                if self.face_manager.delete_face(face):
                    success_count += 1
            
            Logger.info(f"Deleted {success_count} characters.")
            self.refresh()
            if self.on_select_callback:
                self.on_select_callback(None)

    def delete_character(self, face):
        if face in self.selected_faces:
            self.delete_selected()
        else:
            from tkinter import messagebox
            if messagebox.askyesno(loc.get("delete"), loc.get("confirm_delete")):
                if self.face_manager.delete_face(face):
                    self.refresh()
                    if self.on_select_callback:
                        self.on_select_callback(None)

    def add_character(self):
        # Deprecated: We now initialize on edit
        pass

    def refresh_card(self, face_data):
        self.refresh()

class CharacterCard(ctk.CTkFrame):
    def __init__(self, master, face_data):
        super().__init__(master)
        self.face_data = face_data
        self.default_fg_color = self._fg_color
        
        face_dir = face_data.get('_path')
        thumb_path = os.path.join(face_dir, "face_a.png")
        
        self.thumb_image = None
        if os.path.exists(thumb_path):
            try:
                with Image.open(thumb_path) as img:
                    pil_img = img.copy()
                self.thumb_image = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(48, 48))
            except:
                pass
        
        self.lbl_thumb = ctk.CTkLabel(self, text="No Img" if not self.thumb_image else "", image=self.thumb_image)
        self.lbl_thumb.pack(side="left", padx=5, pady=5)
        
        status = face_data.get('_status', 'managed')
        
        display_name = face_data.get('display_name', 'Unknown')
        if status == 'empty':
            display_name = "(Empty)"
        elif status == 'unmanaged':
            display_name = f"{display_name} (Unmanaged)"
            
        self.lbl_name = ctk.CTkLabel(self, text=display_name, font=("Arial", 12, "bold" if status == 'managed' else "normal"))
        
        if status == 'empty':
            self.lbl_name.configure(text_color="gray")
        elif status == 'unmanaged':
            self.lbl_name.configure(text_color="orange")
            
        self.lbl_name.pack(side="left", padx=10)
        
        dirname = face_data.get('_dirname', '')
        self.lbl_id = ctk.CTkLabel(self, text=dirname, font=("Arial", 10))
        self.lbl_id.pack(side="right", padx=5)

    def set_selected(self, selected: bool):
        if selected:
            self.configure(fg_color=("gray75", "gray25"), border_width=2, border_color="blue")
        else:
            self.configure(fg_color=self.default_fg_color, border_width=0)
