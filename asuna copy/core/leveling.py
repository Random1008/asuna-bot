"""Maths des niveaux (fonctions pures, faciles à tester).

Modèle progressif type « MEE6 » : chaque niveau coûte de plus en plus d'XP.
On stocke l'XP *totale* en base et on en déduit le niveau.
"""

from __future__ import annotations


def xp_to_next(level: int) -> int:
    """XP nécessaire pour passer de `level` à `level + 1`."""
    return 5 * (level ** 2) + 50 * level + 100


def level_from_xp(total_xp: int) -> tuple[int, int, int]:
    """Décompose une XP totale en (niveau, xp_dans_le_niveau, xp_requise_pour_le_prochain)."""
    level = 0
    remaining = total_xp
    while remaining >= xp_to_next(level):
        remaining -= xp_to_next(level)
        level += 1
    return level, remaining, xp_to_next(level)


def progress_bar(current: int, needed: int, length: int = 12) -> str:
    """Petite barre de progression en blocs unicode."""
    if needed <= 0:
        return "▰" * length
    filled = max(0, min(length, round(length * current / needed)))
    return "▰" * filled + "▱" * (length - filled)
