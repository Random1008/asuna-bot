"""Rôles à réaction : associe un emoji sur un message à un rôle.

Quand un membre réagit, il reçoit le rôle ; quand il retire sa réaction, le
rôle est retiré. La configuration vit dans la table reaction_roles.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import checks, embeds


def _emoji_key(emoji: discord.PartialEmoji) -> str:
    """Clé stable pour un emoji (custom → '<:name:id>', unicode → le caractère)."""
    if emoji.id is not None:
        return f"<{'a' if emoji.animated else ''}:{emoji.name}:{emoji.id}>"
    return str(emoji.name)


class AutoRoles(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    reactionrole = app_commands.Group(
        name="reactionrole",
        description="Gestion des rôles à réaction",
        default_permissions=discord.Permissions(manage_roles=True),
        guild_only=True,
    )

    @reactionrole.command(name="add", description="Associe un emoji d'un message à un rôle.")
    @app_commands.describe(
        message_id="ID du message cible (clic droit → Copier l'identifiant)",
        emoji="L'emoji à utiliser",
        role="Le rôle à attribuer",
    )
    async def add(
        self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role
    ) -> None:
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=embeds.error("Rôle trop haut", "Ce rôle est au-dessus du mien, je ne pourrai pas l'attribuer."),
                ephemeral=True,
            )
            return
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error("ID invalide", "Donne un identifiant de message numérique."), ephemeral=True
            )
            return

        # Tente d'ajouter la réaction au message pour amorcer.
        try:
            msg = await interaction.channel.fetch_message(mid)
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            await interaction.response.send_message(
                embed=embeds.error("Échec", "Message introuvable dans ce salon, ou emoji invalide."), ephemeral=True
            )
            return

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO reaction_roles (guild_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?)",
            (interaction.guild.id, mid, emoji, role.id),
        )
        await interaction.response.send_message(
            embed=embeds.success("Rôle à réaction créé", f"{emoji} → {role.mention} sur le message `{mid}`."),
            ephemeral=True,
        )

    @reactionrole.command(name="remove", description="Supprime une association emoji → rôle.")
    async def remove(self, interaction: discord.Interaction, message_id: str, emoji: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error("ID invalide", "Donne un identifiant numérique."), ephemeral=True
            )
            return
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (interaction.guild.id, mid, emoji),
        )
        await interaction.response.send_message(
            embed=embeds.success("Supprimé", "Association retirée."), ephemeral=True
        )

    @reactionrole.command(name="list", description="Liste les rôles à réaction du serveur.")
    async def list_(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT message_id, emoji, role_id FROM reaction_roles WHERE guild_id = ?",
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Vide", "Aucun rôle à réaction configuré."), ephemeral=True
            )
            return
        lines = []
        for r in rows:
            role = interaction.guild.get_role(r["role_id"])
            lines.append(f"`{r['message_id']}` — {r['emoji']} → {role.mention if role else 'rôle supprimé'}")
        await interaction.response.send_message(
            embed=embeds.info(f"Rôles à réaction ({len(rows)})", "\n".join(lines)), ephemeral=True
        )

    # ── Application des réactions ───────────────────────────────────────────
    async def _role_for(self, guild_id: int, message_id: int, emoji: discord.PartialEmoji) -> int | None:
        row = await self.bot.db.fetchone(
            "SELECT role_id FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (guild_id, message_id, _emoji_key(emoji)),
        )
        return row["role_id"] if row else None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.member is None or payload.member.bot:
            return
        role_id = await self._role_for(payload.guild_id, payload.message_id, payload.emoji)
        if role_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(role_id) if guild else None
        if role:
            try:
                await payload.member.add_roles(role, reason="Rôle à réaction")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        role_id = await self._role_for(payload.guild_id, payload.message_id, payload.emoji)
        if role_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        role = guild.get_role(role_id)
        if member and role and not member.bot:
            try:
                await member.remove_roles(role, reason="Retrait de rôle à réaction")
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoRoles(bot))
