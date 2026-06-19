"""Économie : monnaie virtuelle, daily, travail, banque, échanges, boutique,
inventaire. Les montants/devise sont configurables par serveur.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core import bank, embeds

# Constantes de gameplay (les gains de daily sont, eux, configurables).
_DAILY_COOLDOWN = timedelta(hours=24)
_WORK_COOLDOWN = timedelta(hours=1)
_WORK_MIN, _WORK_MAX = 50, 180
_WORK_FLAVOR = [
    "Tu as aidé un villageois et gagné", "Tu as vendu des potions pour",
    "Mission accomplie ! Récompense :", "Tu as miné des cristaux et empoché",
    "Tu as gardé la taverne et reçu",
]


def _parse_amount(text: str, available: int) -> int | None:
    """Interprète « 100 », « all », « tout » → montant. None si invalide."""
    text = (text or "").strip().lower()
    if text in ("all", "tout", "max"):
        return available if available > 0 else None
    try:
        value = int(text)
    except ValueError:
        return None
    return value if value > 0 else None


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _money(self, guild_id: int, amount: int) -> str:
        cfg = await self.bot.config.get(guild_id)
        return f"**{amount:,}** {cfg.get('currency_symbol') or '🪙'}".replace(",", " ")

    # ── Consultation ────────────────────────────────────────────────────────
    @app_commands.command(name="balance", description="Affiche ton solde (ou celui d'un membre).")
    @app_commands.describe(membre="Membre à consulter (toi par défaut)")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        target = membre or interaction.user
        acc = await bank.get_account(self.bot.db, interaction.guild.id, target.id)
        embed = embeds.brand(f"💰 Portefeuille de {target.display_name}")
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Liquide", value=await self._money(interaction.guild.id, acc["wallet"]))
        embed.add_field(name="Banque", value=await self._money(interaction.guild.id, acc["bank"]))
        embed.add_field(name="Total", value=await self._money(interaction.guild.id, acc["wallet"] + acc["bank"]))
        await interaction.response.send_message(embed=embed)

    # ── Gains ───────────────────────────────────────────────────────────────
    @app_commands.command(name="daily", description="Récupère ta récompense journalière.")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        now = datetime.now(timezone.utc)
        row = await self.bot.db.fetchone(
            "SELECT last_daily FROM economy WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, interaction.user.id),
        )
        if row and row["last_daily"]:
            last = datetime.fromisoformat(row["last_daily"])
            if now - last < _DAILY_COOLDOWN:
                nxt = last + _DAILY_COOLDOWN
                await interaction.response.send_message(
                    embed=embeds.warning("Déjà récupéré", f"Reviens {discord.utils.format_dt(nxt, 'R')}."),
                    ephemeral=True,
                )
                return
        cfg = await self.bot.config.get(interaction.guild.id)
        amount = cfg.get("daily_amount") or 200
        await bank.add_wallet(self.bot.db, interaction.guild.id, interaction.user.id, amount)
        await self.bot.db.execute(
            "UPDATE economy SET last_daily = ? WHERE guild_id = ? AND user_id = ?",
            (now.isoformat(), interaction.guild.id, interaction.user.id),
        )
        await interaction.response.send_message(
            embed=embeds.success("Récompense journalière", f"Tu reçois {await self._money(interaction.guild.id, amount)} !")
        )

    @app_commands.command(name="work", description="Travaille pour gagner de l'argent (toutes les heures).")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction) -> None:
        now = datetime.now(timezone.utc)
        row = await self.bot.db.fetchone(
            "SELECT last_work FROM economy WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, interaction.user.id),
        )
        if row and row["last_work"]:
            last = datetime.fromisoformat(row["last_work"])
            if now - last < _WORK_COOLDOWN:
                nxt = last + _WORK_COOLDOWN
                await interaction.response.send_message(
                    embed=embeds.warning("Trop tôt", f"Tu pourras retravailler {discord.utils.format_dt(nxt, 'R')}."),
                    ephemeral=True,
                )
                return
        amount = random.randint(_WORK_MIN, _WORK_MAX)
        await bank.add_wallet(self.bot.db, interaction.guild.id, interaction.user.id, amount)
        await self.bot.db.execute(
            "UPDATE economy SET last_work = ? WHERE guild_id = ? AND user_id = ?",
            (now.isoformat(), interaction.guild.id, interaction.user.id),
        )
        flavor = random.choice(_WORK_FLAVOR)
        await interaction.response.send_message(
            embed=embeds.success("Travail terminé", f"{flavor} {await self._money(interaction.guild.id, amount)}.")
        )

    # ── Échanges & banque ─────────────────────────────────────────────────────
    @app_commands.command(name="pay", description="Donne de l'argent à un autre membre.")
    @app_commands.describe(membre="Destinataire", montant="Montant à transférer")
    @app_commands.guild_only()
    async def pay(
        self, interaction: discord.Interaction, membre: discord.Member, montant: app_commands.Range[int, 1, None]
    ) -> None:
        if membre.bot or membre == interaction.user:
            await interaction.response.send_message(
                embed=embeds.error("Impossible", "Choisis un autre membre (pas un bot, pas toi-même)."), ephemeral=True
            )
            return
        ok = await bank.transfer(self.bot.db, interaction.guild.id, interaction.user.id, membre.id, montant)
        if not ok:
            await interaction.response.send_message(
                embed=embeds.error("Fonds insuffisants", "Tu n'as pas assez en liquide."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Transfert effectué", f"{await self._money(interaction.guild.id, montant)} → {membre.mention}.")
        )

    @app_commands.command(name="deposit", description="Dépose de l'argent à la banque (« all » accepté).")
    @app_commands.describe(montant="Montant ou « all »")
    @app_commands.guild_only()
    async def deposit(self, interaction: discord.Interaction, montant: str) -> None:
        acc = await bank.get_account(self.bot.db, interaction.guild.id, interaction.user.id)
        amount = _parse_amount(montant, acc["wallet"])
        if amount is None:
            await interaction.response.send_message(
                embed=embeds.error("Montant invalide", "Indique un nombre positif ou « all »."), ephemeral=True
            )
            return
        if not await bank.deposit(self.bot.db, interaction.guild.id, interaction.user.id, amount):
            await interaction.response.send_message(
                embed=embeds.error("Fonds insuffisants", "Tu n'as pas autant en liquide."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Dépôt effectué", f"{await self._money(interaction.guild.id, amount)} placés en banque.")
        )

    @app_commands.command(name="withdraw", description="Retire de l'argent de la banque (« all » accepté).")
    @app_commands.describe(montant="Montant ou « all »")
    @app_commands.guild_only()
    async def withdraw(self, interaction: discord.Interaction, montant: str) -> None:
        acc = await bank.get_account(self.bot.db, interaction.guild.id, interaction.user.id)
        amount = _parse_amount(montant, acc["bank"])
        if amount is None:
            await interaction.response.send_message(
                embed=embeds.error("Montant invalide", "Indique un nombre positif ou « all »."), ephemeral=True
            )
            return
        if not await bank.withdraw(self.bot.db, interaction.guild.id, interaction.user.id, amount):
            await interaction.response.send_message(
                embed=embeds.error("Fonds insuffisants", "Tu n'as pas autant en banque."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Retrait effectué", f"{await self._money(interaction.guild.id, amount)} retirés de la banque.")
        )

    @app_commands.command(name="baltop", description="Classement des plus fortunés du serveur.")
    @app_commands.guild_only()
    async def baltop(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT user_id, (wallet + bank) AS total FROM economy "
            "WHERE guild_id = ? ORDER BY total DESC LIMIT 10",
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Classement vide", "Personne n'a encore d'argent."), ephemeral=True
            )
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(rows):
            member = interaction.guild.get_member(r["user_id"])
            name = member.display_name if member else f"Utilisateur {r['user_id']}"
            rank = medals[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{rank} **{name}** — {await self._money(interaction.guild.id, r['total'])}")
        await interaction.response.send_message(embed=embeds.brand("🏆 Top fortunes", "\n".join(lines)))

    # ── Boutique & inventaire ─────────────────────────────────────────────────
    @app_commands.command(name="shop", description="Affiche la boutique du serveur.")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, name, description, price, role_id FROM shop_items WHERE guild_id = ? ORDER BY price",
            (interaction.guild.id,),
        )
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Boutique vide", "Aucun article. Les admins peuvent en ajouter via `/shopadmin add`."),
                ephemeral=True,
            )
            return
        embed = embeds.brand("🛒 Boutique")
        for r in rows:
            extra = " 🎭 *(rôle)*" if r["role_id"] else ""
            embed.add_field(
                name=f"{r['name']} — {await self._money(interaction.guild.id, r['price'])}{extra}",
                value=(r["description"] or "—"),
                inline=False,
            )
        embed.set_footer(text="Asuna • /buy <nom> pour acheter")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Achète un article de la boutique.")
    @app_commands.describe(objet="Nom de l'article")
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction, objet: str) -> None:
        item = await self.bot.db.fetchone(
            "SELECT id, name, price, role_id FROM shop_items WHERE guild_id = ? AND name = ?",
            (interaction.guild.id, objet),
        )
        if item is None:
            await interaction.response.send_message(
                embed=embeds.error("Introuvable", f"Aucun article nommé « {objet} »."), ephemeral=True
            )
            return
        acc = await bank.get_account(self.bot.db, interaction.guild.id, interaction.user.id)
        if acc["wallet"] < item["price"]:
            await interaction.response.send_message(
                embed=embeds.error("Trop cher", "Tu n'as pas assez en liquide."), ephemeral=True
            )
            return

        # Article-rôle : on attribue le rôle plutôt que de stocker un objet.
        if item["role_id"]:
            role = interaction.guild.get_role(item["role_id"])
            if role is None:
                await interaction.response.send_message(
                    embed=embeds.error("Rôle manquant", "Le rôle associé n'existe plus. Préviens un admin."), ephemeral=True
                )
                return
            if role in interaction.user.roles:
                await interaction.response.send_message(
                    embed=embeds.info("Déjà possédé", "Tu as déjà ce rôle."), ephemeral=True
                )
                return
            try:
                await interaction.user.add_roles(role, reason="Achat boutique")
            except discord.HTTPException:
                await interaction.response.send_message(
                    embed=embeds.error("Échec", "Je n'ai pas pu te donner le rôle (permissions ?)."), ephemeral=True
                )
                return
        else:
            await self.bot.db.execute(
                "INSERT INTO inventory (guild_id, user_id, item_id, quantity) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + 1",
                (interaction.guild.id, interaction.user.id, item["id"]),
            )

        await bank.add_wallet(self.bot.db, interaction.guild.id, interaction.user.id, -item["price"])
        await interaction.response.send_message(
            embed=embeds.success("Achat réussi", f"Tu as acheté **{item['name']}** pour {await self._money(interaction.guild.id, item['price'])}.")
        )

    @app_commands.command(name="inventory", description="Affiche ton inventaire (ou celui d'un membre).")
    @app_commands.describe(membre="Membre à consulter")
    @app_commands.guild_only()
    async def inventory(self, interaction: discord.Interaction, membre: discord.Member | None = None) -> None:
        target = membre or interaction.user
        rows = await self.bot.db.fetchall(
            "SELECT s.name, i.quantity FROM inventory i JOIN shop_items s ON s.id = i.item_id "
            "WHERE i.guild_id = ? AND i.user_id = ? ORDER BY s.name",
            (interaction.guild.id, target.id),
        )
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Inventaire vide", f"{target.display_name} ne possède aucun objet."), ephemeral=True
            )
            return
        lines = [f"• **{r['name']}** ×{r['quantity']}" for r in rows]
        await interaction.response.send_message(
            embed=embeds.brand(f"🎒 Inventaire de {target.display_name}", "\n".join(lines))
        )

    # ── Admin : boutique ──────────────────────────────────────────────────────
    shopadmin = app_commands.Group(
        name="shopadmin",
        description="Gestion de la boutique",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @shopadmin.command(name="add", description="Ajoute un article à la boutique.")
    @app_commands.describe(
        nom="Nom de l'article", prix="Prix en monnaie",
        description="Description (optionnelle)", role="Rôle attribué à l'achat (optionnel)",
    )
    async def shop_add(
        self, interaction: discord.Interaction, nom: str, prix: app_commands.Range[int, 1, None],
        description: str | None = None, role: discord.Role | None = None,
    ) -> None:
        try:
            await self.bot.db.execute(
                "INSERT INTO shop_items (guild_id, name, description, price, role_id) VALUES (?, ?, ?, ?, ?)",
                (interaction.guild.id, nom, description, prix, role.id if role else None),
            )
        except Exception:
            await interaction.response.send_message(
                embed=embeds.error("Doublon", f"Un article « {nom} » existe déjà."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Article ajouté", f"**{nom}** à {await self._money(interaction.guild.id, prix)}."),
            ephemeral=True,
        )

    @shopadmin.command(name="remove", description="Retire un article de la boutique.")
    async def shop_remove(self, interaction: discord.Interaction, nom: str) -> None:
        await self.bot.db.execute(
            "DELETE FROM shop_items WHERE guild_id = ? AND name = ?", (interaction.guild.id, nom)
        )
        await interaction.response.send_message(
            embed=embeds.success("Article retiré", f"« {nom} » n'est plus en vente."), ephemeral=True
        )

    # ── Admin : monnaie ───────────────────────────────────────────────────────
    eco = app_commands.Group(
        name="eco",
        description="Administration de l'économie",
        default_permissions=discord.Permissions(administrator=True),
        guild_only=True,
    )

    @eco.command(name="give", description="Crédite de l'argent à un membre.")
    async def eco_give(
        self, interaction: discord.Interaction, membre: discord.Member, montant: app_commands.Range[int, 1, None]
    ) -> None:
        await bank.add_wallet(self.bot.db, interaction.guild.id, membre.id, montant)
        await interaction.response.send_message(
            embed=embeds.success("Crédit effectué", f"{await self._money(interaction.guild.id, montant)} → {membre.mention}."),
            ephemeral=True,
        )

    @eco.command(name="take", description="Retire de l'argent du porte-monnaie d'un membre.")
    async def eco_take(
        self, interaction: discord.Interaction, membre: discord.Member, montant: app_commands.Range[int, 1, None]
    ) -> None:
        acc = await bank.get_account(self.bot.db, interaction.guild.id, membre.id)
        retire = min(montant, acc["wallet"])
        await bank.add_wallet(self.bot.db, interaction.guild.id, membre.id, -retire)
        await interaction.response.send_message(
            embed=embeds.success("Débit effectué", f"{await self._money(interaction.guild.id, retire)} retirés à {membre.mention}."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))
