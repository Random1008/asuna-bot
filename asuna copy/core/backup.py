"""Sauvegarde et restauration de la structure d'un serveur.

Capture rôles, catégories, salons et leurs permissions dans un dict JSON-sérialisable.
La restauration est **non destructive** : elle ne crée que ce qui manque (par nom),
sans rien supprimer.
"""

from __future__ import annotations

import discord


def _overwrites(channel) -> dict:
    """Sérialise les permissions d'un salon : {nom_cible: {allow, deny}}."""
    out = {}
    for target, perm in channel.overwrites.items():
        allow, deny = perm.pair()
        if isinstance(target, discord.Role):
            name = "@everyone" if target.is_default() else f"role:{target.name}"
        else:
            continue  # on ignore les overrides par membre
        out[name] = {"allow": allow.value, "deny": deny.value}
    return out


def snapshot_guild(guild: discord.Guild) -> dict:
    """Construit un instantané JSON-sérialisable de la structure du serveur."""
    roles = []
    for r in sorted(guild.roles, key=lambda r: r.position):
        if r.is_default() or r.managed:
            continue
        roles.append({
            "name": r.name, "color": r.color.value, "permissions": r.permissions.value,
            "hoist": r.hoist, "mentionable": r.mentionable,
        })
    categories = [{"name": c.name, "position": c.position, "overwrites": _overwrites(c)}
                  for c in sorted(guild.categories, key=lambda c: c.position)]
    channels = []
    for c in guild.channels:
        if isinstance(c, discord.CategoryChannel):
            continue
        channels.append({
            "name": c.name, "type": ("voice" if isinstance(c, discord.VoiceChannel) else "text"),
            "category": c.category.name if c.category else None,
            "position": c.position, "topic": getattr(c, "topic", None),
            "overwrites": _overwrites(c),
        })
    return {"roles": roles, "categories": categories, "channels": channels}


def summarize(data: dict) -> dict:
    return {"roles": len(data.get("roles", [])), "categories": len(data.get("categories", [])),
            "channels": len(data.get("channels", []))}


async def restore_guild(guild: discord.Guild, data: dict) -> dict:
    """Recrée (par nom) les rôles/catégories/salons manquants. Non destructif."""
    created = {"roles": 0, "categories": 0, "channels": 0}

    existing_roles = {r.name for r in guild.roles}
    for rd in data.get("roles", []):
        if rd["name"] in existing_roles:
            continue
        await guild.create_role(
            name=rd["name"], permissions=discord.Permissions(rd["permissions"]),
            colour=discord.Colour(rd["color"]), hoist=rd["hoist"], mentionable=rd["mentionable"],
            reason="Restauration de backup")
        created["roles"] += 1

    role_by_name = {r.name: r for r in guild.roles}

    def build_overwrites(ow: dict) -> dict:
        res = {}
        for name, pair in ow.items():
            if name == "@everyone":
                target = guild.default_role
            elif name.startswith("role:"):
                target = role_by_name.get(name[5:])
            else:
                target = None
            if target is not None:
                res[target] = discord.PermissionOverwrite.from_pair(
                    discord.Permissions(pair["allow"]), discord.Permissions(pair["deny"]))
        return res

    cat_by_name = {c.name: c for c in guild.categories}
    for cd in data.get("categories", []):
        if cd["name"] in cat_by_name:
            continue
        cat = await guild.create_category(
            cd["name"], overwrites=build_overwrites(cd.get("overwrites", {})), reason="Restauration de backup")
        cat_by_name[cd["name"]] = cat
        created["categories"] += 1

    existing_channels = {c.name for c in guild.channels if not isinstance(c, discord.CategoryChannel)}
    for chd in data.get("channels", []):
        if chd["name"] in existing_channels:
            continue
        category = cat_by_name.get(chd["category"]) if chd["category"] else None
        overwrites = build_overwrites(chd.get("overwrites", {}))
        if chd["type"] == "voice":
            await guild.create_voice_channel(chd["name"], category=category, overwrites=overwrites, reason="Restauration de backup")
        else:
            await guild.create_text_channel(
                chd["name"], category=category, topic=chd.get("topic"), overwrites=overwrites, reason="Restauration de backup")
        created["channels"] += 1

    return created
