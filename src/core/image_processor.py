import threading
from PIL import Image, ImageOps
import io
from typing import Optional, Tuple, Dict
import concurrent.futures

from core.logger import Logger

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
                    Logger.error("rembg not installed.")
                    return None
                except Exception as e:
                    Logger.error(f"Error initializing rembg session: {e}")
                    return None
            return self._rembg_session

    def remove_background(self, image: Image.Image, params: Dict = None) -> Image.Image:
        """Removes background from the image using rembg."""
        session = self._get_session()
        if session:
            import rembg
            
            # Default params
            kwargs = {}
            if params:
                if params.get('alpha_matting', False):
                    kwargs['alpha_matting'] = True
                    kwargs['alpha_matting_foreground_threshold'] = int(params.get('alpha_matting_foreground_threshold', 240))
                    kwargs['alpha_matting_background_threshold'] = int(params.get('alpha_matting_background_threshold', 10))
                    kwargs['alpha_matting_erode_size'] = int(params.get('alpha_matting_erode_size', 10))
            
            return rembg.remove(image, session=session, **kwargs)
        return image

    def remove_background_async(self, image: Image.Image, callback):
        """Runs background removal in a separate thread."""
        def task():
            result = self.remove_background(image)
            callback(result)
        self._executor.submit(task)

    def preprocess_image(self, source_path: str, params: Dict) -> Optional[Image.Image]:
        """
        Loads and applies background removal (if needed). Returns the base image for further transforms.
        """
        if not source_path: return None
        
        try:
            img = Image.open(source_path).convert("RGBA")
        except Exception as e:
            Logger.error(f"Error opening image {source_path}: {e}")
            return None
            
        # Background Removal
        if params.get('use_rembg', False):
            img = self.remove_background(img, params)
            
        return img

    def process_image(self, 
                      source_path: str, 
                      params: Dict, 
                      target_size: Tuple[int, int] = (1920, 1080),
                      frame_path: Optional[str] = None,
                      preprocessed_image: Optional[Image.Image] = None,
                      face_center: Optional[Tuple[int, int]] = None) -> Optional[Image.Image]:
        """
        Processes an image with the given parameters and optional frame.
        If preprocessed_image is provided, source_path and rembg params are ignored.
        """
        
        if preprocessed_image:
            img = preprocessed_image.copy() # Work on copy
        else:
            if not source_path:
                return None
            img = self.preprocess_image(source_path, params)
            if not img: return None

        # 2. Scaling
        scale = params.get('scale', 1.0)
        if scale != 1.0:
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            
        # 3. Canvas Composition
        canvas = Image.new("RGBA", target_size, (0, 0, 0, 0))
        
        cx, cy = target_size[0] // 2, target_size[1] // 2
        ix, iy = img.width // 2, img.height // 2
        
        offset_x = params.get('offset_x', 0)
        offset_y = params.get('offset_y', 0)
        
        paste_x = cx - ix + offset_x
        paste_y = cy - iy + offset_y
        
        canvas.alpha_composite(img, (int(paste_x), int(paste_y)))
        

        
        return canvas

    def create_face_icon(self, image: Image.Image, size: Tuple[int, int], face_center: Optional[Dict] = None, icon_scale: float = 1.0) -> Image.Image:
        """Creates a face icon (face_a, face_b) from the processed image."""
        
        target_w, target_h = size
        
        # Determine center
        if face_center:
            cx, cy = face_center.get('x', image.width // 2), face_center.get('y', image.height // 2)
        else:
            cx, cy = image.width // 2, image.height // 2
            
        # Base height for a "Head" at Scale 1.0
        # This is a heuristic: we assume a standard head/face takes up about 300px height in the original 1080p image.
        BASE_HEIGHT = 300
        
        # Adjust for Icon Scale (Zoom)
        # Larger scale = Smaller crop (Zoom In)
        if icon_scale <= 0: icon_scale = 0.1
        crop_h = int(BASE_HEIGHT / icon_scale)
        
        # Calculate Width based on Target Aspect Ratio
        ratio = target_w / target_h
        crop_w = int(crop_h * ratio)
        
        # Calculate Box centered on cx, cy
        left = cx - (crop_w // 2)
        top = cy - (crop_h // 2)
        right = left + crop_w
        bottom = top + crop_h
        
        # Clamp / Shift to keep within bounds if possible?
        # If we just clamp, we distort the center.
        # If we shift, we keep the size but move the center.
        # Let's try to shift first, then clamp if still too big.
        
        img_w, img_h = image.size
        
        # Shift horizontally
        if left < 0:
            right += -left
            left = 0
        if right > img_w:
            left -= (right - img_w)
            right = img_w
            # If still out of bounds (image too narrow), clamp left
            if left < 0: left = 0
            
        # Shift vertically
        if top < 0:
            bottom += -top
            top = 0
        if bottom > img_h:
            top -= (bottom - img_h)
            bottom = img_h
            # If still out of bounds, clamp top
            if top < 0: top = 0
            
        # Crop
        crop = image.crop((int(left), int(top), int(right), int(bottom)))
        
        # Resize to target
        return crop.resize(size, Image.Resampling.LANCZOS)
