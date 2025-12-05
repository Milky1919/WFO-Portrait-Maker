import tkinter.font

_cached_font_family = None

def get_ui_font_family():
    """
    Returns the best available Japanese font family.
    Priority: Meiryo UI > Yu Gothic UI > MS UI Gothic > Arial
    """
    global _cached_font_family
    if _cached_font_family:
        return _cached_font_family
        
    available_fonts = set(tkinter.font.families())
    
    # Priority list
    priorities = ["Meiryo UI", "Yu Gothic UI", "MS UI Gothic", "Arial"]
    
    for font in priorities:
        if font in available_fonts:
            _cached_font_family = font
            return font
            
    # Fallback
    _cached_font_family = "Arial"
    return "Arial"
