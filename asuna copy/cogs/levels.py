"""Système d'XP et de niveaux : gain d'XP en discutant, montées de niveau
annoncées, classement, et récompenses de rôles automatiques par palier.
"""

from __future__ import annotations

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from core import embeds, leveling

_XP_COOLDOWN = 60.0       # secondes entre deux gains d'XP par membre
_XP_MIN, _XP_MAX = 15, 25  # XP gagnée par message éligible


class Levels(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Gain d'XP ─────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        cfg = await self.bot.config.get(message.guild.id)
        if not cfg.get("xp_enabled"):
            return

        gid, uid = message.guild.id, message.author.id
        row = await self.bot.db.fetchone(
            "SELECT xp, last_msg FROM levels WHERE guild_id = ? AND user_id = ?", (gid, uid)
        )
        now = time.time()
        if row and now - row["last_msg"] < _XP_COOLDOWN:
            return  # encore en cooldown, pas d'XP

        old_xp = row["xp"] if row else 0
        gain = random.randint(_XP_MIN, _XP_MAX)
        new_xp = old_xp + gain
        await self.bot.db.execute(
            "INSERT INTO levels (guild_id, user_id, xp, last_msg) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = excluded.xp, last_msg = excluded.last_msg",
            (gid, uid, new_xp, now),
        )

        old_level, *_ = leveling.level_from_xp(old_xp)
        new_level, *_ = leveling.level_from_xp(new_xp)
        if new_level > old_level:
            await self._on_level_up(message, new_level, cfg)

    async def _on_level_up(self, message: discord.Message, level: int, cfg: dict) -> None:
        # Annonce (si activée), dans le salon configuré ou celui du message.
        if cfg.get("levelup_announce"):
            chan = message.channel
            cid = cfg.get("levelup_channel_id")
            if cid:
                configured = message.guild.get_channel(cid)
                if isinstance(configured, discord.TextChannel):
                    chan = configured
            try:
                await chan.send(
                    embed=embeds.success("Niveau supérieur !", f"{message.author.mention} passe **niveau {level}** 🎉")
                )
            except discord.HTTPException:
                pass

        # Récompenses de rôles pour les paliers atteints.
        rewards = await self.bot.db.fetchall(
            "SELECT level, role_id FROM level_rewards WHERE guild_id = ? AND level <= ?",
            (message.guild.id, level),
        )
        for r in rewards:
            role = message.guild.get_role(r["role_id"])
            if role and role not in message.author.roles:
                try:
                    await message.author.add_roles(role, reason=f"Récompense de niveau {r['level']}")
                except discord.HTTPException:
                    pass

    # ── Consultation ──────────────────────────────────────────────────────────
    @app_commands.command(name="rank", description="Affiche ton niveau et ta progression.")
    @app_commands.describe(membre="Membre à consulter (toi par défaut)")
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        target = membre or interaction.user
        row = await self.bot.db.fetchone(
            "SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?", (interaction.guild.id, target.id)
        )
        total_xp = row["xp"] if row else 0
        level, into, needed = leveling.level_from_xp(total_xp)

        # Rang dans le serveur.
        pos_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS rank FROM levels WHERE guild_id = ? AND xp > ?",
            (interaction.guild.id, total_xp),
        )
        rank = (pos_row["rank"] if pos_row else 0) + 1

        embed = embeds.brand(f"📈 Niveau de {target.display_name}")
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Niveau", value=str(level))
        embed.add_field(name="Rang", value=f"#{rank}")
        embed.add_field(name="XP totale", value=f"{total_xp:,}".replace(",", " "))
        embed.add_field(
            name=f"Progression — {into}/{needed} XP",
            value=leveling.progress_bar(into, needed),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leveltop", description="Classement des niveaux du serveur.")
    @app_commands.guild_only()
    async def leveltop(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT user_id, xp FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT 10",
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Classement vide", "Personne n'a encore d'XP. Discutez un peu !"), ephemeral=True
            )
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(rows):
            member = interaction.guild.get_member(r["user_id"])
            name = member.display_name if member else f"Utilisateur {r['user_id']}"
            lvl, *_ = leveling.level_from_xp(r["xp"])
            tag = medals[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{tag} **{name}** — niveau {lvl} ({r['xp']:,} XP)".replace(",", " "))
        await interaction.response.send_message(embed=embeds.brand("🏆 Top niveaux", "\n".join(lines)))

    # ── Admin : configuration & récompenses ───────────────────────────────────
    levels = app_commands.Group(
        name="levels",
        description="Configuration du système de niveaux",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @levels.command(name="reward", description="Associe un rôle à un palier de niveau (récompense auto).")
    @app_commands.describe(niveau="Niveau requis", role="Rôle à attribuer")
    async def lv_reward(
        self, interaction: discord.Interaction, niveau: app_commands.Range[int, 1, 1000], role: discord.Role
    ) -> None:
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=embeds.error("Rôle trop haut", "Ce rôle est au-dessus du mien, je ne pourrai pas l'attribuer."),
                ephemeral=True,
            )
            return
        await self.bot.db.execute(
            "INSERT INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (interaction.guild.id, niveau, role.id),
        )
        await interaction.response.send_message(
            embed=embeds.success("Récompense définie", f"Niveau {niveau} → {role.mention}."), ephemeral=True
        )

    @levels.command(name="rewards", description="Liste les récompenses de niveau.")
    async def lv_rewards(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT level, role_id FROM level_rewards WHERE guild_id = ? ORDER BY level",
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Aucune récompense", "Ajoute-en avec `/levels reward`."), ephemeral=True
            )
            return
        lines = []
        for r in rows:
            role = interaction.guild.get_role(r["role_id"])
            lines.append(f"Niveau **{r['level']}** → {role.mention if role else 'rôle supprimé'}")
        await interaction.response.send_message(
            embed=embeds.info("Récompenses de niveau", "\n".join(lines)), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Levels(bot))
