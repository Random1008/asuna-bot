"""Chargement et validation de la configuration globale (depuis .env).

La config *par serveur* (préfixe, salons, rôles…) vit en base de données
et se gère via core/config_store.py — ici on ne gère que le global.
"""

import os

from dotenv import load_dotenv

# Charge les variables du fichier .env dans l'environnement du process.
load_dotenv()


def _int_env(name: str, default: int = 0) -> int:
    """Lit une variable d'env entière de façon tolérante (vide → défaut)."""
    raw = os.getenv(name, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class Config:
    """Configuration globale du bot, lue une seule fois au démarrage."""

    TOKEN: str | None = os.getenv("DISCORD_TOKEN")
    DEFAULT_PREFIX: str = os.getenv("DEFAULT_PREFIX", "!")
    OWNER_ID: int = _int_env("OWNER_ID")
    # 0 → synchro globale ; sinon synchro instantanée sur ce serveur de dev.
    DEV_GUILD_ID: int | None = _int_env("DEV_GUILD_ID") or None
    DB_PATH: str = os.getenv("DB_PATH", "data/asuna.db")

    # Dashboard web (lecture seule)
    DASHBOARD_ENABLED: bool = os.getenv("DASHBOARD_ENABLED", "false").lower() in ("1", "true", "yes", "on")
    DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    DASHBOARD_PORT: int = _int_env("DASHBOARD_PORT", 8080)
    # URL publique affichée par /dashboard (sinon construite depuis host:port)
    DASHBOARD_URL: str = os.getenv("DASHBOARD_URL", "")

    @classmethod
    def validate(cls) -> None:
        """Vérifie le minimum vital avant de lancer le bot."""
        if not cls.TOKEN:
            raise RuntimeError(
                "DISCORD_TOKEN manquant. Copie .env.example en .env et renseigne ton token."
            )
