"""Sécurité avancée : anti-nuke, blacklist/whitelist d'utilisateurs, lockdown.

- Anti-nuke : détecte les actions destructives en masse (suppression de salons/
  rôles, créations massives, bannissements) via les logs d'audit et sanctionne
  l'auteur s'il n'est pas de confiance.
- Blacklist : bannit automatiquement les utilisateurs blacklistés qui rejoignent.
- Whitelist : utilisateurs de confiance, exemptés de l'anti-nuke.
- Lockdown : verrouille/déverrouille tous les salons en urgence.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands

from core import embeds, log_router


class Security(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # {(guild_id, user_id): deque[timestamps]} pour la fenêtre anti-nuke.
        self._actions: dict[tuple[int, int], deque] = defaultdict(deque)
        self._punished: set[tuple[int, int]] = set()

    # ── Blacklist à l'arrivée ─────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        row = await self.bot.db.fetchone(
            "SELECT reason FROM user_blacklist WHERE guild_id = ? AND user_id = ?",
            (member.guild.id, member.id))
        if row is None:
            return
        try:
            await member.ban(reason=f"Blacklist : {row['reason'] or 'aucune raison'}")
        except discord.HTTPException:
            return
        await log_router.send_log(
            self.bot, member.guild, "mod",
            embeds.mod("Membre blacklisté banni", f"{member} (`{member.id}`) a tenté de rejoindre."))

    # ── Anti-nuke ─────────────────────────────────────────────────────────────
    async def _actor(self, guild: discord.Guild, action: discord.AuditLogAction):
        """Trouve l'auteur d'une action récente via les logs d'audit."""
        try:
            async for entry in guild.audit_logs(limit=1, action=action):
                if (discord.utils.utcnow() - entry.created_at).total_seconds() < 15:
                    return entry.user
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None

    async def _is_trusted(self, guild: discord.Guild, user_id: int) -> bool:
        if user_id == guild.owner_id or user_id == self.bot.user.id:
            return True
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM security_whitelist WHERE guild_id = ? AND user_id = ?", (guild.id, user_id))
        return row is not None

    async def _guard(self, guild: discord.Guild, action: discord.AuditLogAction, label: str) -> None:
        cfg = await self.bot.config.get(guild.id)
        if not cfg.get("antinuke_enabled"):
            return
        actor = await self._actor(guild, action)
        if actor is None or actor.bot or await self._is_trusted(guild, actor.id):
            return

        threshold = cfg.get("antinuke_threshold") or 3
        window = cfg.get("antinuke_window") or 30
        key = (guild.id, actor.id)
        now = time.monotonic()
        dq = self._actions[key]
        dq.append(now)
        while dq and now - dq[0] > window:
            dq.popleft()

        if len(dq) >= threshold and key not in self._punished:
            self._punished.add(key)
            await self._punish(guild, actor, cfg.get("antinuke_action") or "strip", label, len(dq))

    async def _punish(self, guild, actor, action: str, label: str, count: int) -> None:
        member = guild.get_member(actor.id)
        done = "alerté"
        try:
            if action == "ban":
                await guild.ban(actor, reason="Anti-nuke : actions destructives en masse")
                done = "banni"
            elif action == "kick" and member:
                await member.kick(reason="Anti-nuke : actions destructives en masse")
                done = "expulsé"
            elif member:  # strip : retire ses rôles gérables
                removable = [r for r in member.roles if not r.is_default() and r < guild.me.top_role]
                if removable:
                    await member.remove_roles(*removable, reason="Anti-nuke : rôles retirés")
                done = "privé de ses rôles"
        except discord.HTTPException:
            done = "non sanctionné (permissions ?)"
        await log_router.report_problem(
            self.bot, guild, "🚨 ANTI-NUKE déclenché",
            f"**Auteur :** {actor.mention} (`{actor.id}`)\n**Motif :** {count} × {label} en rafale\n"
            f"**Sanction :** {done}.")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel) -> None:
        await self._guard(channel.guild, discord.AuditLogAction.channel_delete, "suppression de salon")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel) -> None:
        await self._guard(channel.guild, discord.AuditLogAction.channel_create, "création de salon")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self._guard(role.guild, discord.AuditLogAction.role_delete, "suppression de rôle")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user) -> None:
        await self._guard(guild, discord.AuditLogAction.ban, "bannissement")

    # ── Commandes : /security … ───────────────────────────────────────────────
    security = app_commands.Group(
        name="security", description="Sécurité avancée du serveur",
        default_permissions=discord.Permissions(administrator=True), guild_only=True)

    @security.command(name="whitelist", description="Ajoute/retire un membre de confiance (exempté anti-nuke).")
    @app_commands.choices(operation=[
        app_commands.Choice(name="Ajouter", value="add"),
        app_commands.Choice(name="Retirer", value="remove"),
    ])
    async def whitelist(self, interaction: discord.Interaction, operation: app_commands.Choice[str], membre: discord.Member) -> None:
        if operation.value == "add":
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO security_whitelist (guild_id, user_id) VALUES (?, ?)",
                (interaction.guild.id, membre.id))
            msg = f"{membre.mention} est maintenant de confiance."
        else:
            await self.bot.db.execute(
                "DELETE FROM security_whitelist WHERE guild_id = ? AND user_id = ?", (interaction.guild.id, membre.id))
            msg = f"{membre.mention} retiré de la whitelist."
        await interaction.response.send_message(embed=embeds.success("Whitelist mise à jour", msg), ephemeral=True)

    @security.command(name="blacklist", description="Gère la liste des utilisateurs bannis à l'arrivée.")
    @app_commands.choices(operation=[
        app_commands.Choice(name="Ajouter", value="add"),
        app_commands.Choice(name="Retirer", value="remove"),
        app_commands.Choice(name="Lister", value="list"),
    ])
    async def blacklist(self, interaction: discord.Interaction, operation: app_commands.Choice[str],
                        user_id: str | None = None, raison: str | None = None) -> None:
        gid = interaction.guild.id
        if operation.value == "list":
            rows = await self.bot.db.fetchall("SELECT user_id, reason FROM user_blacklist WHERE guild_id = ?", (gid,))
            if not rows:
                await interaction.response.send_message(embed=embeds.info("Blacklist vide", "Aucun utilisateur blacklisté."), ephemeral=True)
                return
            lines = [f"`{r['user_id']}` — {r['reason'] or '—'}" for r in rows]
            await interaction.response.send_message(embed=embeds.info(f"Blacklist ({len(rows)})", "\n".join(lines)), ephemeral=True)
            return
        if not user_id or not user_id.isdigit():
            await interaction.response.send_message(embed=embeds.error("ID requis", "Donne un identifiant numérique."), ephemeral=True)
            return
        uid = int(user_id)
        if operation.value == "add":
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO user_blacklist (guild_id, user_id, reason, created_at) VALUES (?, ?, ?, ?)",
                (gid, uid, raison, discord.utils.utcnow().isoformat()))
            # Bannit immédiatement s'il est déjà là.
            member = interaction.guild.get_member(uid)
            if member:
                try:
                    await member.ban(reason=f"Blacklist : {raison or '—'}")
                except discord.HTTPException:
                    pass
            await interaction.response.send_message(embed=embeds.success("Blacklist", f"`{uid}` sera banni à l'arrivée."), ephemeral=True)
        else:
            await self.bot.db.execute("DELETE FROM user_blacklist WHERE guild_id = ? AND user_id = ?", (gid, uid))
            await interaction.response.send_message(embed=embeds.success("Blacklist", f"`{uid}` retiré."), ephemeral=True)

    # ── Lockdown ──────────────────────────────────────────────────────────────
    @app_commands.command(name="lockdown", description="Verrouille tous les salons écrits (urgence).")
    @app_commands.describe(raison="Raison affichée")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def lockdown(self, interaction: discord.Interaction, raison: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)
        count = 0
        for ch in interaction.guild.text_channels:
            try:
                await ch.set_permissions(interaction.guild.default_role, send_messages=False,
                                         reason=f"Lockdown par {interaction.user}")
                count += 1
            except discord.HTTPException:
                pass
        await interaction.followup.send(
            embed=embeds.warning("🔒 Lockdown activé", f"{count} salon(s) verrouillé(s)." + (f"\nRaison : {raison}" if raison else "")),
            ephemeral=True)

    @app_commands.command(name="unlock", description="Déverrouille tous les salons écrits.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        count = 0
        for ch in interaction.guild.text_channels:
            try:
                await ch.set_permissions(interaction.guild.default_role, send_messages=None,
                                         reason=f"Déverrouillage par {interaction.user}")
                count += 1
            except discord.HTTPException:
                pass
        await interaction.followup.send(
            embed=embeds.success("🔓 Déverrouillé", f"{count} salon(s) déverrouillé(s)."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Security(bot))
