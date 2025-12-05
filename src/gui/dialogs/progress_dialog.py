import customtkinter as ctk

class ProgressDialog(ctk.CTkToplevel):
    def __init__(self, master, title="Processing...", message="Please wait..."):
        super().__init__(master)
        self.title(title)
        self.geometry("300x150")
        self.resizable(False, False)
        
        # Center on parent
        self.transient(master)
        self.grab_set()
        self.lift()
        self.focus_force()
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        self.lbl_message = ctk.CTkLabel(self, text=message)
        self.lbl_message.pack(pady=20)
        
        self.progressbar = ctk.CTkProgressBar(self)
        self.progressbar.pack(pady=10, padx=20, fill="x")
        self.progressbar.set(0)
        
        self.protocol("WM_DELETE_WINDOW", self.disable_close)
        
    def disable_close(self):
        pass

    def set_progress(self, value):
        self.progressbar.set(value)
        self.update_idletasks()

    def close(self):
        self.grab_release()
        self.destroy()
