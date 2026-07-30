import os
import logging
from datetime import datetime

class Logger:
    ERROR = "ERROR"
    WARNING = "WARNING"
    SUCCESS = "SUCCESS"
    INFO = "INFO"

    COLORS = {
        ERROR: "\033[91m",   # Red
        WARNING: "\033[93m", # Yellow
        SUCCESS: "\033[92m", # Green
        INFO: "\033[94m",    # Blue
        "RESET": "\033[0m"
    }

    def __init__(self, name, root_folder, todayDate):
        self.name = name
        self.root_folder = root_folder
        self.todayDate = todayDate

        # Ensure logs folder exists
        self.log_folder = os.path.join(root_folder, "logs")
        os.makedirs(self.log_folder, exist_ok=True)

        self.logs_dir = os.path.join(self.log_folder, todayDate)
        os.makedirs(self.logs_dir, exist_ok=True)

        # File paths
        self.error_log = os.path.join(self.logs_dir, f"{name}_error_{todayDate}.log")
        self.warning_log = os.path.join(self.logs_dir, f"{name}_warning_{todayDate}.log")
        self.main_log = os.path.join(self.logs_dir, f"{name}_main_{todayDate}.log")

        # Create loggers with individual handlers
        self.error_logger = self._create_logger("error_logger", self.error_log)
        self.warning_logger = self._create_logger("warning_logger", self.warning_log)
        self.main_logger = self._create_logger("main_logger", self.main_log)

        print("ℹ️ Created logfiles:", {
            "error": self.error_log,
            "warning": self.warning_log,
            "main": self.main_log
        })

    def _create_logger(self, logger_name, file_path):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:  # prevent duplicate handlers
            handler = logging.FileHandler(file_path, mode="a", encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def log(self, message, level):
        color = self.COLORS.get(level, "")
        reset = self.COLORS["RESET"]

        if level == self.ERROR:
            self.error_logger.info(f"❌ {message}")
            print(f"{color}❌ {message}{reset}")

        elif level == self.WARNING:
            self.warning_logger.info(f"⚠️ {message}")
            print(f"{color}⚠️ {message}{reset}")

        elif level == self.SUCCESS:
            self.main_logger.info(f"✅ {message}")
            print(f"{color}✅ {message}{reset}")

        elif level == self.INFO:
            self.main_logger.info(f"ℹ️ {message}")
            print(f"{color}ℹ️ {message}{reset}")

    @property
    def error_log_file(self):
        return self.error_log

    @property
    def warning_log_file(self):
        return self.warning_log

    @property
    def main_log_file(self):
        return self.main_log


# ======================
# Example usage
# ======================
if __name__ == "__main__":
    today = datetime.now().strftime("%Y%m%d")
    logger_man = Logger("Taiwan", r"D:\Mans_Group\Taiwan", today)

    logger_man.log("This is an error message", logger_man.ERROR)
    logger_man.log("This is a warning message", logger_man.WARNING)
    logger_man.log("This is a success message", logger_man.SUCCESS)
    logger_man.log("This is an info message", logger_man.INFO)
