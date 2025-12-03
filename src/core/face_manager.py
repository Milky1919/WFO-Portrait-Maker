import os
import json
import shutil
import uuid
import glob
from typing import List, Dict, Optional

class FaceManager:
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.faces: List[Dict] = []
        self.ensure_base_path()

    def ensure_base_path(self):
        if not os.path.exists(self.base_path):
            try:
                os.makedirs(self.base_path)
            except OSError as e:
                print(f"Error creating base path {self.base_path}: {e}")

    def scan_faces(self) -> List[Dict]:
        """Scans the base path for face folders and loads their data."""
        self.faces = []
        if not os.path.exists(self.base_path):
            return []

        # Scan for face1 to face100 (or any folder starting with face)
        # The requirement says face1 ~ face100, but we can be flexible
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
            print(f"Error loading {json_path}: {e}")
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
            print("No free face slots available (limit 100).")
            return None

        new_dir_path = os.path.join(self.base_path, new_dir_name)
        os.makedirs(new_dir_path)
        
        # Create sources directory
        os.makedirs(os.path.join(new_dir_path, "sources"))

        # Initialize data
        new_data = {
            "version": "1.1",
            "display_name": display_name,
            "uuid": str(uuid.uuid4()),
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
            print(f"Error saving {json_path}: {e}")
            return False

    def delete_face(self, face_data: Dict) -> bool:
        """Deletes a face folder."""
        face_dir = face_data.get('_path')
        if not face_dir or not os.path.exists(face_dir):
            return False
            
        try:
            shutil.rmtree(face_dir)
            if face_data in self.faces:
                self.faces.remove(face_data)
            return True
        except Exception as e:
            print(f"Error deleting face {face_dir}: {e}")
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
            return new_uuid
        except Exception as e:
            print(f"Error importing image: {e}")
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
