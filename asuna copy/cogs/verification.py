"""Vérification des membres : un bouton persistant qui attribue le rôle de
vérification configuré (anti-bot simple). L'admin pose le panneau via /verifysetup.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import checks, embeds


class VerificationView(discord.ui.View):
    """Vue persistante : le bouton survit aux redémarrages grâce à son custom_id."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Je vérifie que je suis humain",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="asuna:verify",
    )
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cfg = await interaction.client.config.get(interaction.guild.id)
        role_id = cfg.get("verify_role_id")
        role = interaction.guild.get_role(role_id) if role_id else None
        if role is None:
            await interaction.response.send_message(
                embed=embeds.error("Vérification indisponible", "Aucun rôle de vérification n'est configuré. Préviens un admin."),
                ephemeral=True,
            )
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(
                embed=embeds.info("Déjà vérifié", "Tu as déjà accès au serveur. 😉"), ephemeral=True
            )
            return
        try:
            await interaction.user.add_roles(role, reason="Vérification réussie")
        except discord.HTTPException:
            await interaction.response.send_message(
                embed=embeds.error("Échec", "Je n'ai pas pu te donner le rôle (vérifie mes permissions)."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Bienvenue !", f"Tu as reçu le rôle {role.mention}. Bon séjour ! 🎉"),
            ephemeral=True,
        )


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="verifysetup", description="Poste le panneau de vérification dans un salon.")
    @app_commands.describe(salon="Salon où poster le panneau")
    @app_commands.guild_only()
    @checks.is_admin()
    async def verifysetup(self, interaction: discord.Interaction, salon: discord.TextChannel) -> None:
        cfg = await self.bot.config.get(interaction.guild.id)
        if not cfg.get("verify_role_id"):
            await interaction.response.send_message(
                embed=embeds.error("Rôle manquant", "Configure d'abord le rôle avec `!config verifyrole`."),
                ephemeral=True,
            )
            return
        embed = embeds.brand(
            "✅ Vérification",
            "Clique sur le bouton ci-dessous pour confirmer que tu es un humain et accéder au serveur.",
        )
        await salon.send(embed=embed, view=VerificationView())
        await interaction.response.send_message(
            embed=embeds.success("Panneau posté", f"La vérification est active dans {salon.mention}."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Verification(bot))
