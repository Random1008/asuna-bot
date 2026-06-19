"""Configuration du serveur via un panneau interactif unique : `!config`.

`!config` poste un panneau (menu de sections + sélecteurs natifs + interrupteurs
+ boutons). Les boutons ouvrent des **pop-ups (modals)** pour personnaliser les
messages, images (URL), devises et seuils. Couvre : Général, Rôles, Bienvenue,
Tickets, AutoMod, Niveaux, Sécurité, Économie.

Les raccourcis texte (`!config logchannel #x`…) restent disponibles.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from core import embeds

_TEXT = [discord.ChannelType.text]
_CATEGORY = [discord.ChannelType.category]


# ── Pop-ups (modals) ──────────────────────────────────────────────────────────
class PrefixModal(discord.ui.Modal, title="Changer le préfixe"):
    value = discord.ui.TextInput(label="Nouveau préfixe (max 5)", max_length=5)

    def __init__(self, panel) -> None:
        super().__init__()
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.panel.save(interaction, {"prefix": str(self.value)})


class MessageModal(discord.ui.Modal):
    """Message (avec variables) + URL d'image."""

    def __init__(self, panel, titre, msg_key, img_key, cur_msg, cur_img) -> None:
        super().__init__(title=titre)
        self.panel, self.msg_key, self.img_key = panel, msg_key, img_key
        self.message = discord.ui.TextInput(
            label="Message", style=discord.TextStyle.paragraph, required=False, max_length=1500,
            default=cur_msg or "", placeholder="Variables : {membre}, {serveur}")
        self.image = discord.ui.TextInput(
            label="URL d'une image (optionnel)", required=False, default=cur_img or "", placeholder="https://...")
        self.add_item(self.message)
        self.add_item(self.image)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.panel.save(interaction, {
            self.msg_key: str(self.message) or None, self.img_key: str(self.image) or None})


class TicketPanelModal(discord.ui.Modal, title="Panneau de ticket"):
    def __init__(self, panel, cur_t, cur_m, cur_i) -> None:
        super().__init__()
        self.panel = panel
        self.titre = discord.ui.TextInput(label="Titre", required=False, max_length=100, default=cur_t or "")
        self.msg = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph,
                                        required=False, max_length=1000, default=cur_m or "")
        self.image = discord.ui.TextInput(label="URL d'image (optionnel)", required=False, default=cur_i or "")
        for item in (self.titre, self.msg, self.image):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.panel.save(interaction, {
            "ticket_panel_title": str(self.titre) or None,
            "ticket_panel_message": str(self.msg) or None,
            "ticket_panel_image": str(self.image) or None})


class NumberModal(discord.ui.Modal):
    """Saisit un entier pour une clé de config."""

    def __init__(self, panel, titre, key, label, cur) -> None:
        super().__init__(title=titre)
        self.panel, self.key = panel, key
        self.field = discord.ui.TextInput(label=label, default=str(cur if cur is not None else ""), max_length=9)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = int(str(self.field))
        except ValueError:
            await interaction.response.send_message(embed=embeds.error("Invalide", "Entre un nombre entier."), ephemeral=True)
            return
        await self.panel.save(interaction, {self.key: max(0, value)})


class TwoNumberModal(discord.ui.Modal):
    """Deux entiers (ex: seuil + fenêtre)."""

    def __init__(self, panel, titre, k1, l1, c1, k2, l2, c2) -> None:
        super().__init__(title=titre)
        self.panel, self.k1, self.k2 = panel, k1, k2
        self.f1 = discord.ui.TextInput(label=l1, default=str(c1 if c1 is not None else ""), max_length=6)
        self.f2 = discord.ui.TextInput(label=l2, default=str(c2 if c2 is not None else ""), max_length=6)
        self.add_item(self.f1)
        self.add_item(self.f2)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            v1, v2 = int(str(self.f1)), int(str(self.f2))
        except ValueError:
            await interaction.response.send_message(embed=embeds.error("Invalide", "Entre des nombres entiers."), ephemeral=True)
            return
        await self.panel.save(interaction, {self.k1: max(1, v1), self.k2: max(1, v2)})


class BlacklistWordModal(discord.ui.Modal):
    def __init__(self, panel, add: bool) -> None:
        super().__init__(title="Ajouter un mot interdit" if add else "Retirer un mot interdit")
        self.panel, self.add = panel, add
        self.word = discord.ui.TextInput(label="Mot", max_length=100)
        self.add_item(self.word)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        w = str(self.word).lower().strip()
        if self.add:
            await self.panel.bot.db.execute(
                "INSERT OR IGNORE INTO blacklist_words (guild_id, word) VALUES (?, ?)", (self.panel.guild.id, w))
        else:
            await self.panel.bot.db.execute(
                "DELETE FROM blacklist_words WHERE guild_id = ? AND word = ?", (self.panel.guild.id, w))
        await self.panel.refresh(interaction)


class CurrencyModal(discord.ui.Modal, title="Monnaie du serveur"):
    def __init__(self, panel, cur_sym, cur_name) -> None:
        super().__init__()
        self.panel = panel
        self.sym = discord.ui.TextInput(label="Symbole / emoji", default=cur_sym or "🪙", max_length=10)
        self.name = discord.ui.TextInput(label="Nom de la monnaie", default=cur_name or "pièces", max_length=30)
        self.add_item(self.sym)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.panel.save(interaction, {"currency_symbol": str(self.sym), "currency_name": str(self.name)})


# ── Composants génériques ─────────────────────────────────────────────────────
class _ChannelSetter(discord.ui.ChannelSelect):
    def __init__(self, panel, key, placeholder, types, row) -> None:
        super().__init__(channel_types=types, placeholder=placeholder, min_values=1, max_values=1, row=row)
        self.panel, self.key = panel, key

    async def callback(self, interaction):
        await self.panel.save(interaction, {self.key: self.values[0].id})


class _RoleSetter(discord.ui.RoleSelect):
    def __init__(self, panel, key, placeholder, row) -> None:
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, row=row)
        self.panel, self.key = panel, key

    async def callback(self, interaction):
        await self.panel.save(interaction, {self.key: self.values[0].id})


class _Toggle(discord.ui.Button):
    """Interrupteur ON/OFF pour une clé booléenne (0/1)."""

    def __init__(self, panel, key, label, row) -> None:
        on = bool(panel.cfg.get(key))
        super().__init__(label=f"{label} : {'ON' if on else 'OFF'}", emoji="✅" if on else "❌",
                         style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary, row=row)
        self.panel, self.key = panel, key

    async def callback(self, interaction):
        await self.panel.save(interaction, {self.key: 0 if self.panel.cfg.get(self.key) else 1})


class _ActionSelect(discord.ui.Select):
    def __init__(self, panel) -> None:
        cur = panel.cfg.get("antinuke_action") or "strip"
        options = [
            discord.SelectOption(label="Retirer les rôles", value="strip", default=cur == "strip"),
            discord.SelectOption(label="Expulser", value="kick", default=cur == "kick"),
            discord.SelectOption(label="Bannir", value="ban", default=cur == "ban"),
        ]
        super().__init__(placeholder="Sanction anti-nuke", options=options, row=1)
        self.panel = panel

    async def callback(self, interaction):
        await self.panel.save(interaction, {"antinuke_action": self.values[0]})


class _SectionSelect(discord.ui.Select):
    def __init__(self, panel) -> None:
        self.panel = panel
        opts = [
            ("general", "Général", "🏠", "Préfixe, salon de logs"),
            ("roles", "Rôles", "🎭", "Muet, vérification, auto"),
            ("welcome", "Bienvenue & Départ", "👋", "Salon, messages, images"),
            ("tickets", "Tickets", "🎫", "Catégorie, staff, panneau"),
            ("automod", "AutoMod", "🚨", "Anti-spam/liens/raid, mentions"),
            ("levels", "Niveaux", "📈", "XP, annonces, salon"),
            ("security", "Sécurité", "🔐", "Anti-nuke"),
            ("economy", "Économie", "💰", "Monnaie, daily"),
        ]
        options = [discord.SelectOption(label=l, value=v, emoji=e, description=d, default=panel.section == v)
                   for v, l, e, d in opts]
        super().__init__(placeholder="📂 Choisis une section à configurer…", options=options, row=0)

    async def callback(self, interaction):
        self.panel.section = self.values[0]
        await self.panel.refresh(interaction)


# ── Panneau ───────────────────────────────────────────────────────────────────
class ConfigPanel(discord.ui.View):
    def __init__(self, bot, author_id: int, guild: discord.Guild) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = author_id
        self.guild = guild
        self.section = "general"
        self.cfg: dict = {}
        self.blacklist: list[str] = []
        self.message: discord.Message | None = None
        self.build()

    async def interaction_check(self, interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                embed=embeds.info("Panneau privé", "Lance le tien avec `!config`."), ephemeral=True)
            return False
        return True

    async def reload(self) -> None:
        self.cfg = await self.bot.config.get(self.guild.id)
        rows = await self.bot.db.fetchall(
            "SELECT word FROM blacklist_words WHERE guild_id = ? ORDER BY word", (self.guild.id,))
        self.blacklist = [r["word"] for r in rows]

    def _btn(self, label, emoji, cb, row=4):
        b = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary, row=row)
        b.callback = cb
        return b

    def build(self) -> None:
        self.clear_items()
        self.add_item(_SectionSelect(self))
        s = self.section
        if s == "general":
            self.add_item(_ChannelSetter(self, "log_channel_id", "Salon de logs général", _TEXT, 1))
            self.add_item(self._btn("Préfixe", "⌨️", self._open_prefix))
            self.add_item(self._btn("Créer les salons de logs", "📁", self._create_logs))
        elif s == "roles":
            self.add_item(_RoleSetter(self, "mute_role_id", "Rôle muet (/mute)", 1))
            self.add_item(_RoleSetter(self, "verify_role_id", "Rôle de vérification", 2))
            self.add_item(_RoleSetter(self, "autorole_id", "Rôle auto à l'arrivée", 3))
        elif s == "welcome":
            self.add_item(_ChannelSetter(self, "welcome_channel_id", "Salon de bienvenue/départ", _TEXT, 1))
            self.add_item(self._btn("Message de bienvenue", "👋", self._open_welcome))
            self.add_item(self._btn("Message de départ", "🚪", self._open_leave))
        elif s == "tickets":
            self.add_item(_ChannelSetter(self, "ticket_category_id", "Catégorie des tickets", _CATEGORY, 1))
            self.add_item(_RoleSetter(self, "ticket_staff_role_id", "Rôle staff", 2))
            self.add_item(_ChannelSetter(self, "ticket_log_channel_id", "Salon des transcripts", _TEXT, 3))
            self.add_item(self._btn("Personnaliser le panneau", "✏️", self._open_ticket_panel))
            self.add_item(self._btn("Poster le panneau ici", "📨", self._post_ticket_panel))
        elif s == "automod":
            self.add_item(_Toggle(self, "anti_spam", "Anti-spam", 1))
            self.add_item(_Toggle(self, "anti_links", "Anti-liens", 1))
            self.add_item(_Toggle(self, "anti_invites", "Anti-invit.", 1))
            self.add_item(_Toggle(self, "antiraid_enabled", "Anti-raid", 2))
            self.add_item(self._btn("Seuils anti-raid", "🛡️", self._open_antiraid, row=2))
            self.add_item(self._btn("Max mentions", "📢", self._open_maxmentions, row=2))
            self.add_item(self._btn("Ajouter un mot interdit", "🚫", self._open_bl_add, row=3))
            self.add_item(self._btn("Retirer un mot interdit", "♻️", self._open_bl_remove, row=3))
        elif s == "levels":
            self.add_item(_ChannelSetter(self, "levelup_channel_id", "Salon d'annonce des niveaux", _TEXT, 1))
            self.add_item(_Toggle(self, "xp_enabled", "Gain d'XP", 2))
            self.add_item(_Toggle(self, "levelup_announce", "Annonces", 2))
        elif s == "security":
            self.add_item(_ActionSelect(self))
            self.add_item(_Toggle(self, "antinuke_enabled", "Anti-nuke", 2))
            self.add_item(self._btn("Seuil / fenêtre", "🚨", self._open_antinuke, row=2))
        elif s == "economy":
            self.add_item(self._btn("Monnaie (symbole + nom)", "🪙", self._open_currency))
            self.add_item(self._btn("Montant du daily", "📅", self._open_daily))

    def embed(self) -> discord.Embed:
        c, g = self.cfg, self.guild

        def chan(cid):
            ch = g.get_channel(cid) if cid else None
            return ch.mention if ch else "—"

        def role(rid):
            r = g.get_role(rid) if rid else None
            return r.mention if r else "—"

        def oui(v):
            return "✅ ON" if v else "❌ OFF"

        titles = {"general": "🏠 Général", "roles": "🎭 Rôles", "welcome": "👋 Bienvenue & Départ",
                  "tickets": "🎫 Tickets", "automod": "🚨 AutoMod", "levels": "📈 Niveaux",
                  "security": "🔐 Sécurité", "economy": "💰 Économie"}
        embed = embeds.brand("⚙️ Configuration", f"Section : **{titles.get(self.section)}**\n"
                             "Sélecteurs et boutons ci-dessous (les boutons ouvrent une pop-up).")
        s = self.section
        if s == "general":
            embed.add_field(name="Préfixe", value=f"`{c.get('prefix') or '!'}`")
            embed.add_field(name="Salon de logs", value=chan(c.get("log_channel_id")))
        elif s == "roles":
            embed.add_field(name="Rôle muet", value=role(c.get("mute_role_id")))
            embed.add_field(name="Rôle vérif", value=role(c.get("verify_role_id")))
            embed.add_field(name="Rôle auto", value=role(c.get("autorole_id")))
        elif s == "welcome":
            embed.add_field(name="Salon", value=chan(c.get("welcome_channel_id")), inline=False)
            embed.add_field(name="Bienvenue", value=(c.get("welcome_message") or "*(défaut)*")[:150], inline=False)
            embed.add_field(name="Image bienvenue", value=c.get("welcome_image") or "—", inline=False)
            embed.add_field(name="Départ", value=(c.get("leave_message") or "—")[:150], inline=False)
        elif s == "tickets":
            embed.add_field(name="Catégorie", value=chan(c.get("ticket_category_id")))
            embed.add_field(name="Rôle staff", value=role(c.get("ticket_staff_role_id")))
            embed.add_field(name="Transcripts", value=chan(c.get("ticket_log_channel_id")))
            embed.add_field(name="Panneau", value=c.get("ticket_panel_title") or "*(défaut)*", inline=False)
        elif s == "automod":
            embed.add_field(name="Anti-spam", value=oui(c.get("anti_spam")))
            embed.add_field(name="Anti-liens", value=oui(c.get("anti_links")))
            embed.add_field(name="Anti-invitations", value=oui(c.get("anti_invites")))
            embed.add_field(name="Anti-raid", value=oui(c.get("antiraid_enabled")))
            embed.add_field(name="Seuil raid", value=f"{c.get('antiraid_threshold')} / {c.get('antiraid_window')}s")
            embed.add_field(name="Max mentions", value=str(c.get("max_mentions") or "illimité"))
            preview = ", ".join(f"`{w}`" for w in self.blacklist[:10]) or "—"
            embed.add_field(name=f"Mots interdits ({len(self.blacklist)})", value=preview, inline=False)
        elif s == "levels":
            embed.add_field(name="Gain d'XP", value=oui(c.get("xp_enabled")))
            embed.add_field(name="Annonces", value=oui(c.get("levelup_announce")))
            embed.add_field(name="Salon d'annonce", value=chan(c.get("levelup_channel_id")))
        elif s == "security":
            embed.add_field(name="Anti-nuke", value=oui(c.get("antinuke_enabled")))
            embed.add_field(name="Sanction", value=c.get("antinuke_action") or "strip")
            embed.add_field(name="Seuil / fenêtre", value=f"{c.get('antinuke_threshold')} / {c.get('antinuke_window')}s")
        elif s == "economy":
            embed.add_field(name="Monnaie", value=f"{c.get('currency_symbol') or '🪙'} ({c.get('currency_name') or 'pièces'})")
            embed.add_field(name="Daily", value=str(c.get("daily_amount") or 200))
        embed.set_footer(text="Asuna • Configuration")
        return embed

    async def refresh(self, interaction) -> None:
        await self.reload()
        self.build()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def save(self, interaction, updates: dict) -> None:
        for k, v in updates.items():
            await self.bot.config.set(self.guild.id, k, v)
        await self.refresh(interaction)

    # ── Boutons → pop-ups / actions ───────────────────────────────────────────
    async def _open_prefix(self, i):
        await i.response.send_modal(PrefixModal(self))

    async def _open_welcome(self, i):
        await i.response.send_modal(MessageModal(self, "Message de bienvenue", "welcome_message", "welcome_image",
                                                 self.cfg.get("welcome_message"), self.cfg.get("welcome_image")))

    async def _open_leave(self, i):
        await i.response.send_modal(MessageModal(self, "Message de départ", "leave_message", "leave_image",
                                                 self.cfg.get("leave_message"), self.cfg.get("leave_image")))

    async def _open_ticket_panel(self, i):
        await i.response.send_modal(TicketPanelModal(self, self.cfg.get("ticket_panel_title"),
                                                     self.cfg.get("ticket_panel_message"), self.cfg.get("ticket_panel_image")))

    async def _open_maxmentions(self, i):
        await i.response.send_modal(NumberModal(self, "Max mentions", "max_mentions",
                                                "Mentions max par message (0 = illimité)", self.cfg.get("max_mentions")))

    async def _open_antiraid(self, i):
        await i.response.send_modal(TwoNumberModal(self, "Seuils anti-raid",
                                                   "antiraid_threshold", "Arrivées max", self.cfg.get("antiraid_threshold"),
                                                   "antiraid_window", "Fenêtre (s)", self.cfg.get("antiraid_window")))

    async def _open_antinuke(self, i):
        await i.response.send_modal(TwoNumberModal(self, "Seuils anti-nuke",
                                                   "antinuke_threshold", "Actions max", self.cfg.get("antinuke_threshold"),
                                                   "antinuke_window", "Fenêtre (s)", self.cfg.get("antinuke_window")))

    async def _open_currency(self, i):
        await i.response.send_modal(CurrencyModal(self, self.cfg.get("currency_symbol"), self.cfg.get("currency_name")))

    async def _open_bl_add(self, i):
        await i.response.send_modal(BlacklistWordModal(self, True))

    async def _open_bl_remove(self, i):
        await i.response.send_modal(BlacklistWordModal(self, False))

    async def _open_daily(self, i):
        await i.response.send_modal(NumberModal(self, "Montant du daily", "daily_amount",
                                                "Récompense journalière", self.cfg.get("daily_amount")))

    async def _create_logs(self, i):
        logcog = self.bot.get_cog("LogSetup")
        if logcog is None or not self.guild.me.guild_permissions.manage_channels:
            await i.response.send_message(embed=embeds.error("Impossible", "Permission **Gérer les salons** requise."), ephemeral=True)
            return
        await i.response.defer()
        cfg = await self.bot.config.get(self.guild.id)
        cat = await logcog._ensure_category(self.guild, cfg)
        cfg = await self.bot.config.get(self.guild.id)
        await logcog._ensure_channels(self.guild, cat, cfg)
        await self.reload()
        self.build()
        await i.edit_original_response(embed=self.embed(), view=self)

    async def _post_ticket_panel(self, i):
        from cogs.tickets import TicketPanelView, build_panel_embed
        await i.channel.send(embed=build_panel_embed(self.cfg), view=TicketPanelView())
        await i.response.send_message(
            embed=embeds.success("Panneau posté", f"Publié dans {i.channel.mention}."), ephemeral=True)


# ── Cog ───────────────────────────────────────────────────────────────────────
class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.group(name="config", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def config(self, ctx: commands.Context) -> None:
        """Ouvre le panneau de configuration interactif."""
        panel = ConfigPanel(self.bot, ctx.author.id, ctx.guild)
        await panel.reload()
        panel.build()
        panel.message = await ctx.send(embed=panel.embed(), view=panel)

    # ── Raccourcis texte ──────────────────────────────────────────────────────
    @config.command(name="prefix")
    async def config_prefix(self, ctx, prefixe: str) -> None:
        if len(prefixe) > 5:
            await ctx.send(embed=embeds.error("Préfixe trop long", "5 caractères maximum."))
            return
        await self.bot.config.set(ctx.guild.id, "prefix", prefixe)
        await ctx.send(embed=embeds.success("Préfixe mis à jour", f"Nouveau préfixe : `{prefixe}`"))

    @config.command(name="logchannel")
    async def config_logchannel(self, ctx, salon: discord.TextChannel) -> None:
        await self.bot.config.set(ctx.guild.id, "log_channel_id", salon.id)
        await ctx.send(embed=embeds.success("Salon de logs défini", f"Les logs iront dans {salon.mention}."))

    @config.command(name="muterole")
    async def config_muterole(self, ctx, role: discord.Role) -> None:
        await self.bot.config.set(ctx.guild.id, "mute_role_id", role.id)
        await ctx.send(embed=embeds.success("Rôle muet défini", f"`/mute` appliquera {role.mention}."))

    @config.command(name="verifyrole")
    async def config_verifyrole(self, ctx, role: discord.Role) -> None:
        await self.bot.config.set(ctx.guild.id, "verify_role_id", role.id)
        await ctx.send(embed=embeds.success("Rôle de vérification défini", f"Les vérifiés recevront {role.mention}."))

    @config.command(name="autorole")
    async def config_autorole(self, ctx, role: discord.Role) -> None:
        await self.bot.config.set(ctx.guild.id, "autorole_id", role.id)
        await ctx.send(embed=embeds.success("Rôle automatique défini", f"Les nouveaux recevront {role.mention}."))

    async def cog_command_error(self, ctx, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=embeds.error("Accès refusé", "Tu dois être administrateur."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=embeds.error("Argument manquant", "Ouvre plutôt le panneau avec `!config`."))
        elif isinstance(error, (commands.ChannelNotFound, commands.RoleNotFound, commands.BadArgument)):
            await ctx.send(embed=embeds.error("Argument invalide", "Vérifie le salon/rôle indiqué."))
        else:
            self.bot.log.exception("Erreur dans !config", exc_info=error)
            await ctx.send(embed=embeds.error("Oups", "Une erreur est survenue."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Settings(bot))
