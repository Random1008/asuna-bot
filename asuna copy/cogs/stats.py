"""Suivi des statistiques (messages, commandes) + commandes /stats et /dashboard."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core import embeds, stats


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Collecte ───────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        await stats.incr_message(self.bot.db, message.guild.id, message.author.id)

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command
    ) -> None:
        if interaction.guild is not None:
            await stats.incr_command(self.bot.db, interaction.guild.id, command.qualified_name)

    # ── /stats ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="stats", description="Affiche les statistiques du serveur.")
    @app_commands.guild_only()
    async def stats_cmd(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild.id
        db = self.bot.db
        embed = embeds.brand(f"📊 Statistiques — {interaction.guild.name}")
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.add_field(name="Membres", value=str(interaction.guild.member_count))
        embed.add_field(name="Messages aujourd'hui", value=str(await stats.messages_today(db, gid)))
        embed.add_field(name="Messages (7 j)", value=str(await stats.messages_window(db, gid, 7)))

        chatters = await stats.top_users(db, gid, 5)
        if chatters:
            lines = []
            for i, r in enumerate(chatters):
                m = interaction.guild.get_member(r["user_id"])
                lines.append(f"`#{i + 1}` {m.display_name if m else r['user_id']} — {r['count']}")
            embed.add_field(name="🗣️ Top bavards", value="\n".join(lines), inline=False)

        cmds = await stats.top_commands(db, gid, 5)
        if cmds:
            embed.add_field(
                name="⚙️ Commandes populaires",
                value="\n".join(f"`/{r['command']}` — {r['count']}" for r in cmds), inline=False)

        if Config.DASHBOARD_ENABLED:
            embed.add_field(name="🌐 Dashboard", value=f"{self._dashboard_url()}/guild/{gid}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dashboard", description="Donne le lien du dashboard web.")
    async def dashboard_cmd(self, interaction: discord.Interaction) -> None:
        if not Config.DASHBOARD_ENABLED:
            await interaction.response.send_message(
                embed=embeds.info("Dashboard désactivé", "Active-le via `DASHBOARD_ENABLED=true` dans le `.env`."),
                ephemeral=True)
            return
        url = self._dashboard_url()
        target = f"{url}/guild/{interaction.guild.id}" if interaction.guild else url
        await interaction.response.send_message(
            embed=embeds.brand("🌐 Dashboard", f"[Ouvrir le dashboard]({target})\n`{target}`"), ephemeral=True)

    @staticmethod
    def _dashboard_url() -> str:
        return (Config.DASHBOARD_URL or f"http://localhost:{Config.DASHBOARD_PORT}").rstrip("/")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Stats(bot))
