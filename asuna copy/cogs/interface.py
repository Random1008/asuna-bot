"""Démonstration des composants d'interface : boutons, menu déroulant, modal.

Sert d'exemple réutilisable pour les futurs modules (ces patrons se retrouvent
partout : tickets, boutiques, jeux…).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import embeds


class FeedbackModal(discord.ui.Modal, title="Donne ton avis"):
    """Exemple de formulaire (modal) avec deux champs."""

    sujet = discord.ui.TextInput(label="Sujet", placeholder="En quelques mots…", max_length=100)
    details = discord.ui.TextInput(
        label="Détails",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        embed = embeds.success("Merci !", "Ton avis a bien été reçu.")
        embed.add_field(name="Sujet", value=str(self.sujet), inline=False)
        if self.details.value:
            embed.add_field(name="Détails", value=str(self.details), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class DemoView(discord.ui.View):
    """Vue de démo : un bouton, un menu déroulant et un bouton ouvrant un modal."""

    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.select(
        placeholder="🎨 Choisis ta couleur préférée…",
        options=[
            discord.SelectOption(label="Rouge", emoji="🔴", value="Rouge"),
            discord.SelectOption(label="Vert", emoji="🟢", value="Vert"),
            discord.SelectOption(label="Bleu", emoji="🔵", value="Bleu"),
            discord.SelectOption(label="Violet", emoji="🟣", value="Violet"),
        ],
    )
    async def choisir(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await interaction.response.send_message(
            embed=embeds.info("Sélection", f"Tu as choisi : **{select.values[0]}**"), ephemeral=True
        )

    @discord.ui.button(label="Clique-moi", emoji="👆", style=discord.ButtonStyle.primary)
    async def bouton(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=embeds.success("Bouton cliqué", "Et voilà, une interaction de bouton !"), ephemeral=True
        )

    @discord.ui.button(label="Ouvrir un formulaire", emoji="📝", style=discord.ButtonStyle.secondary)
    async def formulaire(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(FeedbackModal())


class Interface(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="interface", description="Démo des composants : boutons, menus, formulaires.")
    async def interface(self, interaction: discord.Interaction) -> None:
        embed = embeds.brand(
            "🎨 Démo d'interface",
            "Voici les composants interactifs disponibles dans Asuna :\n"
            "• **Menu déroulant** pour choisir une option\n"
            "• **Boutons** pour déclencher une action\n"
            "• **Formulaire (modal)** pour saisir du texte",
        )
        await interaction.response.send_message(embed=embed, view=DemoView())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Interface(bot))
