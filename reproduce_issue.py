import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "agent.log"

def test_logger():
    if LOG_FILE.exists():
        os.remove(LOG_FILE)
        print(f"Deleted {LOG_FILE}")
    
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Directory {LOG_DIR} exists: {LOG_DIR.exists()}")

    try:
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding="utf-8",
        )
        print("Successfully created RotatingFileHandler")
    except Exception as e:
        print(f"Failed to create RotatingFileHandler: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_logger()
