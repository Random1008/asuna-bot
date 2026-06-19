"""AutoMod : anti-spam, anti-liens/invitations, anti-mentions, blacklist de mots,
et anti-raid. Tout est configurable par serveur.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from core import checks, embeds, log_router

# Détection de liens et d'invitations Discord.
_LINK_RE = re.compile(r"https?://", re.IGNORECASE)
_INVITE_RE = re.compile(r"(discord\.gg/|discord(app)?\.com/invite/)", re.IGNORECASE)

# Anti-spam : fenêtre glissante.
_SPAM_WINDOW = 5.0     # secondes
_SPAM_LIMIT = 5        # messages max dans la fenêtre


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # {(guild_id, user_id): deque[timestamps]}
        self._msg_times: dict[tuple[int, int], deque] = defaultdict(deque)
        # Anti-raid : {guild_id: deque[join_timestamps]}
        self._join_times: dict[int, deque] = defaultdict(deque)
        self._raid_mode: dict[int, float] = {}  # guild_id -> fin du mode raid (ts)

    # ── Utilitaires ─────────────────────────────────────────────────────────
    async def _log(self, guild: discord.Guild, embed: discord.Embed) -> None:
        await log_router.send_log(self.bot, guild, "mod", embed)

    async def _punish(self, message: discord.Message, motif: str) -> None:
        """Supprime le message fautif et prévient brièvement l'auteur."""
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            warn = embeds.warning("AutoMod", f"{message.author.mention}, ton message a été supprimé : **{motif}**.")
            await message.channel.send(embed=warn, delete_after=6)
        except discord.HTTPException:
            pass
        await self._log(
            message.guild,
            embeds.mod("AutoMod — message supprimé",
                       f"**Auteur :** {message.author.mention}\n**Motif :** {motif}\n**Salon :** {message.channel.mention}"),
        )

    # ── Filtrage des messages ───────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        # Les modérateurs échappent à l'automod.
        if isinstance(message.author, discord.Member) and message.author.guild_permissions.manage_messages:
            return

        cfg = await self.bot.config.get(message.guild.id)
        content = message.content or ""

        # 1) Anti-liens / invitations
        if cfg.get("anti_invites") and _INVITE_RE.search(content):
            await self._punish(message, "invitation Discord interdite")
            return
        if cfg.get("anti_links") and _LINK_RE.search(content):
            await self._punish(message, "lien interdit")
            return

        # 2) Anti-mentions de masse
        max_mentions = cfg.get("max_mentions") or 0
        if max_mentions and len(message.mentions) > max_mentions:
            await self._punish(message, f"trop de mentions (> {max_mentions})")
            return

        # 3) Blacklist de mots
        bad = await self._matches_blacklist(message.guild.id, content)
        if bad:
            await self._punish(message, f"mot interdit (`{bad}`)")
            return

        # 4) Anti-spam (fréquence)
        if cfg.get("anti_spam"):
            key = (message.guild.id, message.author.id)
            now = time.monotonic()
            dq = self._msg_times[key]
            dq.append(now)
            while dq and now - dq[0] > _SPAM_WINDOW:
                dq.popleft()
            if len(dq) > _SPAM_LIMIT:
                dq.clear()
                await self._punish(message, "spam détecté")
                try:
                    # 5 minutes de timeout pour calmer le spammeur.
                    await message.author.timeout(timedelta(minutes=5), reason="AutoMod : spam")
                except discord.HTTPException:
                    pass
                return

    async def _matches_blacklist(self, guild_id: int, content: str) -> str | None:
        rows = await self.bot.db.fetchall(
            "SELECT word FROM blacklist_words WHERE guild_id = ?", (guild_id,)
        )
        lowered = content.lower()
        for r in rows:
            if r["word"].lower() in lowered:
                return r["word"]
        return None

    # ── Anti-raid ───────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        cfg = await self.bot.config.get(member.guild.id)
        if not cfg.get("antiraid_enabled"):
            return
        threshold = cfg.get("antiraid_threshold") or 5
        window = cfg.get("antiraid_window") or 10
        now = time.monotonic()
        dq = self._join_times[member.guild.id]
        dq.append(now)
        while dq and now - dq[0] > window:
            dq.popleft()

        # Déclenche / prolonge le mode raid si le seuil est franchi.
        if len(dq) >= threshold:
            self._raid_mode[member.guild.id] = now + window
            await self._log(
                member.guild,
                embeds.error("🚨 Anti-raid déclenché",
                             f"{len(dq)} arrivées en {window}s. Les nouveaux membres sont expulsés temporairement."),
            )

        # Si on est en mode raid, on expulse le membre qui vient d'arriver.
        if now < self._raid_mode.get(member.guild.id, 0):
            try:
                await member.kick(reason="AutoMod anti-raid : vague d'arrivées suspecte")
            except discord.HTTPException:
                pass



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoMod(bot))
