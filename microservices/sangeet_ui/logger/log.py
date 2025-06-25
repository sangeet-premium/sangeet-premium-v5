import logging
import os
from datetime import datetime
import sys
import threading
from colorama import init, Fore, Style

# Initialize colorama
init(autoreset=True)

# --- Process-safe global storage for loggers and log file paths ---
# This dictionary will hold the configured logger for each name,
# ensuring we don't reconfigure it in the same process.
_loggers = {}
# This dictionary will store the master log file path for a given run.
_log_file_paths = {}
# A lock to make the setup process thread-safe.
_setup_lock = threading.Lock()


class ColoredFormatter(logging.Formatter):
    """A custom log formatter that adds color to log levels for console output."""
    LOG_LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.MAGENTA,
    }

    def format(self, record):
        color = self.LOG_LEVEL_COLORS.get(record.levelno)
        record.levelname = f"{color}{record.levelname}{Style.RESET_ALL}"
        return super().format(record)

def setup_logger(script_name: str = "app"):
    """
    Sets up a Gunicorn-aware, process-safe logger.

    All Gunicorn workers for a single master process will log to the same file.
    It creates one log file per application startup, not per worker.

    Args:
        script_name (str): The base name for the logger and log directory.

    Returns:
        logging.Logger: A configured logger instance.
    """
    with _setup_lock:
        # If a logger for this name is already configured in this process, return it.
        if script_name in _loggers:
            return _loggers[script_name]

        # --- 1. Smart Log File Naming (Gunicorn Aware) ---
        logs_dir = 'logs'
        script_log_dir = os.path.join(logs_dir, script_name)
        os.makedirs(script_log_dir, exist_ok=True)

        # Gunicorn's master process PID is stored in PPID for workers.
        # We use this to generate a consistent filename across all workers of one run.
        parent_pid = os.getppid()
        log_session_id = f"master_pid_{parent_pid}"

        if log_session_id not in _log_file_paths:
            # This block runs only once per master session.
            now = datetime.now()
            day_word = now.strftime('%A')
            day_num = now.strftime('%d')
            month_word = now.strftime('%B')
            year_num = now.strftime('%Y')
            time_hms = now.strftime('%H-%M-%S')

            log_file_name = f"{script_name}_{day_word}_{day_num}_{month_word}_{year_num}_{time_hms}.log"
            _log_file_paths[log_session_id] = os.path.join(script_log_dir, log_file_name)

            # --- 2. Manage Latest Log File Flag (only once per session) ---
            latest_log_path = os.path.join(script_log_dir, '[latest].log')
            if os.path.lexists(latest_log_path): # Use lexists for symlinks
                os.remove(latest_log_path)
            
            # Use a symbolic link for efficiency
            os.symlink(os.path.basename(_log_file_paths[log_session_id]), latest_log_path)
            
        log_file_path = _log_file_paths[log_session_id]

        # --- 3. Configure Logger ---
        logger = logging.getLogger(script_name)
        logger.setLevel(logging.DEBUG)  # Capture all levels of logs
        
        # Prevent adding handlers multiple times if the logger already has them
        if logger.handlers:
            _loggers[script_name] = logger
            return logger

        logger.propagate = False # Prevent logs from propagating to the root logger

        # --- 4. Create Handlers ---
        # Console Handler with color
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = ColoredFormatter(
            '%(asctime)s PID:%(process)d - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)

        # File Handler for detailed black box logging
        # The 'delay=True' argument defers file opening until the first log message is emitted.
        file_handler = logging.FileHandler(log_file_path, mode='a', delay=True)
        file_formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d - PID:%(process)d - %(levelname)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)

        # --- 5. Add Handlers to Logger ---
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

        # Store the configured logger in our global dict
        _loggers[script_name] = logger
        
        return logger