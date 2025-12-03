import datetime

class Logger:
    _instance = None
    _listeners = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance

    @classmethod
    def add_listener(cls, callback):
        """Adds a callback function that receives log messages."""
        cls._listeners.append(callback)

    @classmethod
    def log(cls, message: str):
        """Logs a message with a timestamp."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        print(formatted_message) # Also print to console
        for listener in cls._listeners:
            listener(formatted_message)

    @classmethod
    def info(cls, message: str):
        cls.log(f"[INFO] {message}")

    @classmethod
    def error(cls, message: str):
        cls.log(f"[ERROR] {message}")

    @classmethod
    def warning(cls, message: str):
        cls.log(f"[WARN] {message}")
