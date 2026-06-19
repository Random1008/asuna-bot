"""Commandes générales / informatives accessibles à tous les membres."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import embeds


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Vérifie que le bot répond et affiche sa latence.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        embed = embeds.brand("🏓 Pong !", f"Latence : **{latency_ms} ms**")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serverinfo", description="Affiche des informations sur le serveur.")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        assert g is not None
        embed = embeds.brand(f"📊 {g.name}")
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Propriétaire", value=f"{g.owner.mention if g.owner else '—'}")
        embed.add_field(name="Membres", value=str(g.member_count))
        embed.add_field(name="Salons", value=str(len(g.channels)))
        embed.add_field(name="Rôles", value=str(len(g.roles)))
        embed.add_field(name="Boosts", value=str(g.premium_subscription_count or 0))
        embed.add_field(name="Créé le", value=discord.utils.format_dt(g.created_at, "D"))
        embed.add_field(name="ID", value=f"`{g.id}`", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Affiche des informations sur un membre.")
    @app_commands.describe(membre="Le membre à inspecter (toi par défaut).")
    @app_commands.guild_only()
    async def userinfo(
        self, interaction: discord.Interaction, membre: discord.Member | None = None
    ) -> None:
        member = membre or interaction.user
        embed = embeds.brand(f"👤 {member}")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Surnom", value=member.nick or "—")
        embed.add_field(name="ID", value=f"`{member.id}`")
        embed.add_field(
            name="Compte créé", value=discord.utils.format_dt(member.created_at, "R")
        )
        if member.joined_at:
            embed.add_field(
                name="A rejoint", value=discord.utils.format_dt(member.joined_at, "R")
            )
        roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        embed.add_field(
            name=f"Rôles ({len(roles)})",
            value=", ".join(roles[:15]) or "Aucun",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Affiche l'avatar d'un membre en grand.")
    @app_commands.describe(membre="Le membre dont afficher l'avatar (toi par défaut).")
    async def avatar(
        self, interaction: discord.Interaction, membre: discord.Member | None = None
    ) -> None:
        member = membre or interaction.user
        embed = embeds.brand(f"🖼️ Avatar de {member.display_name}")
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
