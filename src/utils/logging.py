import logging
import sys

from src.config import get, load_settings, resolve_path

_configured = False


def configure_logging(level: str | None = None) -> None:
    global _configured
    settings = load_settings()
    root = logging.getLogger()
    if not _configured:
        formatter = logging.Formatter(
            get(settings, "logging.format"), datefmt=get(settings, "logging.datefmt")
        )
        log_dir = resolve_path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers = [
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_dir / "pipeline.log"),
        ]
        for handler in handlers:
            handler.setFormatter(formatter)
            root.addHandler(handler)
        _configured = True
    # modules take a logger at import time, so an explicit level has to win over that first call
    root.setLevel(level or get(settings, "logging.level"))


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
