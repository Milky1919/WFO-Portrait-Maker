import os
import re

class SteamFinder:
    @staticmethod
    def find_game_executable(game_folder_name: str, preferred_exe_name: str = None) -> str:
        """
        Searches for a game executable within Steam library folders.
        
        Args:
            game_folder_name: The name of the game folder in steamapps/common (e.g., "Wizardry The Five Ordeals")
            preferred_exe_name: The preferred executable name (e.g., "WizardryFoV2.exe"). 
                                If not found or None, returns the first .exe found.
                                
        Returns:
            Path to the executable if found, else None.
        """
        
        # 1. Find Steam Installation
        # Common locations
        steam_paths = [
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
        ]
        
        steam_root = None
        for path in steam_paths:
            if os.path.exists(path):
                steam_root = path
                break
        
        if not steam_root:
            return None
            
        # 2. Parse libraryfolders.vdf
        library_folders = [steam_root] # Default library
        vdf_path = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
        
        if os.path.exists(vdf_path):
            try:
                with open(vdf_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Simple regex to find paths. VDF format is "path" "C:\\..."
                    # Look for "path"		"..."
                    matches = re.findall(r'"path"\s+"(.+?)"', content)
                    for match in matches:
                        # VDF paths usually have double backslashes escaped
                        clean_path = match.replace("\\\\", "\\")
                        if clean_path not in library_folders:
                            library_folders.append(clean_path)
            except Exception as e:
                print(f"Error parsing libraryfolders.vdf: {e}")
        
        # 3. Search for game folder in each library
        for lib in library_folders:
            game_dir = os.path.join(lib, "steamapps", "common", game_folder_name)
            if os.path.exists(game_dir):
                # Found game directory!
                
                # Check for preferred exe
                if preferred_exe_name:
                    exe_path = os.path.join(game_dir, preferred_exe_name)
                    if os.path.exists(exe_path):
                        return exe_path
                
                # If not found or no preference, search for any .exe
                # Exclude unins000.exe, UnityCrashHandler.exe etc if possible, but user said "thought to be executable"
                # Let's just list all .exe and pick the largest one? Or just the first one that looks like a game?
                # Usually the game exe is in the root of game_dir.
                
                candidates = []
                for file in os.listdir(game_dir):
                    if file.lower().endswith(".exe"):
                        candidates.append(file)
                
                if not candidates:
                    return None
                    
                # Heuristic: Pick preferred if in candidates (already checked), else pick largest?
                # Or just return the one that matches the folder name somewhat?
                # For WFO, it's WizardryFO.exe or WizardryFoV2.exe.
                
                # Let's try to match "Wizardry"
                for cand in candidates:
                    if "wizardry" in cand.lower():
                        return os.path.join(game_dir, cand)
                        
                # Fallback: Return the first one
                return os.path.join(game_dir, candidates[0])
                
        return None
