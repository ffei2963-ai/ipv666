import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_DIR = os.environ.get("LOG_DIR", "/var/log/app")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_RETENTION = int(os.environ.get("LOG_RETENTION_DAYS", "7"))


def setup_logger(name: str = "ipv666") -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, f"{name}.log"),
        maxBytes=50 * 1024 * 1024,
        backupCount=LOG_RETENTION,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger()
