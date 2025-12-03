import threading
from PIL import Image, ImageOps
import io
from typing import Optional, Tuple, Dict
import concurrent.futures

class ImageProcessor:
    def __init__(self):
        self._rembg_session = None
        self._session_lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def _get_session(self):
        """Lazy loads the rembg session."""
        with self._session_lock:
            if self._rembg_session is None:
                try:
                    import rembg
                    self._rembg_session = rembg.new_session()
                except ImportError:
                    print("rembg not installed.")
                    return None
                except Exception as e:
                    print(f"Error initializing rembg session: {e}")
                    return None
            return self._rembg_session

    def remove_background(self, image: Image.Image) -> Image.Image:
        """Removes background from the image using rembg."""
        session = self._get_session()
        if session:
            import rembg
            return rembg.remove(image, session=session)
        return image

    def remove_background_async(self, image: Image.Image, callback):
        """Runs background removal in a separate thread."""
        def task():
            result = self.remove_background(image)
            callback(result)
        self._executor.submit(task)

    def process_image(self, 
                      source_path: str, 
                      params: Dict, 
                      target_size: Tuple[int, int] = (1920, 1080)) -> Optional[Image.Image]:
        """
        Processes an image with the given parameters.
        params: {
            'scale': float,
            'offset_x': int,
            'offset_y': int,
            'use_rembg': bool
        }
        """
        if not source_path:
            return None

        try:
            img = Image.open(source_path).convert("RGBA")
        except Exception as e:
            print(f"Error opening image {source_path}: {e}")
            return None

        # 1. Background Removal (if requested)
        if params.get('use_rembg', False):
            # Note: This is synchronous here. For UI responsiveness, 
            # the UI should call remove_background_async separately 
            # and cache the result, or this method should be run in a thread.
            # For export, synchronous is fine.
            img = self.remove_background(img)

        # 2. Scaling
        scale = params.get('scale', 1.0)
        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # 3. Canvas Composition
        # Create a blank canvas of target size
        canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))
        
        # Calculate position
        # Default center of canvas
        cx, cy = target_size[0] // 2, target_size[1] // 2
        
        # Image center
        ix, iy = img.width // 2, img.height // 2
        
        # Apply offsets
        offset_x = params.get('offset_x', 0)
        offset_y = params.get('offset_y', 0)
        
        # Paste position (top-left)
        paste_x = cx - ix + offset_x
        paste_y = cy - iy + offset_y
        
        canvas.alpha_composite(img, (int(paste_x), int(paste_y)))
        
        return canvas

    def create_face_icon(self, image: Image.Image, size: Tuple[int, int]) -> Image.Image:
        """Creates a face icon (face_a, face_b) from the processed image."""
        # For icons, we might want to crop around the center or resize.
        # Requirement says: "face_a (96x96)", "face_b (270x96)"
        # Usually this is a crop of the face area.
        # For now, we'll just resize/crop the center.
        
        # Simple center crop and resize strategy
        img_ratio = image.width / image.height
        target_ratio = size[0] / size[1]
        
        if img_ratio > target_ratio:
            # Image is wider, crop width
            new_width = int(image.height * target_ratio)
            left = (image.width - new_width) // 2
            img = image.crop((left, 0, left + new_width, image.height))
        else:
            # Image is taller, crop height
            new_height = int(image.width / target_ratio)
            top = (image.height - new_height) // 2
            img = image.crop((0, top, image.width, top + new_height))
            
        return img.resize(size, Image.Resampling.LANCZOS)
