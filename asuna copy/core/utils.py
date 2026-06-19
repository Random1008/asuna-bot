"""Petits utilitaires partagés (parsing de durée, hiérarchie de rôles…)."""

from __future__ import annotations

import re
from datetime import timedelta

import discord

_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> timedelta | None:
    """Convertit une durée type « 10m », « 1h30m », « 2d » en timedelta.

    Retourne None si rien d'exploitable n'est trouvé.
    """
    total = 0
    for amount, unit in _DURATION_RE.findall(text or ""):
        total += int(amount) * _UNIT_SECONDS[unit.lower()]
    return timedelta(seconds=total) if total > 0 else None


def hierarchy_ok(
    moderator: discord.Member, target: discord.Member, me: discord.Member
) -> tuple[bool, str | None]:
    """Vérifie qu'une action de modération est légitime et possible.

    Contrôle : pas soi-même, pas le propriétaire, et respect de la hiérarchie
    des rôles pour le modérateur ET pour le bot.
    """
    if target == moderator:
        return False, "Tu ne peux pas faire ça sur toi-même."
    if target == target.guild.owner:
        return False, "Impossible : la cible est le propriétaire du serveur."
    if target.top_role >= me.top_role:
        return False, "Mon rôle est trop bas dans la hiérarchie pour agir sur ce membre."
    is_owner = moderator == moderator.guild.owner
    if not is_owner and target.top_role >= moderator.top_role:
        return False, "Tu ne peux pas viser un membre de rôle égal ou supérieur au tien."
    return True, None
