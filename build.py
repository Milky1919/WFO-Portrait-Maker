import os
import sys
import subprocess
import shutil

def build():
    # Detect PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Base Command
    # --noconsole: No terminal window
    # --onefile: Single .exe file (optional, but requested "binary" usually implies this. However, --onedir is faster startup. Let's stick to onedir for now for speed and debugging, or onefile if distribution is key. User said "distribution". Onefile is cleaner for users.)
    # Let's use --onedir first as it's more robust with assets, then maybe --onefile if requested. 
    # Actually, for "distribution", a single exe is often preferred, but CustomTkinter/OnnxRuntime can be tricky.
    # Let's try --onedir for stability, and maybe zip it.
    # Wait, user asked for ".exe", usually implies single file.
    # But let's check standard PyInstaller usage with these libs.
    
    cmd = [
        "pyinstaller",
        "--noconsole",
        "--name", "WFO Portrait Maker",
        "--clean",
        "--noconfirm", # Overwrite output directory
        "--paths", "src", # Add src to search path
    ]
    
    # Entry Point
    cmd.append("main.py")

    # Data (Assets)
    # Format: src;dest (Windows)
    cmd.extend([
        "--add-data", "assets;assets"
    ])
    
    # Collect All (CustomTkinter, TkinterDnD, OnnxRuntime)
    # This automatically finds paths and adds binaries/data
    cmd.extend([
        "--collect-all", "customtkinter",
        "--collect-all", "tkinterdnd2",
        "--collect-all", "rembg",  # rembg might need hidden imports or data
        "--collect-all", "onnxruntime", # Critical for rembg
        "--collect-all", "PIL"
    ])
    
    # Hidden Imports (Sometimes needed for dynamic imports)
    cmd.extend([
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageTk",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.filedialog",
        "--hidden-import", "tkinter.messagebox"
    ])
    
    # Icon (if exists)
    if os.path.exists("assets/icon.ico"):
        cmd.extend(["--icon", "assets/icon.ico"])

    print("Running PyInstaller...")
    print(" ".join(cmd))
    
    subprocess.check_call(cmd)
    
    print("-" * 50)
    print("Build Complete!")
    print("Executable is located in 'dist/WFO Portrait Maker/WFO Portrait Maker.exe'")
    print("-" * 50)

if __name__ == "__main__":
    build()
