"""Fabrique d'embeds stylés et cohérents pour tout le bot.

Centraliser ici garantit une identité visuelle uniforme (couleurs, footer,
horodatage) sur toutes les réponses.
"""

from __future__ import annotations

import discord

# Palette
BRAND = 0xB57EDC   # violet « Asuna »
SUCCESS = 0x57F287
ERROR = 0xED4245
WARNING = 0xFEE75C
INFO = 0x5865F2
MOD = 0xE67E22

_FOOTER = "Asuna • Bot Discord"


def _base(title: str, description: str | None, color: int) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=_FOOTER)
    return embed


def brand(title: str, description: str | None = None) -> discord.Embed:
    return _base(title, description, BRAND)


def success(title: str, description: str | None = None) -> discord.Embed:
    return _base(f"✅ {title}", description, SUCCESS)


def error(title: str, description: str | None = None) -> discord.Embed:
    return _base(f"❌ {title}", description, ERROR)


def warning(title: str, description: str | None = None) -> discord.Embed:
    return _base(f"⚠️ {title}", description, WARNING)


def info(title: str, description: str | None = None) -> discord.Embed:
    return _base(f"ℹ️ {title}", description, INFO)


def mod(title: str, description: str | None = None) -> discord.Embed:
    """Embed dédié aux actions de modération (couleur orange)."""
    return _base(f"🛡️ {title}", description, MOD)
