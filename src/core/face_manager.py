import os
import json
import shutil
import uuid
import glob
import datetime
import threading
from typing import List, Dict, Optional
from core.logger import Logger

class FaceManager:
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.faces: List[Dict] = []
        self.undo_stack = [] # List of (action_type, data)
        self.redo_stack = [] # List of (action_type, data)
        self.on_history_change = None # Callback function
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
        """Scans the base path for face folders (face1 to face100). Auto-creates if missing."""
        self.faces = []
        if not os.path.exists(self.base_path):
            return []

        # Scan for face1 to face100
        for i in range(1, 101):
            dirname = f"face{i}"
            face_dir = os.path.join(self.base_path, dirname)
            
            # Auto-create if missing
            if not os.path.exists(face_dir):
                try:
                    os.makedirs(face_dir)
                    # Also create sources dir? Maybe wait until used.
                except OSError as e:
                    Logger.error(f"Error creating face directory {face_dir}: {e}")
                    continue
                
            data = self.load_project_data(face_dir)
            if data:
                # Managed
                data['_path'] = face_dir
                data['_dirname'] = dirname
                data['_status'] = "managed"
                self.faces.append(data)
            else:
                # Check for existing images (Unmanaged)
                # We look for standard game files: face_a.png, face_b.png, etc.
                has_images = False
                
                # Case-insensitive check for face_a.png
                try:
                    files = os.listdir(face_dir)
                    for f in files:
                        if f.lower() == "face_a.png":
                            has_images = True
                            break
                except OSError:
                    pass
                
                # thumb_path = os.path.join(face_dir, "face_a.png")
                # if os.path.exists(thumb_path):
                #     has_images = True
                
                status = "unmanaged" if has_images else "empty"
                
                # Create placeholder object
                transient_data = {
                    "display_name": f"Face {i}",
                    "_path": face_dir,
                    "_dirname": dirname,
                    "_status": status,
                    "face_center": None,
                    "states": {}
                }
                self.faces.append(transient_data)
        
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

    def initialize_face(self, face_data: Dict) -> Optional[Dict]:
        """Initializes project_data.json for a transient face slot."""
        face_dir = face_data.get('_path')
        if not face_dir:
            return None
            
        # Ensure sources dir exists
        sources_dir = os.path.join(face_dir, "sources")
        if not os.path.exists(sources_dir):
            try:
                os.makedirs(sources_dir)
            except OSError as e:
                Logger.error(f"Error creating sources directory {sources_dir}: {e}")
                return None

        # Initialize data
        new_data = {
            "version": "1.1",
            "display_name": face_data.get("display_name", "New Character"),
            "uuid": str(uuid.uuid4()),
            "created_at": datetime.datetime.now().isoformat(),
            "face_center": None,
            "created_at": datetime.datetime.now().isoformat(),
            "face_center": None,
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
        
        if self.save_project_data(face_dir, new_data):
            # Merge new data into face_data (which is a reference to the object in self.faces)
            face_data.update(new_data)
            face_data['_status'] = "managed"
            Logger.info(f"Initialized character: {new_data['display_name']} ({face_data['_dirname']})")
            return face_data
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

    def push_update_state(self, face_data: Dict):
        """Pushes the current state of a face to the undo stack before modification."""
        import copy
        self.undo_stack.append({
            'type': 'update',
            'face_data': copy.deepcopy(face_data),
            'path': face_data.get('_path')
        })
        self.redo_stack.clear() # Clear redo stack on new action
        if self.on_history_change: self.on_history_change()

    @property
    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def undo(self) -> Optional[Dict]:
        """Undoes the last action. Returns the restored face data if applicable."""
        if not self.undo_stack:
            Logger.info("Nothing to undo.")
            return None
            
        action = self.undo_stack.pop()
        action_type = action.get('type')
        
        if action_type == 'update':
            # Restore previous state
            prev_data = action.get('face_data')
            path = action.get('path')
            
            # Push CURRENT state to Redo Stack before restoring
            # We need to find the current state of this face in memory
            current_face = None
            for face in self.faces:
                if face.get('_path') == path:
                    current_face = face
                    break
            
            if current_face:
                import copy
                self.redo_stack.append({
                    'type': 'update',
                    'face_data': copy.deepcopy(current_face),
                    'path': path
                })

            if path and os.path.exists(path):
                # Async Save
                threading.Thread(target=self.save_project_data, args=(path, prev_data), daemon=True).start()
                # Update in-memory reference
                if current_face:
                    current_face.update(prev_data)
                    if self.on_history_change: self.on_history_change()
                    return current_face
                        
        elif action_type == 'delete':
            # Restore from trash
            trash_path = action.get('trash_path')
            original_path = action.get('original_path')
            face_data = action.get('face_data')
            
            if os.path.exists(trash_path) and not os.path.exists(original_path):
                try:
                    shutil.move(trash_path, original_path)
                    self.faces.append(face_data)
                    # Sort faces?
                    self.faces.sort(key=lambda x: x.get('_dirname', ''))
                    Logger.info(f"Restored character: {face_data.get('display_name')}")
                    
                    # Push to Redo (Delete again)
                    self.redo_stack.append({
                        'type': 'delete',
                        'face_data': face_data,
                        'trash_path': trash_path, # Reuse same trash path? No, it's gone.
                        # Actually, if we redo a delete, we need to move it back to trash.
                        # But the old trash folder is empty/gone now because we moved it back.
                        # So we need to generate a new trash path or just use logic.
                        'original_path': original_path
                    })
                    
                    return face_data # Return dict to refresh list
                except Exception as e:
                    Logger.error(f"Error restoring face: {e}")
        
        if self.on_history_change: self.on_history_change()
        return None

    def redo(self) -> Optional[Dict]:
        """Redoes the last undone action."""
        if not self.redo_stack:
            Logger.info("Nothing to redo.")
            return None
            
        action = self.redo_stack.pop()
        action_type = action.get('type')
        
        if action_type == 'update':
            # Restore "Future" state
            next_data = action.get('face_data')
            path = action.get('path')
            
            # Push CURRENT (Old) state to Undo Stack
            current_face = None
            for face in self.faces:
                if face.get('_path') == path:
                    current_face = face
                    break
            
            if current_face:
                import copy
                self.undo_stack.append({
                    'type': 'update',
                    'face_data': copy.deepcopy(current_face),
                    'path': path
                })
            
            if path and os.path.exists(path):
                # Async Save
                threading.Thread(target=self.save_project_data, args=(path, next_data), daemon=True).start()
                if current_face:
                    current_face.update(next_data)
                    if self.on_history_change: self.on_history_change()
                    return current_face

        elif action_type == 'delete':
            # Redo Delete
            face_data = action.get('face_data')
            # Call delete_face but don't push to undo stack inside it?
            # Or manually do it.
            # delete_face pushes to undo stack.
            # So if we call delete_face, it will push to undo stack, which is what we want!
            # But we popped from redo stack.
            # So:
            if self.delete_face(face_data):
                if self.on_history_change: self.on_history_change()
                return True # Bool for list refresh

        return None

    def copy_face_data(self, source_face: Dict, target_face: Dict) -> bool:
        """Copies content from source_face to target_face, overwriting target."""
        source_path = source_face.get('_path')
        target_path = target_face.get('_path')
        
        if not source_path or not target_path:
            return False
            
        try:
            # 1. Push Undo for Target
            self.push_update_state(target_face)
            
            # 2. Copy Files (Images & Sources)
            # We need to clear target directory of images/sources first?
            # Or just overwrite? Overwrite is safer/easier.
            # But we should probably clean up old sources if they are not used?
            # For simplicity, let's just copy over.
            
            # Copy 'sources' directory
            src_sources = os.path.join(source_path, "sources")
            dst_sources = os.path.join(target_path, "sources")
            
            if os.path.exists(src_sources):
                if os.path.exists(dst_sources):
                    shutil.rmtree(dst_sources)
                shutil.copytree(src_sources, dst_sources)
            
            # Copy generated images (face_*.png)
            for file in os.listdir(source_path):
                if file.lower().endswith('.png') and file.startswith('face_'):
                    shutil.copy2(os.path.join(source_path, file), os.path.join(target_path, file))
            
            # 3. Update Data
            # We want to copy everything EXCEPT _path, _dirname, _status
            # And maybe generate new UUID?
            
            # Deep copy source data
            import copy
            new_data = copy.deepcopy(source_face)
            
            # Restore target's structural keys
            new_data['_path'] = target_face['_path']
            new_data['_dirname'] = target_face['_dirname']
            new_data['_status'] = 'managed' # It becomes managed
            new_data['uuid'] = str(uuid.uuid4()) # New UUID
            
            # Save to target
            if self.save_project_data(target_path, new_data):
                # Update in-memory target object
                target_face.clear()
                target_face.update(new_data)
                Logger.info(f"Copied {source_face.get('display_name')} to {target_face.get('display_name')}")
                return True
                
        except Exception as e:
            Logger.error(f"Error copying face: {e}")
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


    def get_frame_path(self, frame_id: str) -> Optional[str]:
        """Resolves the absolute path of a frame image by ID."""
        if not frame_id:
            return None
            
        # Assuming frames are stored in assets/frames or similar?
        # Or maybe relative to base_path?
        # For now, let's assume assets/frames relative to app root.
        # But FaceManager doesn't know app root easily unless passed.
        # Let's assume it's passed or we can deduce it.
        # Actually, let's just return None for now if we don't support frames yet,
        # OR check if there is a known location.
        
        # If frame_id is an absolute path, return it
        if os.path.isabs(frame_id) and os.path.exists(frame_id):
            return frame_id
            
        return None
