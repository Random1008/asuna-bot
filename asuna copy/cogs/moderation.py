"""Module de modération : kick, ban, timeout, mute, avertissements, purge."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import checks, embeds, log_router
from core.utils import hierarchy_ok, parse_duration


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Helpers ─────────────────────────────────────────────────────────────
    async def _log_action(self, guild: discord.Guild, embed: discord.Embed) -> None:
        """Trace l'action dans le salon de modération (#asuna-moderation)."""
        await log_router.send_log(self.bot, guild, "mod", embed)

    # ── Sanctions ───────────────────────────────────────────────────────────
    @app_commands.command(name="kick", description="Expulse un membre du serveur.")
    @app_commands.describe(membre="Membre à expulser", raison="Raison de l'expulsion")
    @app_commands.guild_only()
    @checks.can_kick()
    async def kick(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str | None = None,
    ) -> None:
        ok, why = hierarchy_ok(interaction.user, membre, interaction.guild.me)
        if not ok:
            await interaction.response.send_message(embed=embeds.error("Action refusée", why), ephemeral=True)
            return
        reason = raison or "Aucune raison fournie"
        await membre.kick(reason=f"{interaction.user} : {reason}")
        embed = embeds.mod("Membre expulsé", f"{membre.mention} a été expulsé.")
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=reason)
        await interaction.response.send_message(embed=embed)
        await self._log_action(interaction.guild, embed)

    @app_commands.command(name="ban", description="Bannit un membre du serveur.")
    @app_commands.describe(
        membre="Membre à bannir",
        raison="Raison du bannissement",
        jours_messages="Jours de messages à supprimer (0-7)",
    )
    @app_commands.guild_only()
    @checks.can_ban()
    async def ban(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        raison: str | None = None,
        jours_messages: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        ok, why = hierarchy_ok(interaction.user, membre, interaction.guild.me)
        if not ok:
            await interaction.response.send_message(embed=embeds.error("Action refusée", why), ephemeral=True)
            return
        reason = raison or "Aucune raison fournie"
        await membre.ban(
            reason=f"{interaction.user} : {reason}",
            delete_message_days=jours_messages,
        )
        embed = embeds.mod("Membre banni", f"{membre.mention} a été banni.")
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        embed.add_field(name="Raison", value=reason)
        await interaction.response.send_message(embed=embed)
        await self._log_action(interaction.guild, embed)

    @app_commands.command(name="unban", description="Révoque le bannissement d'un utilisateur (par ID).")
    @app_commands.describe(user_id="ID de l'utilisateur à débannir", raison="Raison")
    @app_commands.guild_only()
    @checks.can_ban()
    async def unban(
        self, interaction: discord.Interaction, user_id: str, raison: str | None = None
    ) -> None:
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message(embed=embeds.error("ID invalide", "Donne un identifiant numérique."), ephemeral=True)
            return
        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"{interaction.user} : {raison or '—'}")
        except discord.NotFound:
            await interaction.response.send_message(embed=embeds.error("Introuvable", "Cet utilisateur n'est pas banni."), ephemeral=True)
            return
        embed = embeds.mod("Bannissement révoqué", f"{user.mention} a été débanni.")
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        await interaction.response.send_message(embed=embed)
        await self._log_action(interaction.guild, embed)

    @app_commands.command(name="timeout", description="Réduit un membre au silence pour une durée (ex: 10m, 1h).")
    @app_commands.describe(membre="Membre à isoler", duree="Durée (ex: 30s, 10m, 2h, 1d)", raison="Raison")
    @app_commands.guild_only()
    @checks.can_moderate_members()
    async def timeout(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
        duree: str,
        raison: str | None = None,
    ) -> None:
        ok, why = hierarchy_ok(interaction.user, membre, interaction.guild.me)
        if not ok:
            await interaction.response.send_message(embed=embeds.error("Action refusée", why), ephemeral=True)
            return
        delta = parse_duration(duree)
        if delta is None or delta.total_seconds() > 28 * 86400:
            await interaction.response.send_message(
                embed=embeds.error("Durée invalide", "Exemples valides : `30s`, `10m`, `2h`, `1d` (max 28 jours)."),
                ephemeral=True,
            )
            return
        await membre.timeout(delta, reason=f"{interaction.user} : {raison or '—'}")
        embed = embeds.mod("Membre isolé (timeout)", f"{membre.mention} est réduit au silence.")
        embed.add_field(name="Durée", value=duree)
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        if raison:
            embed.add_field(name="Raison", value=raison, inline=False)
        await interaction.response.send_message(embed=embed)
        await self._log_action(interaction.guild, embed)

    @app_commands.command(name="untimeout", description="Lève le timeout d'un membre.")
    @app_commands.describe(membre="Membre à libérer")
    @app_commands.guild_only()
    @checks.can_moderate_members()
    async def untimeout(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        await membre.timeout(None, reason=f"Levé par {interaction.user}")
        embed = embeds.success("Timeout levé", f"{membre.mention} peut de nouveau parler.")
        await interaction.response.send_message(embed=embed)
        await self._log_action(interaction.guild, embed)

    @app_commands.command(name="mute", description="Applique le rôle muet (configuré via !config muterole).")
    @app_commands.describe(membre="Membre à rendre muet", raison="Raison")
    @app_commands.guild_only()
    @checks.can_moderate_members()
    async def mute(
        self, interaction: discord.Interaction, membre: discord.Member, raison: str | None = None
    ) -> None:
        cfg = await self.bot.config.get(interaction.guild.id)
        role_id = cfg.get("mute_role_id")
        role = interaction.guild.get_role(role_id) if role_id else None
        if role is None:
            await interaction.response.send_message(
                embed=embeds.error("Rôle muet non configuré", "Définis-le avec `!config muterole`."),
                ephemeral=True,
            )
            return
        await membre.add_roles(role, reason=f"{interaction.user} : {raison or '—'}")
        embed = embeds.mod("Membre rendu muet", f"{membre.mention} a reçu le rôle {role.mention}.")
        embed.add_field(name="Modérateur", value=interaction.user.mention)
        await interaction.response.send_message(embed=embed)
        await self._log_action(interaction.guild, embed)

    @app_commands.command(name="unmute", description="Retire le rôle muet d'un membre.")
    @app_commands.describe(membre="Membre à démuter")
    @app_commands.guild_only()
    @checks.can_moderate_members()
    async def unmute(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        cfg = await self.bot.config.get(interaction.guild.id)
        role_id = cfg.get("mute_role_id")
        role = interaction.guild.get_role(role_id) if role_id else None
        if role and role in membre.roles:
            await membre.remove_roles(role, reason=f"Démuté par {interaction.user}")
        await interaction.response.send_message(
            embed=embeds.success("Membre démuté", f"{membre.mention} n'est plus muet."),
        )

    # ── Avertissements ──────────────────────────────────────────────────────
    @app_commands.command(name="warn", description="Donne un avertissement à un membre.")
    @app_commands.describe(membre="Membre à avertir", raison="Raison de l'avertissement")
    @app_commands.guild_only()
    @checks.is_mod()
    async def warn(
        self, interaction: discord.Interaction, membre: discord.Member, raison: str
    ) -> None:
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (interaction.guild.id, membre.id, interaction.user.id, raison,
             discord.utils.utcnow().isoformat()),
        )
        row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS c FROM warnings WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, membre.id),
        )
        count = row["c"] if row else 1
        embed = embeds.warning("Avertissement enregistré", f"{membre.mention} a été averti.")
        embed.add_field(name="Raison", value=raison)
        embed.add_field(name="Total", value=f"{count} avertissement(s)")
        await interaction.response.send_message(embed=embed)
        await self._log_action(interaction.guild, embed)
        try:
            await membre.send(
                embed=embeds.warning(
                    f"Tu as reçu un avertissement sur {interaction.guild.name}", raison
                )
            )
        except discord.HTTPException:
            pass  # DMs fermés

    @app_commands.command(name="warns", description="Liste les avertissements d'un membre.")
    @app_commands.describe(membre="Membre à consulter")
    @app_commands.guild_only()
    @checks.is_mod()
    async def warns(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, moderator_id, reason, created_at FROM warnings "
            "WHERE guild_id = ? AND user_id = ? ORDER BY id DESC",
            (interaction.guild.id, membre.id),
        )
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Casier vierge", f"{membre.mention} n'a aucun avertissement."),
                ephemeral=True,
            )
            return
        embed = embeds.warning(f"Avertissements de {membre.display_name}", f"Total : {len(rows)}")
        for r in rows[:10]:
            mod = interaction.guild.get_member(r["moderator_id"])
            embed.add_field(
                name=f"#{r['id']} — par {mod.display_name if mod else 'inconnu'}",
                value=r["reason"] or "—",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarns", description="Efface tous les avertissements d'un membre.")
    @app_commands.describe(membre="Membre à blanchir")
    @app_commands.guild_only()
    @checks.is_mod()
    async def clearwarns(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, membre.id),
        )
        await interaction.response.send_message(
            embed=embeds.success("Casier effacé", f"Les avertissements de {membre.mention} ont été supprimés."),
        )

    # ── Nettoyage ───────────────────────────────────────────────────────────
    @app_commands.command(name="purge", description="Supprime un lot de messages récents.")
    @app_commands.describe(nombre="Nombre de messages (1-100)", membre="Filtrer sur un membre (optionnel)")
    @app_commands.guild_only()
    @checks.is_mod()
    async def purge(
        self,
        interaction: discord.Interaction,
        nombre: app_commands.Range[int, 1, 100],
        membre: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        check = (lambda m: m.author == membre) if membre else None
        deleted = await interaction.channel.purge(limit=nombre, check=check)
        await interaction.followup.send(
            embed=embeds.success("Nettoyage terminé", f"**{len(deleted)}** message(s) supprimé(s)."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
