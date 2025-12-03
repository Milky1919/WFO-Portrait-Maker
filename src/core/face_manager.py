import os
import json
import shutil
import uuid
import glob
import datetime
from typing import List, Dict, Optional
from core.logger import Logger

class FaceManager:
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.faces: List[Dict] = []
        self.undo_stack = [] # List of (action_type, data)
        self.trash_path = os.path.join(base_path, "_trash")
        if not os.path.exists(self.trash_path):
            try:
                os.makedirs(self.trash_path)
            except OSError as e:
                Logger.error(f"Error creating trash path {self.trash_path}: {e}")

        self.ensure_base_path()
        self.scan_faces()

    def ensure_base_path(self):
        if not os.path.exists(self.base_path):
            try:
                os.makedirs(self.base_path)
            except OSError as e:
                Logger.error(f"Error creating base path {self.base_path}: {e}")

    def scan_faces(self) -> List[Dict]:
        """Scans the base path for face folders and loads their data."""
        self.faces = []
        if not os.path.exists(self.base_path):
            return []

        # Scan for face1 to face100 (or any folder starting with face)
        face_dirs = glob.glob(os.path.join(self.base_path, "face*"))
        
        for face_dir in face_dirs:
            if not os.path.isdir(face_dir):
                continue
                
            data = self.load_project_data(face_dir)
            if data:
                # Add directory path to data for internal use
                data['_path'] = face_dir
                data['_dirname'] = os.path.basename(face_dir)
                self.faces.append(data)
        
        return self.faces

    def load_project_data(self, face_dir: str) -> Optional[Dict]:
        """Loads project_data.json from a face directory."""
        json_path = os.path.join(face_dir, "project_data.json")
        if not os.path.exists(json_path):
            return None
        
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            Logger.error(f"Error loading {json_path}: {e}")
            return None

    def create_new_face(self, display_name: str = "New Character") -> Optional[Dict]:
        """Creates a new face folder and initializes project_data.json."""
        # Find a free folder name (face1, face2, ...)
        existing_dirs = {os.path.basename(d) for d in glob.glob(os.path.join(self.base_path, "face*"))}
        new_dir_name = None
        for i in range(1, 101):
            name = f"face{i}"
            if name not in existing_dirs:
                new_dir_name = name
                break
        
        if not new_dir_name:
            Logger.warning("No free face slots available (limit 100).")
            return None

        new_dir_path = os.path.join(self.base_path, new_dir_name)
        try:
            os.makedirs(new_dir_path)
            # Create sources directory
            os.makedirs(os.path.join(new_dir_path, "sources"))
        except OSError as e:
            Logger.error(f"Error creating directory {new_dir_path}: {e}")
            return None

        # Initialize data
        new_data = {
            "version": "1.1",
            "display_name": display_name,
            "uuid": str(uuid.uuid4()),
            "created_at": datetime.datetime.now().isoformat(),
            "face_center": {"x": 0, "y": 0}, # Default center
            "frame_id": None,
            "states": {
                "normal": {
                    "suffix": "",
                    "source_uuid": None,
                    "scale": 1.0,
                    "offset_x": 0,
                    "offset_y": 0,
                    "use_rembg": False
                }
            }
        }
        
        if self.save_project_data(new_dir_path, new_data):
            new_data['_path'] = new_dir_path
            new_data['_dirname'] = new_dir_name
            self.faces.append(new_data)
            Logger.info(f"Created new character: {display_name} ({new_dir_name})")
            return new_data
        return None

    def save_project_data(self, face_dir: str, data: Dict) -> bool:
        """Saves project_data.json with backup."""
        json_path = os.path.join(face_dir, "project_data.json")
        bak_path = os.path.join(face_dir, "project_data.json.bak")
        
        # Remove internal keys before saving
        save_data = {k: v for k, v in data.items() if not k.startswith('_')}

        try:
            # Create backup if exists
            if os.path.exists(json_path):
                shutil.copy2(json_path, bak_path)
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            Logger.error(f"Error saving {json_path}: {e}")
            return False

    def delete_face(self, face_data: Dict) -> bool:
        """Deletes a face folder (Moves to trash)."""
        face_dir = face_data.get('_path')
        if not face_dir or not os.path.exists(face_dir):
            return False
            
        try:
            # Move to trash
            dirname = os.path.basename(face_dir)
            trash_dest = os.path.join(self.trash_path, f"{dirname}_{uuid.uuid4()}")
            shutil.move(face_dir, trash_dest)
            
            if face_data in self.faces:
                self.faces.remove(face_data)
            
            # Push undo action
            self.undo_stack.append({
                'type': 'delete',
                'face_data': face_data,
                'trash_path': trash_dest,
                'original_path': face_dir
            })
            
            Logger.info(f"Deleted character (moved to trash): {face_data.get('display_name')}")
            return True
        except Exception as e:
            Logger.error(f"Error deleting face {face_dir}: {e}")
            return False

    def undo(self) -> bool:
        """Undoes the last action."""
        if not self.undo_stack:
            Logger.info("Nothing to undo.")
            return False
            
        action = self.undo_stack.pop()
        action_type = action.get('type')
        
        if action_type == 'delete':
            # Restore from trash
            trash_path = action.get('trash_path')
            original_path = action.get('original_path')
            face_data = action.get('face_data')
            
            if os.path.exists(trash_path):
                try:
                    # Ensure original path is free (it should be)
                    if os.path.exists(original_path):
                        # Conflict? Maybe rename?
                        # For now assume it's free or we overwrite
                        pass
                        
                    shutil.move(trash_path, original_path)
                    self.faces.append(face_data)
                    # Re-sort faces?
                    Logger.info(f"Undid delete: {face_data.get('display_name')}")
                    return True
                except Exception as e:
                    Logger.error(f"Undo failed: {e}")
                    return False
        
        return False

    def import_source_image(self, face_data: Dict, source_path: str) -> Optional[str]:
        """Imports an image into the sources folder and returns its new UUID."""
        if not os.path.exists(source_path):
            return None
            
        face_dir = face_data.get('_path')
        if not face_dir:
            return None
            
        sources_dir = os.path.join(face_dir, "sources")
        if not os.path.exists(sources_dir):
            os.makedirs(sources_dir)
            
        new_uuid = str(uuid.uuid4())
        ext = os.path.splitext(source_path)[1]
        dest_path = os.path.join(sources_dir, new_uuid + ext)
        
        try:
            shutil.copy2(source_path, dest_path)
            Logger.info(f"Imported image: {os.path.basename(source_path)}")
            return new_uuid
        except Exception as e:
            Logger.error(f"Error importing image: {e}")
            return None

    def get_source_path(self, face_data: Dict, source_uuid: str) -> Optional[str]:
        """Resolves the absolute path of a source image by UUID."""
        face_dir = face_data.get('_path')
        if not face_dir:
            return None
            
        sources_dir = os.path.join(face_dir, "sources")
        # We don't know the extension, so we search
        pattern = os.path.join(sources_dir, f"{source_uuid}.*")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
        return None

    def scan_frames(self) -> List[str]:
        """Scans assets/frames for frame images."""
        frames_dir = os.path.join(self.base_path, "assets", "frames")
        if not os.path.exists(frames_dir):
            return []
            
        # Supported extensions
        exts = ['*.png', '*.jpg', '*.webp']
        frames = []
        for ext in exts:
            frames.extend([os.path.basename(f) for f in glob.glob(os.path.join(frames_dir, ext))])
        return sorted(frames)

    def get_frame_path(self, frame_id: str) -> Optional[str]:
        """Resolves absolute path for a frame ID."""
        if not frame_id:
            return None
        return os.path.join(self.base_path, "assets", "frames", frame_id)

    def import_frame(self, file_path: str) -> Optional[str]:
        """Imports a frame image into assets/frames."""
        frames_dir = os.path.join(self.base_path, "assets", "frames")
        if not os.path.exists(frames_dir):
            os.makedirs(frames_dir)
            
        filename = os.path.basename(file_path)
        dest_path = os.path.join(frames_dir, filename)
        
        try:
            shutil.copy2(file_path, dest_path)
            Logger.info(f"Imported frame: {filename}")
            return filename
        except Exception as e:
            Logger.error(f"Error importing frame {filename}: {e}")
            return None
