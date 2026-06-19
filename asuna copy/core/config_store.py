"""Configuration *par serveur*, stockée dans la table guild_config.

Fournit un accès simple (get/set) avec un cache mémoire pour éviter de taper la
base à chaque message. Les clés modifiables sont whitelistées pour éviter toute
injection de nom de colonne.
"""

from __future__ import annotations

from core.database import Database

# Colonnes que l'on autorise à modifier via set() (sécurité anti-injection).
ALLOWED_KEYS = {
    "prefix",
    "log_channel_id",
    "mute_role_id",
    "verify_role_id",
    "autorole_id",
    "welcome_channel_id",
    "welcome_message",
    "leave_message",
    "log_category_id",
    "log_messages_channel_id",
    "log_members_channel_id",
    "log_mod_channel_id",
    "log_system_channel_id",
    "currency_symbol",
    "currency_name",
    "daily_amount",
    "xp_enabled",
    "levelup_channel_id",
    "levelup_announce",
    "ticket_category_id",
    "ticket_staff_role_id",
    "ticket_log_channel_id",
    "ticket_counter",
    "antinuke_enabled",
    "antinuke_threshold",
    "antinuke_window",
    "antinuke_action",
    "welcome_image",
    "leave_image",
    "ticket_panel_title",
    "ticket_panel_message",
    "ticket_panel_image",
    "anti_spam",
    "anti_links",
    "anti_invites",
    "max_mentions",
    "antiraid_enabled",
    "antiraid_threshold",
    "antiraid_window",
}


class ConfigStore:
    """Lecture/écriture de la config d'un serveur, avec cache en mémoire."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[int, dict] = {}

    async def get(self, guild_id: int) -> dict:
        """Retourne la config du serveur sous forme de dict (crée la ligne au besoin)."""
        if guild_id in self._cache:
            return self._cache[guild_id]
        # Garantit l'existence de la ligne avec les valeurs par défaut du schéma.
        await self.db.execute(
            "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await self.db.fetchone(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        )
        data = dict(row) if row is not None else {"guild_id": guild_id}
        self._cache[guild_id] = data
        return data

    async def set(self, guild_id: int, key: str, value) -> None:
        """Modifie une clé de config et invalide le cache."""
        if key not in ALLOWED_KEYS:
            raise ValueError(f"Clé de configuration inconnue : {key}")
        await self.get(guild_id)  # garantit la ligne
        await self.db.execute(
            f"UPDATE guild_config SET {key} = ? WHERE guild_id = ?", (value, guild_id)
        )
        self._cache.pop(guild_id, None)  # forcera un rechargement frais
