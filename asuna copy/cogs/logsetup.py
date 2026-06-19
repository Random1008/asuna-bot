"""Mise en place automatique des salons de logs.

`!setup-log` (ou `/setup-log`) crée une catégorie privée « Asuna • Logs » et les
salons de suivi. Tout est mémorisé par **ID** : renommer un salon plus tard n'a
aucun impact. La commande est idempotente — la relancer répare les salons
manquants au lieu de tout recréer.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import embeds

# Salons à créer : (clé de config, nom par défaut, description du sujet).
_LOG_CHANNELS = [
    ("log_messages_channel_id", "asuna-messages", "Messages supprimés et édités"),
    ("log_members_channel_id", "asuna-membres", "Arrivées et départs de membres"),
    ("log_mod_channel_id", "asuna-moderation", "Actions de modération et AutoMod"),
    ("log_system_channel_id", "asuna-bot", "Incidents du bot (erreurs, permissions…)"),
]


class LogSetup(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _ensure_category(
        self, guild: discord.Guild, cfg: dict
    ) -> discord.CategoryChannel:
        """Récupère la catégorie de logs existante (par ID) ou la crée (privée)."""
        cat = guild.get_channel(cfg.get("log_category_id")) if cfg.get("log_category_id") else None
        if isinstance(cat, discord.CategoryChannel):
            return cat
        # Catégorie cachée à @everyone, visible par le bot.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        cat = await guild.create_category(
            "Asuna • Logs", overwrites=overwrites, reason="Setup des logs Asuna"
        )
        await self.bot.config.set(guild.id, "log_category_id", cat.id)
        return cat

    async def _ensure_channels(
        self, guild: discord.Guild, category: discord.CategoryChannel, cfg: dict
    ) -> list[tuple[str, discord.TextChannel, bool]]:
        """Garantit l'existence de chaque salon. Retourne (clé_config, salon, créé?)."""
        results = []
        for key, default_name, topic in _LOG_CHANNELS:
            existing = guild.get_channel(cfg.get(key)) if cfg.get(key) else None
            if isinstance(existing, discord.TextChannel):
                results.append((key, existing, False))
                continue
            channel = await guild.create_text_channel(
                default_name, category=category, topic=topic, reason="Setup des logs Asuna"
            )
            await self.bot.config.set(guild.id, key, channel.id)
            results.append((key, channel, True))
        return results

    @commands.hybrid_command(
        name="setup-log",
        description="Crée la catégorie et les salons de logs (suivis par ID).",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def setup_log(self, ctx: commands.Context) -> None:
        # Vérifie que le bot peut gérer les salons.
        if not ctx.guild.me.guild_permissions.manage_channels:
            await ctx.reply(
                embed=embeds.error(
                    "Permission manquante",
                    "J'ai besoin de la permission **Gérer les salons** pour créer les logs.",
                )
            )
            return

        # defer : la création de salons peut prendre quelques secondes.
        async with ctx.typing():
            cfg = await self.bot.config.get(ctx.guild.id)
            category = await self._ensure_category(ctx.guild, cfg)
            cfg = await self.bot.config.get(ctx.guild.id)  # rafraîchit après création
            channels = await self._ensure_channels(ctx.guild, category, cfg)

        # Récapitulatif.
        created = sum(1 for *_, was_created in channels if was_created)
        lines = []
        for _key, channel, was_created in channels:
            tag = "🆕 créé" if was_created else "✅ existant"
            lines.append(f"{tag} — {channel.mention}")
        embed = embeds.success(
            "Logs configurés",
            f"Catégorie {category.mention} prête.\n"
            f"{created} salon(s) créé(s), {len(channels) - created} réutilisé(s).\n\n"
            + "\n".join(lines),
        )
        embed.add_field(
            name="Bon à savoir",
            value="Les salons sont suivis par **ID** : tu peux les renommer ou les "
            "déplacer librement, le suivi continue. Le salon `asuna-bot` reçoit les "
            "incidents techniques du bot.",
            inline=False,
        )
        await ctx.reply(embed=embed)

        # Message d'amorçage dans le salon système (#asuna-bot).
        system = next((ch for key, ch, _ in channels if key == "log_system_channel_id"), None)
        if isinstance(system, discord.TextChannel):
            try:
                await system.send(
                    embed=embeds.info(
                        "Salon d'incidents actif",
                        "Je signalerai ici tout problème : commande échouée, permission "
                        "manquante, erreur inattendue…",
                    )
                )
            except discord.HTTPException:
                pass

    @setup_log.error
    async def setup_log_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Réponses propres pour les erreurs de cette commande (préfixe)."""
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply(
                embed=embeds.error("Accès refusé", "Tu dois être administrateur pour utiliser cette commande.")
            )
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.reply(
                embed=embeds.error("Permission manquante", "Il me manque la permission **Gérer les salons**.")
            )
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.reply(embed=embeds.error("Serveur uniquement", "Cette commande s'utilise sur un serveur."))
        else:
            self.bot.log.exception("Erreur dans setup-log", exc_info=error)
            await ctx.reply(embed=embeds.error("Oups", "Une erreur est survenue pendant la configuration."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LogSetup(bot))
