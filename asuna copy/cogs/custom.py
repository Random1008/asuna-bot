"""Réponses automatiques à des mots-clés (gérées par les admins)."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import embeds


class Custom(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Écoute des messages : réponses automatiques ──────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None or not message.content:
            return
        rows = await self.bot.db.fetchall(
            "SELECT trigger, response, match_type FROM autoresponses WHERE guild_id = ?",
            (message.guild.id,),
        )
        lowered = message.content.lower()
        for r in rows:
            trig = r["trigger"].lower()
            mt = r["match_type"]
            hit = (
                (mt == "contains" and trig in lowered)
                or (mt == "exact" and trig == lowered)
                or (mt == "startswith" and lowered.startswith(trig))
            )
            if hit:
                await message.channel.send(r["response"])
                break  # une seule réponse auto par message

    # ── /autoresponse … ─────────────────────────────────────────────────────
    autoresponse = app_commands.Group(
        name="autoresponse",
        description="Réponses automatiques à des mots-clés",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @autoresponse.command(name="add", description="Ajoute une réponse automatique.")
    @app_commands.describe(
        declencheur="Le mot/phrase qui déclenche",
        reponse="Le message envoyé en réponse",
        correspondance="Type de correspondance",
    )
    @app_commands.choices(
        correspondance=[
            app_commands.Choice(name="contient", value="contains"),
            app_commands.Choice(name="exact", value="exact"),
            app_commands.Choice(name="commence par", value="startswith"),
        ]
    )
    async def ar_add(
        self,
        interaction: discord.Interaction,
        declencheur: str,
        reponse: str,
        correspondance: app_commands.Choice[str] | None = None,
    ) -> None:
        mt = correspondance.value if correspondance else "contains"
        await self.bot.db.execute(
            "INSERT INTO autoresponses (guild_id, trigger, response, match_type) VALUES (?, ?, ?, ?)",
            (interaction.guild.id, declencheur, reponse, mt),
        )
        await interaction.response.send_message(
            embed=embeds.success("Réponse auto ajoutée", f"« {declencheur} » → réponse enregistrée ({mt})."),
            ephemeral=True,
        )

    @autoresponse.command(name="remove", description="Supprime une réponse automatique par son ID.")
    async def ar_remove(self, interaction: discord.Interaction, id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM autoresponses WHERE guild_id = ? AND id = ?", (interaction.guild.id, id)
        )
        await interaction.response.send_message(
            embed=embeds.success("Supprimée", f"Réponse auto #{id} retirée."), ephemeral=True
        )

    @autoresponse.command(name="list", description="Liste les réponses automatiques.")
    async def ar_list(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, trigger, match_type FROM autoresponses WHERE guild_id = ? ORDER BY id",
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Vide", "Aucune réponse automatique."), ephemeral=True
            )
            return
        lines = [f"`#{r['id']}` ({r['match_type']}) — « {r['trigger']} »" for r in rows]
        await interaction.response.send_message(
            embed=embeds.info(f"Réponses automatiques ({len(rows)})", "\n".join(lines)), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Custom(bot))
