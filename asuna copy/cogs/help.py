"""Aide interactive : /help (membres) et /adminhelp (admins).

UI : un embed d'accueil + un menu déroulant pour naviguer entre les catégories,
plus un bouton « Accueil » pour revenir à la page principale. Chaque catégorie
est une page d'embed listant ses commandes.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import checks, embeds

# ── Catalogue des commandes ──────────────────────────────────────────────────
# Structure : clé → { label, emoji, short (description courte du menu),
#                     intro, commands: [(signature, description), …] }

MEMBER_CATEGORIES: dict[str, dict] = {
    "general": {
        "label": "Général",
        "emoji": "📋",
        "short": "Infos & commandes de base",
        "intro": "Les commandes utiles à tout le monde.",
        "commands": [
            ("/help", "Affiche cette aide interactive."),
            ("/adminhelp", "Aide des commandes d'administration (réservé aux admins)."),
            ("/ping", "Vérifie la latence du bot."),
            ("/serverinfo", "Informations sur le serveur."),
            ("/userinfo [membre]", "Informations sur un membre."),
            ("/avatar [membre]", "Affiche l'avatar d'un membre en grand."),
        ],
    },
    "stats": {
        "label": "Statistiques",
        "emoji": "📊",
        "short": "Stats du serveur & dashboard",
        "intro": "Statistiques d'activité et dashboard web (lecture seule).",
        "commands": [
            ("/stats", "Stats du serveur : messages, top bavards, commandes."),
            ("/dashboard", "Lien vers le dashboard web (si activé)."),
        ],
    },
    "interface": {
        "label": "Interface",
        "emoji": "🎨",
        "short": "Démo boutons / menus / formulaires",
        "intro": "Composants interactifs disponibles.",
        "commands": [
            ("/interface", "Démo : boutons, menus déroulants et formulaires."),
        ],
    },
    "economy": {
        "label": "Économie",
        "emoji": "💰",
        "short": "Monnaie, daily, travail, boutique",
        "intro": "Gagne et dépense la monnaie du serveur.",
        "commands": [
            ("/balance [membre]", "Affiche ton solde (liquide + banque)."),
            ("/daily", "Récompense journalière."),
            ("/work", "Travaille pour gagner de l'argent (toutes les heures)."),
            ("/pay <membre> <montant>", "Donne de l'argent à un membre."),
            ("/deposit <montant|all>", "Dépose à la banque."),
            ("/withdraw <montant|all>", "Retire de la banque."),
            ("/baltop", "Classement des plus riches."),
            ("/shop", "Affiche la boutique."),
            ("/buy <objet>", "Achète un article."),
            ("/inventory [membre]", "Affiche un inventaire."),
        ],
    },
    "levels": {
        "label": "Niveaux",
        "emoji": "📈",
        "short": "XP, rang et classement",
        "intro": "Gagne de l'XP en discutant et grimpe les niveaux.",
        "commands": [
            ("/rank [membre]", "Ton niveau, ton XP et ta progression."),
            ("/leveltop", "Classement des niveaux du serveur."),
        ],
    },
    "jeux": {
        "label": "Mini-jeux",
        "emoji": "🎲",
        "short": "Pile/face, quiz, devinette, morpion",
        "intro": "Des jeux rapides ; certains rapportent de l'or.",
        "commands": [
            ("/pileface <choix> <mise>", "Pile ou face avec une mise (50/50)."),
            ("/devine", "Devine le nombre entre 1 et 100."),
            ("/quiz", "Question de culture générale (récompense)."),
            ("/morpion <adversaire>", "Défie un membre au morpion."),
        ],
    },
    "rpg": {
        "label": "RPG / Combat",
        "emoji": "⚔️",
        "short": "Combat façon Undertale",
        "intro": "Affronte des monstres dans une interface façon Undertale "
        "(FIGHT / ACT / ITEM / MERCY).",
        "commands": [
            ("/combat", "Un combat unique : attaque, épargne, gagne de l'or."),
            ("/tour", "Grimpe la Tour roguelite (100 étages, classes, boss, héritage)."),
            ("/blackmarket", "Améliorations permanentes (stats, résurrection)."),
            ("/forge", "Achète et équipe armes & armures."),
            ("/achievements", "Tes succès débloqués."),
            ("/abandon", "Abandonne ton ascension en cours."),
            ("/rpgjournal", "Tes records, ton héritage et tes dernières morts."),
        ],
    },
    "outils": {
        "label": "Outils pratiques",
        "emoji": "🧰",
        "short": "Sondages, rappels, to-do, convertisseur",
        "intro": "Des outils du quotidien pour le serveur.",
        "commands": [
            ("/sondage <question> <options>", "Crée un sondage à boutons (options séparées par `;`)."),
            ("/rappel <durée> <message>", "Programme un rappel (ex: 30m, 2h, 1d)."),
            ("/rappels", "Liste tes rappels en attente."),
            ("/rappelannuler <id>", "Annule un rappel."),
            ("/todo add|list|done|remove|clear", "Ta liste de tâches personnelle."),
            ("/convertir <valeur> <type>", "Convertit températures, distances, poids."),
        ],
    },
    "community": {
        "label": "Communauté",
        "emoji": "🙌",
        "short": "Rôles & vérification",
        "intro": "Fonctionnalités communautaires (configurées par les admins).",
        "commands": [
            ("Vérification", "Clique sur le bouton du salon de vérification pour accéder au serveur."),
            ("Rôles à réaction", "Réagis sur les messages prévus pour obtenir des rôles."),
        ],
    },
}

ADMIN_CATEGORIES: dict[str, dict] = {
    "moderation": {
        "label": "Modération",
        "emoji": "🛡️",
        "short": "Sanctions & avertissements",
        "intro": "Outils de sanction. Nécessite les permissions adéquates.",
        "commands": [
            ("/kick <membre> [raison]", "Expulse un membre."),
            ("/ban <membre> [raison] [jours]", "Bannit un membre."),
            ("/unban <user_id> [raison]", "Révoque un bannissement."),
            ("/timeout <membre> <durée> [raison]", "Isole un membre (ex: 10m, 1h)."),
            ("/untimeout <membre>", "Lève un timeout."),
            ("/mute <membre> [raison]", "Applique le rôle muet configuré."),
            ("/unmute <membre>", "Retire le rôle muet."),
            ("/warn <membre> <raison>", "Avertit un membre."),
            ("/warns <membre>", "Liste les avertissements."),
            ("/clearwarns <membre>", "Efface les avertissements."),
            ("/purge <nombre> [membre]", "Supprime des messages en masse."),
        ],
    },
    "automod": {
        "label": "AutoMod",
        "emoji": "🚨",
        "short": "Se configure dans le panneau !config",
        "intro": "Modération automatique. **Réglages dans le panneau `!config` → section 🚨 AutoMod** : "
        "anti-spam, anti-liens, anti-invitations, anti-raid, max mentions, mots interdits.",
        "commands": [
            ("!config → 🚨 AutoMod", "Active/désactive les protections et gère les mots interdits."),
        ],
    },
    "logs": {
        "label": "Logs",
        "emoji": "📜",
        "short": "Salons de logs (suivis par ID)",
        "intro": "Création et suivi des salons de logs. Les salons sont suivis par "
        "ID : tu peux les renommer sans rien casser.",
        "commands": [
            ("/setup-log (ou !setup-log)", "Crée la catégorie + les salons de logs (asuna-messages, -membres, -moderation, -bot)."),
            ("#asuna-bot", "Salon où le bot signale ses incidents (commandes échouées, permissions manquantes…)."),
        ],
    },
    "config": {
        "label": "Configuration",
        "emoji": "⚙️",
        "short": "Panneau interactif (!config)",
        "intro": "Tape **`!config`** : un **panneau interactif** s'ouvre (menu de "
        "sections + sélecteurs + boutons). Les boutons ouvrent des **pop-ups** pour "
        "personnaliser messages et images (bienvenue, départ, panneau de ticket…).",
        "commands": [
            ("!config", "Ouvre le panneau de configuration interactif (8 sections)."),
            ("🏠 Général / 🎭 Rôles", "Préfixe, salon de logs, rôles muet/vérif/auto."),
            ("👋 Bienvenue / 🎫 Tickets", "Messages + **images** (pop-up), panneau de ticket personnalisé."),
            ("🚨 AutoMod / 📈 Niveaux", "Interrupteurs anti-spam/liens/raid, XP, annonces…"),
            ("🔐 Sécurité / 💰 Économie", "Anti-nuke, monnaie, daily."),
            ("Raccourcis texte", "`!config prefix|logchannel|muterole|verifyrole|autorole`."),
        ],
    },
    "economy": {
        "label": "Économie & Niveaux",
        "emoji": "💰",
        "short": "Boutique, monnaie, paramètres XP",
        "intro": "Gestion économie/niveaux. Devise, daily, XP et annonces se règlent "
        "dans **`!config`** (sections 💰 Économie / 📈 Niveaux).",
        "commands": [
            ("/shopadmin add <nom> <prix> [desc] [rôle]", "Ajoute un article (rôle optionnel)."),
            ("/shopadmin remove <nom>", "Retire un article."),
            ("/eco give <membre> <montant>", "Crédite de l'argent à un membre."),
            ("/eco take <membre> <montant>", "Retire de l'argent à un membre."),
            ("/levels reward <niveau> <rôle>", "Récompense de rôle par palier."),
            ("/levels rewards", "Liste les récompenses de niveau."),
            ("💰/📈 dans !config", "Monnaie, daily, gain d'XP, annonces."),
        ],
    },
    "tickets": {
        "label": "Support / Tickets",
        "emoji": "🎫",
        "short": "Salons d'assistance privés",
        "intro": "Système de tickets. **Catégorie, staff et transcripts se règlent dans "
        "`!config` → section 🎫 Tickets** (avec panneau personnalisable + image).",
        "commands": [
            ("/ticket panel <salon>", "Poste le bouton d'ouverture de tickets."),
            ("/ticket add|remove <membre>", "Ajoute/retire un membre du ticket courant."),
            ("/ticket close", "Ferme le ticket courant (ou via le bouton 🔒)."),
            ("Réglages : !config → 🎫 Tickets", "Catégorie, rôle staff, transcripts, panneau."),
        ],
    },
    "security": {
        "label": "Sécurité & Backups",
        "emoji": "🔐",
        "short": "Anti-nuke, blacklist, lockdown, sauvegardes",
        "intro": "Protection avancée et sauvegarde du serveur. **L'anti-nuke se règle dans "
        "`!config` → section 🔐 Sécurité.**",
        "commands": [
            ("/security whitelist <add/remove> <membre>", "Membre de confiance (exempté anti-nuke)."),
            ("/security blacklist <add/remove/list> [id] [raison]", "Bannit automatiquement à l'arrivée."),
            ("/lockdown [raison] · /unlock", "Verrouille/déverrouille tous les salons (urgence)."),
            ("/backup create|list|restore|delete", "Sauvegarde/restaure rôles, salons, permissions."),
            ("/dbbackup", "(Propriétaire) Copie de la base de données en DM."),
            ("Anti-nuke : !config → 🔐 Sécurité", "Activer, sanction, seuil/fenêtre."),
        ],
    },
    "verification": {
        "label": "Vérification",
        "emoji": "✅",
        "short": "Panneau anti-bot",
        "intro": "Filtrage des nouveaux membres par bouton.",
        "commands": [
            ("/verifysetup <salon>", "Poste le panneau de vérification (rôle via !config verifyrole)."),
        ],
    },
    "roles": {
        "label": "Rôles à réaction",
        "emoji": "🎭",
        "short": "Emoji → rôle",
        "intro": "Attribue des rôles via des réactions emoji.",
        "commands": [
            ("/reactionrole add <message_id> <emoji> <rôle>", "Crée une association."),
            ("/reactionrole remove <message_id> <emoji>", "Supprime une association."),
            ("/reactionrole list", "Liste les rôles à réaction."),
        ],
    },
    "custom": {
        "label": "Réponses auto",
        "emoji": "✍️",
        "short": "Réponses automatiques à mots-clés",
        "intro": "Fais réagir le bot à des mots-clés.",
        "commands": [
            ("/autoresponse add <déclencheur> <réponse> [type]", "Réponse auto à un mot-clé."),
            ("/autoresponse remove <id>", "Supprime une réponse auto."),
            ("/autoresponse list", "Liste les réponses auto."),
        ],
    },
}

# Commandes en préfixe « ! » (hybrides/préfixe) — affichées dans /help ET /adminhelp.
_PREFIX_CATEGORY: dict = {
    "label": "Commandes ! (préfixe)",
    "emoji": "⌨️",
    "short": "Commandes hybrides / préfixe",
    "intro": "Ces commandes s'utilisent avec le préfixe **!** (et non le slash). "
    "Réservées aux administrateurs.",
    "commands": [
        ("!config", "Ouvre le **panneau de configuration interactif** (pop-ups, images)."),
        ("!setup-log", "Crée la catégorie + salons de logs (aussi en `/setup-log`)."),
        ("!config prefix <préfixe>", "Raccourci : change le préfixe."),
        ("!config logchannel <#salon>", "Raccourci : salon de logs."),
        ("!config muterole <@rôle>", "Raccourci : rôle muet."),
        ("!config verifyrole <@rôle>", "Raccourci : rôle de vérification."),
        ("!config autorole <@rôle>", "Raccourci : rôle auto."),
    ],
}

# Disponible dans les deux aides.
MEMBER_CATEGORIES["prefixe"] = _PREFIX_CATEGORY
ADMIN_CATEGORIES["prefixe"] = _PREFIX_CATEGORY


def _home_embed(categories: dict[str, dict], titre: str, sous_titre: str) -> discord.Embed:
    """Construit la page d'accueil listant toutes les catégories."""
    embed = embeds.brand(titre, sous_titre)
    embed.set_footer(text="Asuna • Utilise le menu déroulant ci-dessous")
    for cat in categories.values():
        # Aperçu des commandes : premiers mots, dédupliqués (ex: !config affiché une fois).
        tokens = []
        for sig, _ in cat["commands"]:
            tok = sig.split()[0]
            if tok not in tokens:
                tokens.append(tok)
        cmds = "  ".join(f"`{t}`" for t in tokens[:6])
        embed.add_field(
            name=f"{cat['emoji']} {cat['label']}",
            value=f"{cat['short']}\n{cmds}",
            inline=False,
        )
    return embed


def _category_embed(cat: dict) -> discord.Embed:
    """Construit la page d'une catégorie listant ses commandes."""
    embed = embeds.brand(f"{cat['emoji']} {cat['label']}", cat["intro"])
    for sig, desc in cat["commands"]:
        embed.add_field(name=sig, value=desc, inline=False)
    embed.set_footer(text="Asuna • « Accueil » pour revenir")
    return embed


class _CategorySelect(discord.ui.Select):
    def __init__(self, categories: dict[str, dict]) -> None:
        self.categories = categories
        options = [
            discord.SelectOption(
                label=cat["label"], value=key, emoji=cat["emoji"], description=cat["short"]
            )
            for key, cat in categories.items()
        ]
        super().__init__(placeholder="📂 Choisis une catégorie…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        cat = self.categories[self.values[0]]
        await interaction.response.edit_message(embed=_category_embed(cat), view=self.view)


class HelpView(discord.ui.View):
    """Menu d'aide : sélecteur de catégorie + bouton d'accueil. Privé à l'auteur."""

    def __init__(self, author_id: int, categories: dict[str, dict], home: discord.Embed) -> None:
        super().__init__(timeout=180)
        self.author_id = author_id
        self.home = home
        self.message: discord.Message | None = None
        self.add_item(_CategorySelect(categories))

    @discord.ui.button(label="Accueil", emoji="🏠", style=discord.ButtonStyle.secondary, row=1)
    async def accueil(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=self.home, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=embeds.info("Menu privé", "Lance la commande toi-même pour naviguer."), ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Affiche l'aide des commandes membres.")
    async def help(self, interaction: discord.Interaction) -> None:
        home = _home_embed(
            MEMBER_CATEGORIES,
            "📖 Aide d'Asuna",
            f"Salut {interaction.user.mention} ! Voici les commandes disponibles.\n"
            "Choisis une catégorie dans le menu déroulant ci-dessous. 👇",
        )
        view = HelpView(interaction.user.id, MEMBER_CATEGORIES, home)
        await interaction.response.send_message(embed=home, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="adminhelp", description="Affiche l'aide des commandes d'administration.")
    @app_commands.guild_only()
    @checks.is_admin()
    async def adminhelp(self, interaction: discord.Interaction) -> None:
        home = _home_embed(
            ADMIN_CATEGORIES,
            "🛠️ Aide Administration — Asuna",
            "Commandes réservées au staff. Choisis une catégorie dans le menu ci-dessous. 👇",
        )
        view = HelpView(interaction.user.id, ADMIN_CATEGORIES, home)
        await interaction.response.send_message(embed=home, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
