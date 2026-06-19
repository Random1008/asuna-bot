"""Logs d'événements : messages supprimés/édités, arrivées et départs.

Tout est envoyé dans le salon de logs configuré via !config logchannel. Gère
aussi les messages de bienvenue / départ si configurés.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from core import embeds, log_router


class Logs(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Messages ────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        embed = embeds.info("🗑️ Message supprimé")
        embed.add_field(name="Auteur", value=message.author.mention)
        embed.add_field(name="Salon", value=message.channel.mention)
        embed.add_field(name="Contenu", value=(message.content or "*(aucun texte)*")[:1024], inline=False)
        await log_router.send_log(self.bot, message.guild, "messages", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        embed = embeds.info("✏️ Message édité")
        embed.add_field(name="Auteur", value=before.author.mention)
        embed.add_field(name="Salon", value=before.channel.mention)
        embed.add_field(name="Avant", value=(before.content or "—")[:1024], inline=False)
        embed.add_field(name="Après", value=(after.content or "—")[:1024], inline=False)
        await log_router.send_log(self.bot, before.guild, "messages", embed)

    # ── Arrivées / départs ──────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        cfg = await self.bot.config.get(member.guild.id)

        # Rôle automatique à l'arrivée (si configuré).
        autorole_id = cfg.get("autorole_id")
        if autorole_id:
            role = member.guild.get_role(autorole_id)
            if role:
                try:
                    await member.add_roles(role, reason="Rôle automatique à l'arrivée")
                except discord.HTTPException:
                    pass

        # Message de bienvenue (si configuré).
        wc_id = cfg.get("welcome_channel_id")
        wc = member.guild.get_channel(wc_id) if wc_id else None
        if isinstance(wc, discord.TextChannel):
            template = cfg.get("welcome_message") or "Bienvenue {membre} sur **{serveur}** ! 🎉"
            text = template.replace("{membre}", member.mention).replace("{serveur}", member.guild.name)
            embed = embeds.success("Nouveau membre", text)
            if cfg.get("welcome_image"):
                embed.set_image(url=cfg["welcome_image"])
            await wc.send(embed=embed)

        # Log technique.
        embed = embeds.success("📥 Arrivée")
        embed.add_field(name="Membre", value=f"{member.mention} ({member})")
        embed.add_field(name="Compte créé", value=discord.utils.format_dt(member.created_at, "R"))
        embed.add_field(name="Total membres", value=str(member.guild.member_count))
        await log_router.send_log(self.bot, member.guild, "members", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        cfg = await self.bot.config.get(member.guild.id)
        wc_id = cfg.get("welcome_channel_id")
        wc = member.guild.get_channel(wc_id) if wc_id else None
        if isinstance(wc, discord.TextChannel) and cfg.get("leave_message"):
            text = cfg["leave_message"].replace("{membre}", str(member)).replace("{serveur}", member.guild.name)
            embed = embeds.info("Départ", text)
            if cfg.get("leave_image"):
                embed.set_image(url=cfg["leave_image"])
            await wc.send(embed=embed)

        embed = embeds.warning("📤 Départ")
        embed.add_field(name="Membre", value=f"{member} (`{member.id}`)")
        embed.add_field(name="Total membres", value=str(member.guild.member_count))
        await log_router.send_log(self.bot, member.guild, "members", embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Logs(bot))
