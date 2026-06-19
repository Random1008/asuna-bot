"""Décorateurs de permissions réutilisables pour les slash commands.

On s'appuie sur les permissions Discord natives (vérifiées côté serveur par
l'API), ce qui est plus robuste qu'une liste de rôles maison.
"""

from __future__ import annotations

from discord import app_commands


def is_admin():
    """Réservé aux membres ayant la permission « Administrateur »."""
    return app_commands.checks.has_permissions(administrator=True)


def is_mod():
    """Réservé aux modérateurs (permission « Gérer les messages »)."""
    return app_commands.checks.has_permissions(manage_messages=True)


def can_kick():
    return app_commands.checks.has_permissions(kick_members=True)


def can_ban():
    return app_commands.checks.has_permissions(ban_members=True)


def can_moderate_members():
    """Pour timeout/mute (permission « Modérer les membres »)."""
    return app_commands.checks.has_permissions(moderate_members=True)


def can_manage_roles():
    return app_commands.checks.has_permissions(manage_roles=True)
