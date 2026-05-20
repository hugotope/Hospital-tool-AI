"""
Hospital AI — Configuración centralizada de logging
====================================================
Uso:
    from logging_config import setup_logging, get_logger

    setup_logging()  # una vez al arrancar (app.py)
    log = get_logger("pipeline")
    log.info("mensaje")

Loggers hijos de ``hospital_ai``:
    pipeline, training, notifications, health

Salida:
    - stdout (docker logs hospital-ai-backend)
    - logs/hospital-ai.log (rotativo, volumen Docker hospital_logs)
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = ROOT_DIR / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "hospital-ai.log"

_CONFIGURED = False

_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def setup_logging(
    *,
    level: str | None = None,
    log_dir: Path | str | None = None,
    log_file: Path | str | None = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Inicializa logging global del proyecto (idempotente)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    env_level = (level or os.environ.get("HOSPITAL_LOG_LEVEL", "INFO")).upper()
    numeric_level = _LEVEL_MAP.get(env_level, logging.INFO)

    log_directory = Path(log_dir or os.environ.get("HOSPITAL_LOG_DIR", DEFAULT_LOG_DIR))
    log_path = Path(log_file or os.environ.get("HOSPITAL_LOG_FILE", log_directory / "hospital-ai.log"))
    log_directory.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("hospital_ai")
    root.setLevel(numeric_level)
    root.handlers.clear()
    root.propagate = False

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(numeric_level)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    try:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning("No se pudo abrir log rotativo %s: %s", log_path, exc)

    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    root.info("Logging inicializado | nivel=%s | archivo=%s", env_level, log_path)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """
    Devuelve un logger hijo de ``hospital_ai``.

    ``name`` puede ser ``pipeline``, ``training``, etc.
    """
    if not name:
        return logging.getLogger("hospital_ai")
    if name.startswith("hospital_ai."):
        return logging.getLogger(name)
    return logging.getLogger(f"hospital_ai.{name}")
