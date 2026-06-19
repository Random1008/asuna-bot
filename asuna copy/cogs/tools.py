"""Outils pratiques : sondages, rappels, to-do, convertisseur.

- Sondages : embed + boutons de vote, un vote par membre, décompte en direct,
  persistants (réenregistrés au démarrage).
- Rappels : planifiés en base, déclenchés par une boucle de fond (survivent au
  redémarrage).
- To-do : liste personnelle par membre.
- Convertisseur : températures, distances, poids (hors-ligne).
"""

from __future__ import annotations

import json

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import embeds
from core.utils import parse_duration

_NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


# ── Sondages ──────────────────────────────────────────────────────────────────
def _bar(count: int, total: int, length: int = 12) -> str:
    filled = round(length * count / total) if total else 0
    return "▰" * filled + "▱" * (length - filled)


async def render_poll(bot, poll: dict) -> discord.Embed:
    """Construit l'embed d'un sondage à partir des votes en base."""
    options = json.loads(poll["options"])
    votes = await bot.db.fetchall(
        "SELECT choice, COUNT(*) AS c FROM poll_votes WHERE poll_id = ? GROUP BY choice", (poll["id"],))
    counts = {r["choice"]: r["c"] for r in votes}
    total = sum(counts.values())
    status = " — clôturé" if poll["closed"] else ""
    embed = embeds.brand(f"📊 {poll['question']}{status}")
    for i, opt in enumerate(options):
        c = counts.get(i, 0)
        pct = round(100 * c / total) if total else 0
        embed.add_field(name=f"{_NUM[i]} {opt}", value=f"{_bar(c, total)}  {c} vote(s) — {pct}%", inline=False)
    embed.set_footer(text=f"Asuna • {total} vote(s) au total")
    return embed


class PollView(discord.ui.View):
    """Vue de sondage persistante (custom_ids = asuna:poll:<id>:<i>)."""

    def __init__(self, bot, poll_id: int, options: list[str], closed: bool = False) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.poll_id = poll_id
        for i in range(len(options)):
            btn = discord.ui.Button(
                emoji=_NUM[i], style=discord.ButtonStyle.secondary,
                custom_id=f"asuna:poll:{poll_id}:{i}", disabled=closed)
            btn.callback = self._make_vote(i)
            self.add_item(btn)
        if not closed:
            close_btn = discord.ui.Button(
                label="Clôturer", emoji="🛑", style=discord.ButtonStyle.danger,
                custom_id=f"asuna:poll:{poll_id}:close")
            close_btn.callback = self._close
            self.add_item(close_btn)

    async def _poll(self) -> dict | None:
        row = await self.bot.db.fetchone("SELECT * FROM polls WHERE id = ?", (self.poll_id,))
        return dict(row) if row else None

    def _make_vote(self, choice: int):
        async def cb(interaction: discord.Interaction):
            poll = await self._poll()
            if poll is None or poll["closed"]:
                await interaction.response.send_message(
                    embed=embeds.info("Sondage clôturé", "Ce sondage n'accepte plus de votes."), ephemeral=True)
                return
            await self.bot.db.execute(
                "INSERT INTO poll_votes (poll_id, user_id, choice) VALUES (?, ?, ?) "
                "ON CONFLICT(poll_id, user_id) DO UPDATE SET choice = excluded.choice",
                (self.poll_id, interaction.user.id, choice))
            await interaction.response.edit_message(embed=await render_poll(self.bot, await self._poll()), view=self)
        return cb

    async def _close(self, interaction: discord.Interaction):
        poll = await self._poll()
        if poll is None:
            return
        is_admin = interaction.user.guild_permissions.manage_messages
        if interaction.user.id != poll["author_id"] and not is_admin:
            await interaction.response.send_message(
                embed=embeds.error("Non autorisé", "Seul l'auteur ou un modérateur peut clôturer."), ephemeral=True)
            return
        await self.bot.db.execute("UPDATE polls SET closed = 1 WHERE id = ?", (self.poll_id,))
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=await render_poll(self.bot, await self._poll()), view=self)
        self.stop()


async def register_open_polls(bot) -> None:
    """Réenregistre les vues des sondages ouverts au démarrage (persistance)."""
    rows = await bot.db.fetchall("SELECT id, message_id, options FROM polls WHERE closed = 0 AND message_id IS NOT NULL")
    for r in rows:
        bot.add_view(PollView(bot, r["id"], json.loads(r["options"])), message_id=r["message_id"])


# ── Cog ───────────────────────────────────────────────────────────────────────
class Tools(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self) -> None:
        self.reminder_loop.cancel()

    # ── Sondage ────────────────────────────────────────────────────────────────
    @app_commands.command(name="sondage", description="Crée un sondage à boutons (options séparées par « ; »).")
    @app_commands.describe(question="La question", options="2 à 10 options séparées par des points-virgules")
    @app_commands.guild_only()
    async def sondage(self, interaction: discord.Interaction, question: str, options: str) -> None:
        opts = [o.strip() for o in options.split(";") if o.strip()]
        if not (2 <= len(opts) <= 10):
            await interaction.response.send_message(
                embed=embeds.error("Options invalides", "Donne entre 2 et 10 options séparées par `;`."), ephemeral=True)
            return
        cur = await self.bot.db.execute(
            "INSERT INTO polls (guild_id, channel_id, author_id, question, options, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (interaction.guild.id, interaction.channel.id, interaction.user.id, question,
             json.dumps(opts), discord.utils.utcnow().isoformat()))
        poll_id = cur.lastrowid
        poll = await self.bot.db.fetchone("SELECT * FROM polls WHERE id = ?", (poll_id,))
        view = PollView(self.bot, poll_id, opts)
        await interaction.response.send_message(embed=await render_poll(self.bot, dict(poll)), view=view)
        msg = await interaction.original_response()
        await self.bot.db.execute("UPDATE polls SET message_id = ? WHERE id = ?", (msg.id, poll_id))

    # ── Rappels ────────────────────────────────────────────────────────────────
    @app_commands.command(name="rappel", description="Programme un rappel (ex: 10m, 2h, 1d).")
    @app_commands.describe(duree="Délai avant le rappel (ex: 30m, 2h, 1d)", message="Texte du rappel")
    @app_commands.guild_only()
    async def rappel(self, interaction: discord.Interaction, duree: str, message: str) -> None:
        delta = parse_duration(duree)
        if delta is None:
            await interaction.response.send_message(
                embed=embeds.error("Durée invalide", "Exemples : `30m`, `2h`, `1d`."), ephemeral=True)
            return
        due = discord.utils.utcnow() + delta
        await self.bot.db.execute(
            "INSERT INTO reminders (guild_id, channel_id, user_id, due_at, text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (interaction.guild.id, interaction.channel.id, interaction.user.id, due.isoformat(),
             message, discord.utils.utcnow().isoformat()))
        await interaction.response.send_message(
            embed=embeds.success("Rappel programmé", f"Je te rappellerai {discord.utils.format_dt(due, 'R')} :\n> {message}"),
            ephemeral=True)

    @app_commands.command(name="rappels", description="Liste tes rappels en attente.")
    @app_commands.guild_only()
    async def rappels(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, due_at, text FROM reminders WHERE guild_id = ? AND user_id = ? ORDER BY due_at",
            (interaction.guild.id, interaction.user.id))
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Aucun rappel", "Tu n'as pas de rappel en attente."), ephemeral=True)
            return
        from datetime import datetime
        lines = []
        for r in rows:
            when = discord.utils.format_dt(datetime.fromisoformat(r["due_at"]), "R")
            lines.append(f"`#{r['id']}` — {when} : {r['text']}")
        await interaction.response.send_message(
            embed=embeds.info(f"Tes rappels ({len(rows)})", "\n".join(lines)), ephemeral=True)

    @app_commands.command(name="rappelannuler", description="Annule un de tes rappels par son numéro.")
    @app_commands.guild_only()
    async def rappelannuler(self, interaction: discord.Interaction, id: int) -> None:
        cur = await self.bot.db.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?", (id, interaction.user.id))
        ok = cur.rowcount > 0
        await interaction.response.send_message(
            embed=(embeds.success("Rappel annulé", f"Le rappel #{id} a été supprimé.") if ok
                   else embeds.error("Introuvable", "Aucun rappel à ce numéro (ou pas le tien).")),
            ephemeral=True)

    @tasks.loop(seconds=30)
    async def reminder_loop(self) -> None:
        now = discord.utils.utcnow().isoformat()
        due = await self.bot.db.fetchall("SELECT * FROM reminders WHERE due_at <= ?", (now,))
        for r in due:
            await self._fire_reminder(r)
            await self.bot.db.execute("DELETE FROM reminders WHERE id = ?", (r["id"],))

    @reminder_loop.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    async def _fire_reminder(self, r) -> None:
        embed = embeds.brand("⏰ Rappel", r["text"])
        channel = self.bot.get_channel(r["channel_id"])
        try:
            if isinstance(channel, discord.TextChannel):
                await channel.send(content=f"<@{r['user_id']}>", embed=embed)
            else:
                user = await self.bot.fetch_user(r["user_id"])
                await user.send(embed=embed)
        except discord.HTTPException:
            pass

    # ── To-do ──────────────────────────────────────────────────────────────────
    todo = app_commands.Group(name="todo", description="Ta liste de tâches personnelle", guild_only=True)

    @todo.command(name="add", description="Ajoute une tâche.")
    async def todo_add(self, interaction: discord.Interaction, tache: str) -> None:
        await self.bot.db.execute(
            "INSERT INTO todos (guild_id, user_id, text, created_at) VALUES (?, ?, ?, ?)",
            (interaction.guild.id, interaction.user.id, tache, discord.utils.utcnow().isoformat()))
        await interaction.response.send_message(embed=embeds.success("Tâche ajoutée", tache), ephemeral=True)

    @todo.command(name="list", description="Affiche ta liste de tâches.")
    async def todo_list(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT id, text, done FROM todos WHERE guild_id = ? AND user_id = ? ORDER BY done, id",
            (interaction.guild.id, interaction.user.id))
        if not rows:
            await interaction.response.send_message(
                embed=embeds.info("Liste vide", "Ajoute une tâche avec `/todo add`."), ephemeral=True)
            return
        lines = [f"{'✅' if r['done'] else '⬜'} `#{r['id']}` {r['text']}" for r in rows]
        await interaction.response.send_message(
            embed=embeds.brand("📝 Tes tâches", "\n".join(lines)), ephemeral=True)

    @todo.command(name="done", description="Marque une tâche comme faite.")
    async def todo_done(self, interaction: discord.Interaction, id: int) -> None:
        await self.bot.db.execute(
            "UPDATE todos SET done = 1 WHERE id = ? AND user_id = ?", (id, interaction.user.id))
        await interaction.response.send_message(embed=embeds.success("Tâche faite", f"Tâche #{id} cochée. 🎉"), ephemeral=True)

    @todo.command(name="remove", description="Supprime une tâche.")
    async def todo_remove(self, interaction: discord.Interaction, id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM todos WHERE id = ? AND user_id = ?", (id, interaction.user.id))
        await interaction.response.send_message(embed=embeds.success("Tâche supprimée", f"Tâche #{id} retirée."), ephemeral=True)

    @todo.command(name="clear", description="Vide les tâches terminées.")
    async def todo_clear(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute(
            "DELETE FROM todos WHERE user_id = ? AND guild_id = ? AND done = 1",
            (interaction.user.id, interaction.guild.id))
        await interaction.response.send_message(embed=embeds.success("Nettoyé", "Tâches terminées supprimées."), ephemeral=True)

    # ── Convertisseur ──────────────────────────────────────────────────────────
    @app_commands.command(name="convertir", description="Convertit une valeur (températures, distances, poids).")
    @app_commands.describe(valeur="La valeur à convertir", conversion="Le type de conversion")
    @app_commands.choices(conversion=[
        app_commands.Choice(name="°C → °F", value="c_f"),
        app_commands.Choice(name="°F → °C", value="f_c"),
        app_commands.Choice(name="km → miles", value="km_mi"),
        app_commands.Choice(name="miles → km", value="mi_km"),
        app_commands.Choice(name="kg → lb", value="kg_lb"),
        app_commands.Choice(name="lb → kg", value="lb_kg"),
    ])
    async def convertir(self, interaction: discord.Interaction, valeur: float,
                        conversion: app_commands.Choice[str]) -> None:
        formulas = {
            "c_f": (lambda v: v * 9 / 5 + 32, "°C", "°F"),
            "f_c": (lambda v: (v - 32) * 5 / 9, "°F", "°C"),
            "km_mi": (lambda v: v * 0.621371, "km", "mi"),
            "mi_km": (lambda v: v / 0.621371, "mi", "km"),
            "kg_lb": (lambda v: v * 2.20462, "kg", "lb"),
            "lb_kg": (lambda v: v / 2.20462, "lb", "kg"),
        }
        fn, src, dst = formulas[conversion.value]
        result = fn(valeur)
        await interaction.response.send_message(
            embed=embeds.brand("🔁 Conversion", f"**{valeur:g} {src}** = **{result:.2f} {dst}**"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tools(bot))
