import customtkinter as ctk
from core.face_manager import FaceManager
import os
from PIL import Image

import tkinter

from core.localization import loc

class CharacterListFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, face_manager: FaceManager, **kwargs):
        super().__init__(master, label_text=loc.get("characters"), **kwargs)
        self.face_manager = face_manager
        self.on_select_callback = None
        self.cards = []
        
        self.refresh()

    def set_on_select(self, callback):
        self.on_select_callback = callback

    def refresh(self):
        # Clear existing
        for widget in self.winfo_children():
            widget.destroy()
        self.cards = []
        
        faces = self.face_manager.scan_faces()
        for face in faces:
            card = CharacterCard(self, face)
            card.pack(fill="x", pady=5, padx=5)
            # Bind click to the frame and its children
            self._bind_click(card, face)
            self.cards.append(card)
            
        # Add "New" button at bottom
        add_btn = ctk.CTkButton(self, text=loc.get("new_character"), command=self.add_character)
        add_btn.pack(pady=10)

    def _bind_click(self, widget, face):
        widget.bind("<Button-1>", lambda e, f=face: self.on_card_click(f))
        widget.bind("<Button-3>", lambda e, f=face: self.show_context_menu(e, f))
        for child in widget.winfo_children():
            self._bind_click(child, face)

    def show_context_menu(self, event, face):
        # Select the card first
        self.on_card_click(face)
        
        menu = tkinter.Menu(self, tearoff=0)
        menu.add_command(label=loc.get("delete"), command=lambda: self.delete_character(face))
        menu.post(event.x_root, event.y_root)

    def delete_character(self, face):
        from tkinter import messagebox
        if messagebox.askyesno(loc.get("delete"), loc.get("confirm_delete")):
            if self.face_manager.delete_face(face):
                self.refresh()
                # If we deleted the currently selected face, clear selection in editor
                # Ideally we callback with None
                if self.on_select_callback:
                    self.on_select_callback(None)

    def add_character(self):
        new_face = self.face_manager.create_new_face()
        if new_face:
            self.refresh()
            if self.on_select_callback:
                self.on_select_callback(new_face)

    def on_card_click(self, face):
        # Update selection visual
        for card in self.cards:
            card.set_selected(False)
        
        # Find the card that was clicked (this is a bit inefficient but safe)
        for card in self.cards:
            if card.face_data == face:
                card.set_selected(True)
                break

        if self.on_select_callback:
            self.on_select_callback(face)
    
    def refresh_card(self, face_data):
        # Find card and update (or just full refresh for simplicity)
        self.refresh()

class CharacterCard(ctk.CTkFrame):
    def __init__(self, master, face_data):
        super().__init__(master)
        self.face_data = face_data
        self.default_fg_color = self._fg_color
        
        # Try to load thumbnail (face_a.png)
        face_dir = face_data.get('_path')
        thumb_path = os.path.join(face_dir, "face_a.png")
        
        self.thumb_image = None
        if os.path.exists(thumb_path):
            try:
                pil_img = Image.open(thumb_path)
                self.thumb_image = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(48, 48))
            except:
                pass
        
        # Thumbnail Label
        self.lbl_thumb = ctk.CTkLabel(self, text="No Img" if not self.thumb_image else "", image=self.thumb_image)
        self.lbl_thumb.pack(side="left", padx=5, pady=5)
        
        # Name
        display_name = face_data.get('display_name', 'Unknown')
        self.lbl_name = ctk.CTkLabel(self, text=display_name, font=("Arial", 12, "bold"))
        self.lbl_name.pack(side="left", padx=10)
        
        # Folder Name (ID)
        dirname = face_data.get('_dirname', '')
        self.lbl_id = ctk.CTkLabel(self, text=dirname, font=("Arial", 10))
        self.lbl_id.pack(side="right", padx=5)

    def set_selected(self, selected: bool):
        if selected:
            self.configure(fg_color=("gray75", "gray25"), border_width=2, border_color="blue")
        else:
            self.configure(fg_color=self.default_fg_color, border_width=0)
