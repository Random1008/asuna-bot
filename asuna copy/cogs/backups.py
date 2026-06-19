"""Sauvegardes du serveur : structure (rôles, salons, permissions) et base de données.

La restauration est non destructive (ne recrée que ce qui manque) et confirmée
par un bouton. Le backup de la base SQLite est réservé au propriétaire du bot.
"""

from __future__ import annotations

import io
import json

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core import backup, embeds

_MAX_BACKUPS = 10  # on garde les N derniers backups par serveur


class RestoreConfirmView(discord.ui.View):
    """Confirmation avant restauration (action sensible)."""

    def __init__(self, author_id: int, data: dict) -> None:
        super().__init__(timeout=60)
        self.author_id = author_id
        self.data = data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    @discord.ui.button(label="Restaurer", emoji="♻️", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=embeds.info("Restauration en cours…", "Recréation des éléments manquants…"), view=None)
        try:
            created = await backup.restore_guild(interaction.guild, self.data)
        except discord.Forbidden:
            await interaction.edit_original_response(
                embed=embeds.error("Permissions insuffisantes", "Il me faut **Gérer les rôles** et **Gérer les salons**."))
            return
        await interaction.edit_original_response(
            embed=embeds.success(
                "Restauration terminée",
                f"Créés — rôles : **{created['roles']}**, catégories : **{created['categories']}**, "
                f"salons : **{created['channels']}**.\n*(Rien n'a été supprimé.)*"))
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=embeds.info("Annulé", "Aucune modification."), view=None)
        self.stop()


class Backups(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    backup_grp = app_commands.Group(
        name="backup", description="Sauvegarde/restauration du serveur",
        default_permissions=discord.Permissions(administrator=True), guild_only=True)

    @backup_grp.command(name="create", description="Sauvegarde la structure du serveur (rôles, salons, permissions).")
    @app_commands.describe(nom="Nom du backup (optionnel)")
    async def create(self, interaction: discord.Interaction, nom: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        data = backup.snapshot_guild(interaction.guild)
        name = nom or discord.utils.utcnow().strftime("backup-%Y%m%d-%H%M")
        await self.bot.db.execute(
            "INSERT INTO backups (guild_id, name, data, created_at) VALUES (?, ?, ?, ?)",
            (interaction.guild.id, name, json.dumps(data), discord.utils.utcnow().isoformat()))
        # Purge des plus anciens au-delà de la limite.
        await self.bot.db.execute(
            "DELETE FROM backups WHERE guild_id = ? AND id NOT IN "
            "(SELECT id FROM backups WHERE guild_id = ? ORDER BY id DESC LIMIT ?)",
            (interaction.guild.id, interaction.guild.id, _MAX_BACKUPS))
        s = backup.summarize(data)
        await interaction.followup.send(
            embed=embeds.success("Backup créé", f"**{name}** — {s['roles']} rôles, {s['categories']} catégories, {s['channels']} salons."),
            ephemeral=True)

    @backup_grp.command(name="list", description="Liste les sauvegardes du serveur.")
    async def list_(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, name, created_at FROM backups WHERE guild_id = ? ORDER BY id DESC", (interaction.guild.id,))
        if not rows:
            await interaction.response.send_message(embed=embeds.info("Aucun backup", "Crée-en un avec `/backup create`."), ephemeral=True)
            return
        from datetime import datetime
        lines = [f"`#{r['id']}` **{r['name']}** — {discord.utils.format_dt(datetime.fromisoformat(r['created_at']), 'R')}" for r in rows]
        await interaction.response.send_message(embed=embeds.info(f"Sauvegardes ({len(rows)})", "\n".join(lines)), ephemeral=True)

    @backup_grp.command(name="restore", description="Restaure une sauvegarde (recrée ce qui manque).")
    @app_commands.describe(id="Numéro du backup (voir /backup list)")
    async def restore(self, interaction: discord.Interaction, id: int) -> None:
        row = await self.bot.db.fetchone(
            "SELECT name, data FROM backups WHERE id = ? AND guild_id = ?", (id, interaction.guild.id))
        if row is None:
            await interaction.response.send_message(embed=embeds.error("Introuvable", "Aucun backup à ce numéro."), ephemeral=True)
            return
        data = json.loads(row["data"])
        s = backup.summarize(data)
        embed = embeds.warning(
            f"Restaurer « {row['name']} » ?",
            f"Je vais recréer les éléments **manquants** ({s['roles']} rôles, {s['categories']} catégories, "
            f"{s['channels']} salons). **Rien ne sera supprimé.** Confirmer ?")
        await interaction.response.send_message(embed=embed, view=RestoreConfirmView(interaction.user.id, data), ephemeral=True)

    @backup_grp.command(name="delete", description="Supprime une sauvegarde.")
    async def delete(self, interaction: discord.Interaction, id: int) -> None:
        await self.bot.db.execute("DELETE FROM backups WHERE id = ? AND guild_id = ?", (id, interaction.guild.id))
        await interaction.response.send_message(embed=embeds.success("Supprimé", f"Backup #{id} supprimé."), ephemeral=True)

    # ── Backup de la base de données (propriétaire uniquement) ─────────────────
    @app_commands.command(name="dbbackup", description="(Propriétaire) Reçoit une copie de la base de données en DM.")
    async def dbbackup(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != Config.OWNER_ID:
            await interaction.response.send_message(
                embed=embeds.error("Réservé", "Seul le propriétaire du bot peut faire ça."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            with open(Config.DB_PATH, "rb") as f:
                data = io.BytesIO(f.read())
            await interaction.user.send(
                embed=embeds.brand("💾 Backup de la base", "Conserve ce fichier en lieu sûr."),
                file=discord.File(data, filename="asuna.db"))
            await interaction.followup.send(embed=embeds.success("Envoyé", "Base envoyée en message privé."), ephemeral=True)
        except (OSError, discord.HTTPException):
            await interaction.followup.send(embed=embeds.error("Échec", "Impossible d'envoyer la base (DM fermés ?)."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Backups(bot))
