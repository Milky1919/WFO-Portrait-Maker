import os
import requests
import threading
from core.logger import Logger

class RembgDownloader:
    MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
    
    @staticmethod
    def get_model_path():
        user_home = os.path.expanduser("~")
        return os.path.join(user_home, ".u2net", "u2net.onnx")

    @staticmethod
    def is_model_installed():
        return os.path.exists(RembgDownloader.get_model_path())

    def download_model(self, progress_callback, cancel_event, on_complete):
        """
        Downloads the model in a separate thread.
        progress_callback: function(float) -> None (0.0 to 1.0)
        cancel_event: threading.Event
        on_complete: function(bool) -> None (True if success, False if failed/cancelled)
        """
        thread = threading.Thread(target=self._download_worker, args=(progress_callback, cancel_event, on_complete))
        thread.start()

    def _download_worker(self, progress_callback, cancel_event, on_complete):
        model_path = self.get_model_path()
        temp_path = model_path + ".tmp"
        
        try:
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            
            Logger.info(f"Starting download from {self.MODEL_URL}")
            response = requests.get(self.MODEL_URL, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if cancel_event.is_set():
                        Logger.info("Download cancelled.")
                        f.close()
                        os.remove(temp_path)
                        on_complete(False)
                        return
                        
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress_callback(downloaded / total_size)
                            
            # Rename temp to final
            if os.path.exists(model_path):
                os.remove(model_path)
            os.rename(temp_path, model_path)
            
            Logger.info("Download completed.")
            on_complete(True)
            
        except Exception as e:
            Logger.error(f"Download failed: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            on_complete(False)
