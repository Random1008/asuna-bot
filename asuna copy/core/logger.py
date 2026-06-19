"""Configuration des logs développeur (console + fichier avec rotation)."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(name: str = "asuna", log_dir: str = "logs") -> logging.Logger:
    """Crée (une seule fois) un logger qui écrit en console et dans logs/asuna.log."""
    logger = logging.getLogger(name)
    if logger.handlers:  # déjà configuré → on réutilise
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    # Fichier tournant (5 Mo × 3)
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "asuna.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
