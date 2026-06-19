"""Système de tickets de support.

Un panneau (bouton persistant) permet aux membres d'ouvrir un **salon privé**
visible d'eux seuls + du staff. Boutons « Prendre en charge » et « Fermer » ;
à la fermeture, un transcript est archivé dans le salon de logs configuré.

Configuration (admin) : catégorie des tickets, rôle staff, salon de transcripts.
"""

from __future__ import annotations

import asyncio
import io

import discord
from discord import app_commands
from discord.ext import commands

from core import embeds


def build_panel_embed(cfg: dict) -> discord.Embed:
    """Embed du panneau d'ouverture de tickets (personnalisable via !config)."""
    title = cfg.get("ticket_panel_title") or "🎫 Besoin d'aide ?"
    message = cfg.get("ticket_panel_message") or "Clique sur le bouton ci-dessous pour ouvrir un ticket privé avec le staff."
    embed = embeds.brand(title, message)
    if cfg.get("ticket_panel_image"):
        embed.set_image(url=cfg["ticket_panel_image"])
    return embed


async def _is_staff(bot, member: discord.Member) -> bool:
    """True si le membre est admin ou possède le rôle staff configuré."""
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    cfg = await bot.config.get(member.guild.id)
    role_id = cfg.get("ticket_staff_role_id")
    return bool(role_id) and any(r.id == role_id for r in member.roles)


async def _build_transcript(channel: discord.TextChannel) -> discord.File:
    """Construit un transcript texte des messages du ticket."""
    lines = [f"Transcript — #{channel.name}", "=" * 40]
    async for msg in channel.history(limit=500, oldest_first=True):
        stamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
        content = msg.content or ("[embed/fichier]" if (msg.embeds or msg.attachments) else "")
        lines.append(f"[{stamp}] {msg.author}: {content}")
    data = io.BytesIO("\n".join(lines).encode("utf-8"))
    return discord.File(data, filename=f"{channel.name}.txt")


# ── Vues persistantes ─────────────────────────────────────────────────────────
class TicketPanelView(discord.ui.View):
    """Panneau public : bouton d'ouverture de ticket (persistant)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket", emoji="🎫",
                       style=discord.ButtonStyle.primary, custom_id="asuna:ticket:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _open_ticket(interaction)


class TicketControlView(discord.ui.View):
    """Contrôles dans un ticket : prise en charge + fermeture (persistant)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Prendre en charge", emoji="🙋",
                       style=discord.ButtonStyle.secondary, custom_id="asuna:ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot = interaction.client
        if not await _is_staff(bot, interaction.user):
            await interaction.response.send_message(
                embed=embeds.error("Réservé au staff", "Seul le staff peut prendre en charge un ticket."), ephemeral=True)
            return
        await bot.db.execute(
            "UPDATE tickets SET claimed_by = ? WHERE channel_id = ? AND status = 'open'",
            (interaction.user.id, interaction.channel.id))
        await interaction.response.send_message(
            embed=embeds.success("Ticket pris en charge", f"{interaction.user.mention} s'occupe de ce ticket."))

    @discord.ui.button(label="Fermer", emoji="🔒",
                       style=discord.ButtonStyle.danger, custom_id="asuna:ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _close_ticket(interaction)


# ── Logique partagée ──────────────────────────────────────────────────────────
async def _open_ticket(interaction: discord.Interaction) -> None:
    bot = interaction.client
    guild = interaction.guild
    cfg = await bot.config.get(guild.id)
    category = guild.get_channel(cfg.get("ticket_category_id")) if cfg.get("ticket_category_id") else None
    staff = guild.get_role(cfg.get("ticket_staff_role_id")) if cfg.get("ticket_staff_role_id") else None
    if not isinstance(category, discord.CategoryChannel) or staff is None:
        await interaction.response.send_message(
            embed=embeds.error("Tickets non configurés", "Un admin doit définir la catégorie et le rôle staff (`/ticket category`, `/ticket staff`)."),
            ephemeral=True)
        return

    # Un seul ticket ouvert par membre.
    existing = await bot.db.fetchone(
        "SELECT channel_id FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
        (guild.id, interaction.user.id))
    if existing and guild.get_channel(existing["channel_id"]):
        await interaction.response.send_message(
            embed=embeds.info("Ticket déjà ouvert", f"Tu as déjà un ticket : <#{existing['channel_id']}>."), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    number = (cfg.get("ticket_counter") or 0) + 1
    await bot.config.set(guild.id, "ticket_counter", number)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        staff: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    channel = await guild.create_text_channel(
        f"ticket-{number:04d}", category=category, overwrites=overwrites,
        topic=f"Ticket de {interaction.user} (id {interaction.user.id})", reason="Ouverture de ticket")
    await bot.db.execute(
        "INSERT INTO tickets (guild_id, channel_id, user_id, number, status, created_at) "
        "VALUES (?, ?, ?, ?, 'open', ?)",
        (guild.id, channel.id, interaction.user.id, number, discord.utils.utcnow().isoformat()))

    embed = embeds.brand(
        f"🎫 Ticket #{number:04d}",
        f"Bienvenue {interaction.user.mention} ! Décris ta demande, le staff te répondra ici.\n"
        "Utilise les boutons ci-dessous pour la prise en charge ou la fermeture.")
    await channel.send(content=f"{interaction.user.mention} {staff.mention}", embed=embed, view=TicketControlView())
    await interaction.followup.send(
        embed=embeds.success("Ticket ouvert", f"Ton ticket : {channel.mention}"), ephemeral=True)


async def _close_ticket(interaction: discord.Interaction) -> None:
    bot = interaction.client
    channel = interaction.channel
    ticket = await bot.db.fetchone(
        "SELECT * FROM tickets WHERE channel_id = ? AND status = 'open'", (channel.id,))
    if ticket is None:
        await interaction.response.send_message(
            embed=embeds.error("Pas un ticket", "Cette commande s'utilise dans un ticket ouvert."), ephemeral=True)
        return
    if interaction.user.id != ticket["user_id"] and not await _is_staff(bot, interaction.user):
        await interaction.response.send_message(
            embed=embeds.error("Non autorisé", "Seuls l'auteur du ticket et le staff peuvent le fermer."), ephemeral=True)
        return

    await bot.db.execute("UPDATE tickets SET status = 'closed' WHERE channel_id = ?", (channel.id,))
    await interaction.response.send_message(embed=embeds.warning("Fermeture", "Ce ticket sera fermé dans 5 secondes..."))

    # Transcript dans le salon de logs configuré.
    cfg = await bot.config.get(interaction.guild.id)
    log = interaction.guild.get_channel(cfg.get("ticket_log_channel_id")) if cfg.get("ticket_log_channel_id") else None
    if isinstance(log, discord.TextChannel):
        try:
            owner = interaction.guild.get_member(ticket["user_id"])
            summary = embeds.info(
                f"📁 Ticket #{ticket['number']:04d} archivé",
                f"Auteur : {owner.mention if owner else ticket['user_id']}\n"
                f"Fermé par : {interaction.user.mention}")
            await log.send(embed=summary, file=await _build_transcript(channel))
        except discord.HTTPException:
            pass

    await asyncio.sleep(5)
    try:
        await channel.delete(reason=f"Ticket fermé par {interaction.user}")
    except discord.HTTPException:
        pass


# ── Cog : configuration & commandes ───────────────────────────────────────────
class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ticket = app_commands.Group(
        name="ticket", description="Système de tickets de support",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True)

    @ticket.command(name="panel", description="Poste le panneau d'ouverture de tickets dans un salon.")
    async def panel(self, interaction: discord.Interaction, salon: discord.TextChannel) -> None:
        cfg = await self.bot.config.get(interaction.guild.id)
        await salon.send(embed=build_panel_embed(cfg), view=TicketPanelView())
        await interaction.response.send_message(
            embed=embeds.success("Panneau posté", f"Les tickets s'ouvrent depuis {salon.mention}."), ephemeral=True)

    @ticket.command(name="add", description="Ajoute un membre au ticket courant.")
    async def add(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if not await self._in_ticket(interaction):
            return
        await interaction.channel.set_permissions(membre, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(
            embed=embeds.success("Membre ajouté", f"{membre.mention} a accès à ce ticket."))

    @ticket.command(name="remove", description="Retire un membre du ticket courant.")
    async def remove(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if not await self._in_ticket(interaction):
            return
        await interaction.channel.set_permissions(membre, overwrite=None)
        await interaction.response.send_message(
            embed=embeds.success("Membre retiré", f"{membre.mention} n'a plus accès à ce ticket."))

    @ticket.command(name="close", description="Ferme le ticket courant.")
    async def close(self, interaction: discord.Interaction) -> None:
        await _close_ticket(interaction)

    async def _in_ticket(self, interaction: discord.Interaction) -> bool:
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM tickets WHERE channel_id = ? AND status = 'open'", (interaction.channel.id,))
        if row is None:
            await interaction.response.send_message(
                embed=embeds.error("Pas un ticket", "Cette commande s'utilise dans un ticket ouvert."), ephemeral=True)
            return False
        return True


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
