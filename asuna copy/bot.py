"""Point d'entrée du bot Asuna.

Définit la sous-classe AsunaBot (gestion DB + config + chargement des cogs +
synchro des slash commands + handler d'erreurs global) puis lance le bot.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core import embeds, log_router
from core.config_store import ConfigStore
from core.database import Database
from core.logger import setup_logger

# Liste des modules (cogs) chargés au démarrage. Ajouter un module = ajouter
# une ligne ici après avoir déposé le fichier dans cogs/.
INITIAL_COGS = [
    "cogs.help",
    "cogs.general",
    "cogs.moderation",
    "cogs.automod",
    "cogs.logs",
    "cogs.logsetup",
    "cogs.settings",
    "cogs.verification",
    "cogs.autoroles",
    "cogs.custom",
    "cogs.interface",
    "cogs.economy",
    "cogs.levels",
    "cogs.rpg",
    "cogs.tickets",
    "cogs.tools",
    "cogs.stats",
    "cogs.games",
    "cogs.security",
    "cogs.backups",
]


async def _get_prefix(bot: "AsunaBot", message: discord.Message):
    """Préfixe dynamique par serveur (+ mention du bot)."""
    default = Config.DEFAULT_PREFIX
    prefix = default
    if message.guild is not None:
        cfg = await bot.config.get(message.guild.id)
        prefix = cfg.get("prefix") or default
    return commands.when_mentioned_or(prefix)(bot, message)


class AsunaBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # nécessaire pour automod / commandes texte
        intents.members = True          # nécessaire pour join/leave, rôles auto

        super().__init__(
            command_prefix=_get_prefix,
            intents=intents,
            help_command=None,  # on fournit notre propre /help stylé
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )

        self.log = setup_logger()
        self.db = Database(Config.DB_PATH)
        self.config = ConfigStore(self.db)
        self.start_time = discord.utils.utcnow()
        self._dashboard_runner = None

    async def setup_hook(self) -> None:
        """Appelé automatiquement avant la connexion : init DB, cogs, synchro."""
        await self.db.connect()
        self.log.info("Base de données initialisée (%s)", Config.DB_PATH)

        for cog in INITIAL_COGS:
            try:
                await self.load_extension(cog)
                self.log.info("Cog chargé : %s", cog)
            except Exception:
                self.log.exception("Échec du chargement du cog %s", cog)

        # Vues persistantes (boutons qui survivent à un redémarrage).
        from cogs.verification import VerificationView
        from cogs.tickets import TicketControlView, TicketPanelView
        self.add_view(VerificationView())
        self.add_view(TicketPanelView())
        self.add_view(TicketControlView())

        # Réenregistre les sondages encore ouverts pour que leurs boutons marchent.
        from cogs.tools import register_open_polls
        await register_open_polls(self)

        # Démarre le dashboard web si activé.
        if Config.DASHBOARD_ENABLED:
            try:
                from core.dashboard import start_dashboard
                self._dashboard_runner = await start_dashboard(self, Config.DASHBOARD_HOST, Config.DASHBOARD_PORT)
                self.log.info("Dashboard web démarré sur %s:%s", Config.DASHBOARD_HOST, Config.DASHBOARD_PORT)
            except Exception:
                self.log.exception("Échec du démarrage du dashboard")

        # Handler d'erreurs global pour toutes les slash commands.
        self.tree.on_error = self.on_app_command_error

        # Synchro des commandes : instantanée sur le serveur de dev si défini.
        if Config.DEV_GUILD_ID:
            guild = discord.Object(id=Config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            self.log.info("Slash commands synchronisées sur le serveur de dev (%d).", len(synced))
        else:
            synced = await self.tree.sync()
            self.log.info("Slash commands synchronisées globalement (%d).", len(synced))

    async def on_ready(self) -> None:
        self.log.info("Connecté en tant que %s (id=%s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="/help • la communauté"
            )
        )

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Transforme les erreurs en réponses propres (et logue les vraies bugs)."""
        # report = True → on signale aussi l'incident dans #asuna-bot.
        report = False
        if isinstance(error, app_commands.MissingPermissions):
            msg = "Tu n'as pas les permissions nécessaires pour cette commande."
        elif isinstance(error, app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            msg = f"Il me manque des permissions : `{perms}`."
            report = True
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"Doucement ! Réessaie dans {error.retry_after:.1f}s."
        elif isinstance(error, app_commands.CheckFailure):
            msg = "Tu ne peux pas utiliser cette commande ici."
        else:
            self.log.exception("Erreur non gérée dans une commande", exc_info=error)
            msg = "Une erreur inattendue est survenue. Les développeurs ont été notifiés."
            report = True

        # Signale l'incident dans le salon système du serveur, si configuré.
        if report and interaction.guild is not None:
            cmd = interaction.command.qualified_name if interaction.command else "inconnue"
            await log_router.report_problem(
                self,
                interaction.guild,
                "Incident de commande",
                f"**Commande :** `/{cmd}`\n"
                f"**Utilisateur :** {interaction.user.mention}\n"
                f"**Type :** `{type(error).__name__}`\n"
                f"**Détail :** {str(error)[:500] or '—'}",
            )

        embed = embeds.error("Oups", msg)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            pass  # l'interaction a expiré, rien à faire

    async def close(self) -> None:
        """Arrêt propre : dashboard + base de données."""
        if self._dashboard_runner is not None:
            await self._dashboard_runner.cleanup()
        await self.db.close()
        await super().close()


def main() -> None:
    Config.validate()
    bot = AsunaBot()
    # log_handler=None : on gère nous-mêmes les logs via core/logger.py
    bot.run(Config.TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
