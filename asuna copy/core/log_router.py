"""Routage des logs vers le bon salon, par type d'événement.

Les salons sont retrouvés par **ID** (stockés en config) : renommer un salon
n'a donc aucun impact. Si un salon dédié n'est pas défini, on retombe sur le
salon de logs général (`log_channel_id`).
"""

from __future__ import annotations

import discord

from core import embeds

# Type d'événement → colonne de config contenant l'ID du salon dédié.
_KIND_COLUMN = {
    "messages": "log_messages_channel_id",  # suppressions / éditions
    "members": "log_members_channel_id",    # arrivées / départs
    "mod": "log_mod_channel_id",            # actions de modération / automod
    "system": "log_system_channel_id",      # incidents du bot (#asuna-bot)
}


async def get_log_channel(bot, guild: discord.Guild, kind: str) -> discord.TextChannel | None:
    """Retourne le salon de log adapté au `kind`, ou None s'il n'existe pas/plus."""
    cfg = await bot.config.get(guild.id)
    column = _KIND_COLUMN.get(kind)
    channel_id = cfg.get(column) if column else None
    if not channel_id:
        channel_id = cfg.get("log_channel_id")  # repli sur le salon général
    channel = guild.get_channel(channel_id) if channel_id else None
    return channel if isinstance(channel, discord.TextChannel) else None


async def send_log(bot, guild: discord.Guild, kind: str, embed: discord.Embed) -> None:
    """Envoie un embed dans le salon de log du type donné (silencieux si absent)."""
    channel = await get_log_channel(bot, guild, kind)
    if channel is None:
        return
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


async def report_problem(bot, guild: discord.Guild, title: str, description: str) -> None:
    """Signale un incident du bot dans le salon système (#asuna-bot)."""
    await send_log(bot, guild, "system", embeds.error(title, description))
