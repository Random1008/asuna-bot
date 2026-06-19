"""Mini-jeux : pile ou face (avec mise), devinette, quiz, morpion.

Les gains sont crédités via l'économie (core/bank.py). Le morpion est un duel
entre deux membres (sans mise).
"""

from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands

from core import bank, embeds

# Petite banque de questions de quiz (réponse correcte en index 0, mélangée à l'affichage).
_QUIZ: list[dict] = [
    {"q": "Quelle est la capitale de l'Australie ?", "good": "Canberra", "bad": ["Sydney", "Melbourne", "Perth"]},
    {"q": "Combien de côtés a un hexagone ?", "good": "6", "bad": ["5", "7", "8"]},
    {"q": "Quel est le plus grand océan ?", "good": "Pacifique", "bad": ["Atlantique", "Indien", "Arctique"]},
    {"q": "Qui a peint la Joconde ?", "good": "Léonard de Vinci", "bad": ["Picasso", "Van Gogh", "Monet"]},
    {"q": "En quelle année a eu lieu la Révolution française ?", "good": "1789", "bad": ["1689", "1815", "1492"]},
    {"q": "Quel gaz les plantes absorbent-elles ?", "good": "Dioxyde de carbone", "bad": ["Oxygène", "Azote", "Hélium"]},
    {"q": "Combien de joueurs dans une équipe de football (terrain) ?", "good": "11", "bad": ["9", "10", "12"]},
    {"q": "Quelle planète est la plus proche du Soleil ?", "good": "Mercure", "bad": ["Vénus", "Mars", "Terre"]},
]


# ════════════════════════════════════════════════════════════════════════════
#  Pile ou face (mise)
# ════════════════════════════════════════════════════════════════════════════
class Games(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _money(self, guild_id: int, amount: int) -> str:
        cfg = await self.bot.config.get(guild_id)
        return f"**{amount}** {cfg.get('currency_symbol') or '🪙'}"

    @app_commands.command(name="pileface", description="Pile ou face avec une mise (50/50).")
    @app_commands.describe(choix="Ton pari", mise="Montant à miser")
    @app_commands.choices(choix=[
        app_commands.Choice(name="Pile", value="pile"),
        app_commands.Choice(name="Face", value="face"),
    ])
    @app_commands.guild_only()
    async def pileface(self, interaction: discord.Interaction, choix: app_commands.Choice[str],
                       mise: app_commands.Range[int, 1, None]) -> None:
        acc = await bank.get_account(self.bot.db, interaction.guild.id, interaction.user.id)
        if acc["wallet"] < mise:
            await interaction.response.send_message(
                embed=embeds.error("Fonds insuffisants", "Tu n'as pas assez en liquide."), ephemeral=True)
            return
        result = random.choice(["pile", "face"])
        won = result == choix.value
        await bank.add_wallet(self.bot.db, interaction.guild.id, interaction.user.id, mise if won else -mise)
        face = "🪙 Pile" if result == "pile" else "🪙 Face"
        if won:
            embed = embeds.success("Gagné !", f"C'est tombé sur **{face}**.\nTu remportes {await self._money(interaction.guild.id, mise)} !")
        else:
            embed = embeds.error("Perdu...", f"C'est tombé sur **{face}**.\nTu perds {await self._money(interaction.guild.id, mise)}.")
        await interaction.response.send_message(embed=embed)

    # ── Devinette ──────────────────────────────────────────────────────────────
    @app_commands.command(name="devine", description="Devine le nombre (1-100) en un minimum d'essais.")
    @app_commands.guild_only()
    async def devine(self, interaction: discord.Interaction) -> None:
        view = GuessView(self.bot, interaction.user, random.randint(1, 100))
        await interaction.response.send_message(
            embed=embeds.brand("🔢 Devinette", "Je pense à un nombre entre **1 et 100**.\nClique sur **Deviner** !"),
            view=view)
        view.message = await interaction.original_response()

    # ── Quiz ───────────────────────────────────────────────────────────────────
    @app_commands.command(name="quiz", description="Une question de culture générale (récompense en or).")
    @app_commands.guild_only()
    async def quiz(self, interaction: discord.Interaction) -> None:
        q = random.choice(_QUIZ)
        options = [q["good"]] + q["bad"]
        random.shuffle(options)
        view = QuizView(self.bot, interaction.user, q["good"], options)
        await interaction.response.send_message(
            embed=embeds.brand("🧠 Quiz", q["q"]), view=view)
        view.message = await interaction.original_response()

    # ── Morpion ────────────────────────────────────────────────────────────────
    @app_commands.command(name="morpion", description="Défie un membre au morpion (tic-tac-toe).")
    @app_commands.describe(adversaire="Le membre à défier")
    @app_commands.guild_only()
    async def morpion(self, interaction: discord.Interaction, adversaire: discord.Member) -> None:
        if adversaire.bot or adversaire.id == interaction.user.id:
            await interaction.response.send_message(
                embed=embeds.error("Adversaire invalide", "Choisis un autre membre (pas un bot, pas toi)."), ephemeral=True)
            return
        view = TicTacToe(interaction.user, adversaire)
        await interaction.response.send_message(
            content=f"❌ {interaction.user.mention} vs ⭕ {adversaire.mention}\nAu tour de {interaction.user.mention} (❌)",
            view=view)
        view.message = await interaction.original_response()


# ── Vues : devinette ──────────────────────────────────────────────────────────
class GuessModal(discord.ui.Modal, title="Ta proposition"):
    nombre = discord.ui.TextInput(label="Un nombre entre 1 et 100", max_length=3)

    def __init__(self, view: "GuessView") -> None:
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.view.guess(interaction, str(self.nombre))


class GuessView(discord.ui.View):
    def __init__(self, bot, player, secret: int) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.player = player
        self.secret = secret
        self.tries = 0
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                embed=embeds.info("Pas ta partie", "Lance la tienne avec `/devine` !"), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Deviner", emoji="🎯", style=discord.ButtonStyle.primary)
    async def deviner(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(GuessModal(self))

    async def guess(self, interaction: discord.Interaction, raw: str) -> None:
        try:
            value = int(raw)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error("Invalide", "Entre un nombre entier."), ephemeral=True)
            return
        self.tries += 1
        if value == self.secret:
            reward = max(10, 60 - self.tries * 8)
            await bank.add_wallet(self.bot.db, interaction.guild.id, interaction.user.id, reward)
            cfg = await self.bot.config.get(interaction.guild.id)
            sym = cfg.get("currency_symbol") or "🪙"
            for item in self.children:
                item.disabled = True
            self.stop()
            await interaction.response.edit_message(
                embed=embeds.success("Trouvé !", f"C'était **{self.secret}** ! En {self.tries} essai(s).\n+{reward} {sym}"),
                view=self)
        else:
            sens = "plus grand ⬆️" if value < self.secret else "plus petit ⬇️"
            await interaction.response.edit_message(
                embed=embeds.warning("Pas encore", f"**{value}** → c'est {sens}.\nEssais : {self.tries}"), view=self)


# ── Vues : quiz ───────────────────────────────────────────────────────────────
class QuizView(discord.ui.View):
    def __init__(self, bot, player, answer: str, options: list[str]) -> None:
        super().__init__(timeout=60)
        self.bot = bot
        self.player = player
        self.answer = answer
        self.message: discord.Message | None = None
        for opt in options:
            btn = discord.ui.Button(label=opt[:80], style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(opt)
            self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                embed=embeds.info("Pas ton quiz", "Lance le tien avec `/quiz` !"), ephemeral=True)
            return False
        return True

    def _make_cb(self, choice: str):
        async def cb(interaction: discord.Interaction):
            correct = choice == self.answer
            for item in self.children:
                item.disabled = True
                if item.label == self.answer:
                    item.style = discord.ButtonStyle.success
                elif item.label == choice:
                    item.style = discord.ButtonStyle.danger
            self.stop()
            if correct:
                reward = 25
                await bank.add_wallet(self.bot.db, interaction.guild.id, interaction.user.id, reward)
                cfg = await self.bot.config.get(interaction.guild.id)
                sym = cfg.get("currency_symbol") or "🪙"
                embed = embeds.success("Bonne réponse !", f"**{self.answer}** — +{reward} {sym}")
            else:
                embed = embeds.error("Raté", f"La bonne réponse était **{self.answer}**.")
            await interaction.response.edit_message(embed=embed, view=self)
        return cb


# ── Vues : morpion ────────────────────────────────────────────────────────────
class _Cell(discord.ui.Button):
    def __init__(self, x: int, y: int) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label="​", row=y)
        self.x, self.y = x, y

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.play(interaction, self)


class TicTacToe(discord.ui.View):
    def __init__(self, player_x, player_o) -> None:
        super().__init__(timeout=300)
        self.players = [player_x, player_o]
        self.marks = ["❌", "⭕"]
        self.turn = 0
        self.board = [[None, None, None] for _ in range(3)]
        self.message: discord.Message | None = None
        for y in range(3):
            for x in range(3):
                self.add_item(_Cell(x, y))

    @property
    def current(self):
        return self.players[self.turn]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.current.id:
            return True
        if interaction.user.id in (p.id for p in self.players):
            await interaction.response.send_message(embed=embeds.info("Patience", "Ce n'est pas ton tour."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=embeds.info("Spectateur", "Tu ne joues pas cette partie."), ephemeral=True)
        return False

    async def play(self, interaction: discord.Interaction, cell: _Cell) -> None:
        mark = self.marks[self.turn]
        self.board[cell.y][cell.x] = self.turn
        cell.label = mark
        cell.style = discord.ButtonStyle.danger if self.turn == 0 else discord.ButtonStyle.success
        cell.disabled = True

        if self._winner() is not None:
            content = f"🎉 {self.current.mention} ({mark}) remporte la partie !"
            self._end()
        elif all(c is not None for row in self.board for c in row):
            content = "🤝 Match nul !"
            self._end()
        else:
            self.turn ^= 1
            content = (f"❌ {self.players[0].mention} vs ⭕ {self.players[1].mention}\n"
                       f"Au tour de {self.current.mention} ({self.marks[self.turn]})")
        await interaction.response.edit_message(content=content, view=self)

    def _winner(self):
        b = self.board
        lines = []
        lines.extend(b)                                  # lignes
        lines.extend([[b[r][c] for r in range(3)] for c in range(3)])  # colonnes
        lines.append([b[i][i] for i in range(3)])        # diagonale
        lines.append([b[i][2 - i] for i in range(3)])    # anti-diagonale
        for line in lines:
            if line[0] is not None and line[0] == line[1] == line[2]:
                return line[0]
        return None

    def _end(self) -> None:
        for item in self.children:
            item.disabled = True
        self.stop()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Games(bot))
