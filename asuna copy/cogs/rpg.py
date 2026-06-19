"""RPG « la Tour » : exploration roguelite + combat façon Undertale.

- `/combat` : un combat unique autonome.
- `/tour`   : grimpe la Tour (création de héros, salles, boss, mort/héritage).

La scène est rendue en image (core/undertale_ui.py) et toutes les actions sont
de vrais boutons Discord. Le combat (BattleView) peut être lancé seul ou piloté
par la tour (TowerView) via un callback `on_end`.

Vertical slice de idea/RPG_Discord_Design.md. Simplification assumée : chaque
étage = un choix entre 3 portes (au lieu de la structure 3+2 salles du doc) ;
la structure complète viendra ensuite.
"""

from __future__ import annotations

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

from core import bank, embeds, rpg_data, rpg_engine, undertale_ui
from core.rpg_engine import MAX_FLOOR, Run

_DARK = 0x2B2D31


def _mk_button(label, style, callback, emoji=None) -> discord.ui.Button:
    btn = discord.ui.Button(label=label, style=style, emoji=emoji)
    btn.callback = callback
    return btn


def _scene_embed() -> discord.Embed:
    e = discord.Embed(color=_DARK)
    e.set_image(url="attachment://battle.png")
    return e


# ════════════════════════════════════════════════════════════════════════════
#  COMBAT
# ════════════════════════════════════════════════════════════════════════════
class Battle:
    """État d'un combat (autonome ou lancé par la tour)."""

    def __init__(self, guild_id, user_id, monster, *, player_hp=20, player_max=20,
                 atk=(5, 8), crit=0.12, potions=2, lifesteal=False, gold_mult=1.0,
                 is_boss=False, revive=False, on_hit=None, defense=0) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        self.monster = monster
        # Boss multi-phase : on démarre sur la 1re phase ; sinon PV/méca directs.
        self.phases = monster.get("phases") or []
        self.phase = 0
        if self.phases:
            self.monster_hp = self.phases[0]["hp"]
            self.mechanic = self.phases[0].get("mechanic")
        else:
            self.monster_hp = monster["hp"]
            self.mechanic = monster.get("mechanic")
        self.player_hp = player_hp
        self.player_max = player_max
        self.atk = atk
        self.crit = crit
        self.lifesteal = lifesteal
        self.gold_mult = gold_mult
        self.is_boss = is_boss
        self.revive = revive       # peut ressusciter une fois (Revenant / Âme)
        self.revived = False
        self.defense = defense     # réduction de dégâts (armure)
        self.on_hit = on_hit       # statut infligé au monstre quand on frappe (selon la classe)
        self.lv = 1
        # Objets : potions (soin) + un Éclat de glace (gèle l'ennemi 1 tour).
        self.items = []
        if potions > 0:
            self.items.append({"name": "Potion", "qty": potions, "effect": "heal", "value": 12})
        self.items.append({"name": "Éclat de glace", "qty": 1, "effect": "freeze"})
        # Effets de statut actifs (clé → {turns, potency}).
        self.player_status: dict = {}
        self.monster_status: dict = {}
        self.spareable = False

    def menu_text(self) -> str:
        return self.monster.get("idle", f"* {self.monster['name']} se tient là.")

    def next_phase(self) -> str | None:
        """Passe à la phase suivante d'un boss multi-phase. Retourne son dialogue, ou None."""
        if self.phase + 1 < len(self.phases):
            self.phase += 1
            self.monster_hp = self.phases[self.phase]["hp"]
            self.mechanic = self.phases[self.phase].get("mechanic")
            return self.phases[self.phase].get("dialogue", "")
        return None


class BattleView(discord.ui.View):
    def __init__(self, bot, player, battle: Battle, on_end=None) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.player = player
        self.b = battle
        self.on_end = on_end          # callable(view) appelé à la fin (mode tour)
        self.outcome: str | None = None
        self.reward_gold = 0
        self.message: discord.Message | None = None
        self.build_main()

    # ── Boutons principaux ────────────────────────────────────────────────────
    def build_main(self) -> None:
        self.clear_items()
        self.add_item(_mk_button("FIGHT", discord.ButtonStyle.danger, self.on_fight, "⚔️"))
        self.add_item(_mk_button("ACT", discord.ButtonStyle.primary, self.on_act, "💬"))
        self.add_item(_mk_button("ITEM", discord.ButtonStyle.secondary, self.on_item, "🎒"))
        self.add_item(_mk_button("MERCY", discord.ButtonStyle.success, self.on_mercy, "🕊️"))

    # ── Rendu ─────────────────────────────────────────────────────────────────
    async def _frame(self, dialogue: str, *, flash=False, soul=False) -> None:
        buf = undertale_ui.render_battle(
            dialogue=dialogue, lv=self.b.lv, hp=self.b.player_hp, max_hp=self.b.player_max,
            monster=self.b.monster["key"], monster_name=self.b.monster["name"], flash=flash, soul=soul,
        )
        if self.message is not None:
            await self.message.edit(attachments=[discord.File(buf, "battle.png")], embed=_scene_embed(), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                embed=embeds.info("Pas ton combat", "Lance le tien avec `/combat` ou `/tour` !"), ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.clear_items()
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # ── Fins ──────────────────────────────────────────────────────────────────
    async def _finish(self) -> None:
        self.stop()
        if self.on_end is not None:
            await self.on_end(self)

    async def _victory(self, *, spared=False) -> None:
        self.clear_items()
        self.reward_gold = int(self.b.monster["gold"] * self.b.gold_mult)
        self.outcome = "spare" if spared else "win"
        if self.on_end is None:  # mode autonome : on crédite directement le portefeuille
            await bank.add_wallet(self.bot.db, self.b.guild_id, self.b.user_id, self.reward_gold)
        verb = "épargné" if spared else "vaincu"
        await self._frame(f"* Tu as {verb} {self.b.monster['name']} !\n* +{self.reward_gold} or")
        await asyncio.sleep(0.4)
        await self._finish()

    async def _game_over(self) -> None:
        self.clear_items()
        self.outcome = "dead"
        await self._frame("* Tes PV tombent à zéro...\n* GAME OVER.")
        await asyncio.sleep(0.4)
        await self._finish()

    async def _maybe_die(self) -> bool:
        """Gère les PV à zéro. Retourne True si le héros meurt vraiment.

        Si une résurrection est disponible (Revenant / amélioration « Âme »),
        elle est consommée et le héros repart à mi-PV.
        """
        if self.b.player_hp > 0:
            return False
        if self.b.revive and not self.b.revived:
            self.b.revived = True
            self.b.player_hp = max(1, self.b.player_max // 2)
            await rpg_engine.grant_achievement(self.bot.db, self.b.guild_id, self.b.user_id, "increvable")
            await self._frame("* Tu refuses de mourir...\n* Ton âme te ramène à la vie !")
            await asyncio.sleep(0.9)
            return False
        await self._game_over()
        return True

    # ── Effets de statut (brûlure / saignement / gel) ─────────────────────────
    _STATUS_LABELS = {"brulure": "Brûlure", "saignement": "Saignement", "gel": "Gel"}

    def _apply_status(self, who: str, spec: dict) -> None:
        target = self.b.player_status if who == "player" else self.b.monster_status
        target[spec["status"]] = {"turns": spec["turns"], "potency": spec.get("potency", 0)}

    def _status_words(self) -> str:
        """Résumé des statuts du héros, à afficher sous le menu."""
        parts = [f"{self._STATUS_LABELS[k]} {v['turns']}" for k, v in self.b.player_status.items()]
        return ("\n* Statut : " + ", ".join(parts)) if parts else ""

    async def _apply_dot(self, who: str) -> bool:
        """Applique brûlure + saignement à une cible. Retourne True si elle meurt."""
        status = self.b.player_status if who == "player" else self.b.monster_status
        total, names = 0, []
        for key in ("brulure", "saignement"):
            if key in status:
                total += status[key]["potency"]
                status[key]["turns"] -= 1
                names.append(self._STATUS_LABELS[key].lower())
                if status[key]["turns"] <= 0:
                    del status[key]
        if total <= 0:
            return False
        label = " et ".join(dict.fromkeys(names))
        if who == "player":
            self.b.player_hp -= total
            await self._frame(f"* La {label} te ronge... -{total} PV.")
            await asyncio.sleep(0.6)
            return self.b.player_hp <= 0
        self.b.monster_hp -= total
        await self._frame(f"* {self.b.monster['name']} souffre ({label}) : -{total} PV.")
        await asyncio.sleep(0.6)
        return self.b.monster_hp <= 0

    async def _on_monster_zero(self) -> bool:
        """PV du monstre à zéro. Retourne True si le combat continue (phase suivante)."""
        dialogue = self.b.next_phase()
        if dialogue is not None:
            self.b.monster_status.clear()  # nouvelle phase : statuts remis à zéro
            await self._frame(dialogue)
            await asyncio.sleep(1.0)
            return True
        await self._victory()
        return False

    # ── Phase d'esquive (bullet-hell tour par tour, pour les boss) ────────────
    async def _show_dodge(self, danger: set, soul: int, dialogue: str) -> None:
        buf = undertale_ui.render_dodge(
            danger=danger, soul=soul, lanes=5, hp=self.b.player_hp, max_hp=self.b.player_max, dialogue=dialogue)
        await self.message.edit(attachments=[discord.File(buf, "battle.png")], embed=_scene_embed(), view=self)

    async def _dodge(self, dmg: int) -> int:
        """Mini-jeu d'esquive : choisis un couloir sûr. Retourne les dégâts subis."""
        lanes = 5
        danger = set(random.sample(range(lanes), random.choice([2, 3])))
        soul = 2
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        def make_move(delta):
            async def cb(interaction):
                await interaction.response.defer()
                if not future.done():
                    future.set_result(delta)
            return cb

        self.clear_items()
        self.add_item(_mk_button("Gauche", discord.ButtonStyle.primary, make_move(-1), "⬅️"))
        self.add_item(_mk_button("Rester", discord.ButtonStyle.secondary, make_move(0), "⏺️"))
        self.add_item(_mk_button("Droite", discord.ButtonStyle.primary, make_move(1), "➡️"))
        await self._show_dodge(danger, soul, "* ESQUIVE ! Choisis un couloir sûr.")

        try:
            move = await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            move = 0
        soul = max(0, min(lanes - 1, soul + move))
        self.clear_items()
        if soul in danger:
            taken = max(1, dmg - self.b.defense)
            await self._show_dodge(danger, soul, f"* Touché ! -{taken} PV.")
        else:
            taken = 0
            await self._show_dodge(danger, soul, "* Esquive parfaite ! Aucun dégât.")
        await asyncio.sleep(0.8)
        return taken

    # ── Tour de l'ennemi (statuts + mécaniques de boss) ───────────────────────
    async def _enemy_turn(self) -> bool:
        self.clear_items()
        mech = self.b.mechanic

        # 1) Le monstre subit ses brûlures / saignements.
        if self.b.monster_status:
            if await self._apply_dot("monster"):
                if not await self._on_monster_zero():  # mort → victoire gérée
                    return False
                # sinon : nouvelle phase, le combat continue

        # 2) Gelé : le monstre saute son tour.
        if "gel" in self.b.monster_status:
            self.b.monster_status["gel"]["turns"] -= 1
            if self.b.monster_status["gel"]["turns"] <= 0:
                del self.b.monster_status["gel"]
            await self._frame(f"* {self.b.monster['name']} est gelé ! Il ne peut pas agir.")
            await asyncio.sleep(0.7)
            return True

        # 3) Faux Héros : se régénère.
        if mech == "faux_heros":
            self.b.monster_hp += 6
            await self._frame("* Le Faux Héros se régénère !")
            await asyncio.sleep(0.6)
        # 4) Paresseux / Instable : peuvent sauter leur tour.
        if mech == "paresseux" and random.random() < 0.4:
            await self._frame("* Le boss somnole... il rate son tour !")
            await asyncio.sleep(0.7)
            return True
        if mech == "instable" and random.random() < 0.25:
            await self._frame("* Le Spectre vacille et disparaît un instant !")
            await asyncio.sleep(0.7)
            return True

        # 5) Horloger / Instable : peuvent frapper deux fois.
        hits = 1
        if (mech == "horloger" and random.random() < 0.5) or (mech == "instable" and random.random() < 0.3):
            hits = 2

        for _ in range(hits):
            await self._frame(random.choice(self.b.monster["attacks"]))
            await asyncio.sleep(0.7)
            dmg = max(1, self.b.monster["atk"] + random.randint(-1, 2))
            if self.b.is_boss:
                # Boss : phase d'esquive interactive (l'âme dans les couloirs).
                taken = await self._dodge(dmg)
            else:
                taken = max(1, dmg - self.b.defense)  # armure
                await self._frame("", flash=True)
                await asyncio.sleep(0.12)
                suffix = "  (x2 !)" if hits > 1 else ""
                await self._frame(f"* Tu encaisses {taken} dégâts.{suffix}")
                await asyncio.sleep(0.6)
            self.b.player_hp -= taken
            if mech == "vampire" and taken > 0:  # se soigne sur les dégâts infligés
                self.b.monster_hp += max(1, taken // 2)
            # Le monstre peut t'infliger un statut (seulement s'il t'a touché).
            inflicts = self.b.monster.get("inflicts")
            if taken > 0 and inflicts and self.b.player_hp > 0 and random.random() < inflicts["chance"]:
                self._apply_status("player", inflicts)
                await self._frame(f"* Tu es pris de {self._STATUS_LABELS[inflicts['status']]} !")
                await asyncio.sleep(0.6)
            if self.b.player_hp <= 0:
                if await self._maybe_die():
                    return False
                break  # ressuscité : on arrête les coups de ce tour
        return True

    async def _back_to_menu(self) -> None:
        # Au début de ton tour, tes brûlures/saignements te rongent.
        if self.b.player_status:
            if await self._apply_dot("player"):
                if await self._maybe_die():
                    return
        self.build_main()
        await self._frame(self.b.menu_text() + self._status_words())

    # ── FIGHT ─────────────────────────────────────────────────────────────────
    async def on_fight(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        self.clear_items()
        await self._frame("* Tu attaques !")
        await asyncio.sleep(0.45)
        await self._frame("* Tu attaques !", flash=True)
        await asyncio.sleep(0.12)
        crit = random.random() < self.b.crit
        dmg = random.randint(*self.b.atk) * (2 if crit else 1)
        self.b.monster_hp -= dmg
        text = f"* COUP CRITIQUE ! {dmg} dégâts !" if crit else f"* Tu infliges {dmg} dégâts."
        if self.b.lifesteal:
            healed = min(max(1, dmg // 3), self.b.player_max - self.b.player_hp)
            if healed:
                self.b.player_hp += healed
                text += f"\n* Tu draines {healed} PV."
        if self.b.mechanic == "miroir":  # le miroir renvoie une part des dégâts
            reflect = max(1, dmg // 4)
            self.b.player_hp -= reflect
            text += f"\n* Le miroir te renvoie {reflect} dégâts !"
        # Statut infligé au monstre selon ta classe (brûlure / saignement).
        if self.b.on_hit and self.b.monster_hp > 0 and random.random() < self.b.on_hit["chance"]:
            self._apply_status("monster", self.b.on_hit)
            text += f"\n* {self.b.monster['name']} : {self._STATUS_LABELS[self.b.on_hit['status']]} !"
        await self._frame(text)
        await asyncio.sleep(0.7)
        if self.b.player_hp <= 0:  # la mécanique miroir peut t'achever
            if await self._maybe_die():
                return
        if self.b.monster_hp <= 0:
            if await self._on_monster_zero():  # boss multi-phase → continue
                if await self._enemy_turn():
                    await self._back_to_menu()
            return
        if await self._enemy_turn():
            await self._back_to_menu()

    # ── ACT ───────────────────────────────────────────────────────────────────
    async def on_act(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        self.clear_items()
        for name in self.b.monster.get("acts", {}):
            self.add_item(_mk_button(name, discord.ButtonStyle.secondary, self._make_act_cb(name)))
        self.add_item(_mk_button("Retour", discord.ButtonStyle.secondary, self._on_back))
        await self._frame("* Que fais-tu ?")

    def _make_act_cb(self, name: str):
        async def cb(interaction, n=name):
            await interaction.response.defer()
            self.clear_items()
            await self._frame(self.b.monster["acts"][n])
            await asyncio.sleep(0.9)
            if n == self.b.monster.get("spare_act"):
                self.b.spareable = True
                await self._frame("* (Le monstre est prêt à être épargné — MERCY.)")
                await asyncio.sleep(0.9)
            if await self._enemy_turn():
                await self._back_to_menu()
        return cb

    async def _on_back(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await self._back_to_menu()

    # ── ITEM ──────────────────────────────────────────────────────────────────
    async def on_item(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        available = [it for it in self.b.items if it["qty"] > 0]
        if not available:
            self.clear_items()
            await self._frame("* Ton sac est vide...")
            await asyncio.sleep(0.8)
            await self._back_to_menu()
            return
        self.clear_items()
        for it in available:
            self.add_item(_mk_button(f"{it['name']} (x{it['qty']})", discord.ButtonStyle.secondary, self._make_item_cb(it)))
        self.add_item(_mk_button("Retour", discord.ButtonStyle.secondary, self._on_back))
        await self._frame("* Quel objet utiliser ?")

    def _make_item_cb(self, item: dict):
        async def cb(interaction, it=item):
            await interaction.response.defer()
            self.clear_items()
            it["qty"] -= 1
            if it["effect"] == "heal":
                healed = min(it["value"], self.b.player_max - self.b.player_hp)
                self.b.player_hp += healed
                await self._frame(f"* Tu utilises {it['name']}.\n* Tu récupères {healed} PV.")
            elif it["effect"] == "freeze":
                self.b.monster_status["gel"] = {"turns": 1, "potency": 0}
                await self._frame(f"* Tu lances un Éclat de glace !\n* {self.b.monster['name']} est gelé.")
            await asyncio.sleep(0.9)
            if await self._enemy_turn():
                await self._back_to_menu()
        return cb

    # ── MERCY ─────────────────────────────────────────────────────────────────
    async def on_mercy(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        self.clear_items()
        self.add_item(_mk_button("Épargner", discord.ButtonStyle.success, self._on_spare))
        self.add_item(_mk_button("Fuir", discord.ButtonStyle.secondary, self._on_flee))
        self.add_item(_mk_button("Retour", discord.ButtonStyle.secondary, self._on_back))
        hint = "* Tu peux l'épargner." if self.b.spareable else "* Le monstre n'est pas prêt à partir."
        await self._frame(f"* MERCY\n{hint}")

    async def _on_spare(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if self.b.spareable:
            await self._victory(spared=True)
            return
        self.clear_items()
        await self._frame("* Tu tends la main...\n* Le monstre refuse.")
        await asyncio.sleep(0.9)
        if await self._enemy_turn():
            await self._back_to_menu()

    async def _on_flee(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        self.clear_items()
        # Les boss ne se fuient pas.
        if not self.b.is_boss and random.random() < 0.5:
            self.outcome = "flee"
            await self._frame("* Tu prends la fuite !")
            await asyncio.sleep(0.4)
            await self._finish()
            return
        await self._frame("* Tu tentes de fuir...\n* Échec !")
        await asyncio.sleep(0.8)
        if await self._enemy_turn():
            await self._back_to_menu()


# ════════════════════════════════════════════════════════════════════════════
#  TOUR (boucle roguelite)
# ════════════════════════════════════════════════════════════════════════════
class TowerView(discord.ui.View):
    def __init__(self, cog, player, run: Run) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.bot = cog.bot
        self.player = player
        self.run = run
        self.message: discord.Message | None = None
        self._pending: tuple[str, int] | None = None  # salle en cours (groupe, index)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                embed=embeds.info("Pas ta partie", "Lance la tienne avec `/tour` !"), ephemeral=True
            )
            return False
        return True

    async def _show(self, buf) -> None:
        await self.message.edit(attachments=[discord.File(buf, "battle.png")], embed=_scene_embed(), view=self)

    # ── Affichage d'un étage ──────────────────────────────────────────────────
    async def render_floor(self) -> None:
        self.clear_items()
        self._pending = None
        run = self.run
        if run.floor > MAX_FLOOR:
            await self._win_tower()
            return
        if run.floor == MAX_FLOOR:  # boss final multi-phase
            self.add_item(_mk_button("Affronter le GARDIEN DU SOMMET", discord.ButtonStyle.danger, self._enter_final, "🌟"))
            await self._show(undertale_ui.render_scene(
                dialogue="* Le sommet de la Tour. Le Gardien du Sommet t'attend...",
                hp=run.hp, max_hp=run.max_hp, floor=run.floor, gold=run.gold, label="SOMMET", monster="final"))
            return
        if run.floor % 10 == 0:  # boss d'étage
            self.add_item(_mk_button("Affronter le BOSS", discord.ButtonStyle.danger, self._enter_boss, "👑"))
            await self._show(undertale_ui.render_scene(
                dialogue=f"* Une présence colossale garde l'étage {run.floor}...",
                hp=run.hp, max_hp=run.max_hp, floor=run.floor, gold=run.gold, label="BOSS", monster="golem"))
            return
        # Étage normal : 3 salles obligatoires + 2 optionnelles.
        if run.floor_state is None:
            run.floor_state = rpg_data.generate_floor(run.floor)
            await run.save(self.bot.db)
        await self._render_map()

    async def _render_map(self) -> None:
        self.clear_items()
        fs = self.run.floor_state
        for i, (kind, done) in enumerate(zip(fs["mandatory"], fs["m_done"])):
            if not done:
                self.add_item(_mk_button(rpg_data.ROOM_LABELS.get(kind, kind), discord.ButtonStyle.primary,
                                         self._make_slot_cb("m", i), rpg_data.ROOM_EMOJI.get(kind)))
        for i, (kind, done) in enumerate(zip(fs["optional"], fs["o_done"])):
            if not done:
                self.add_item(_mk_button(rpg_data.ROOM_LABELS.get(kind, kind), discord.ButtonStyle.secondary,
                                         self._make_slot_cb("o", i), rpg_data.ROOM_EMOJI.get(kind)))
        can_ascend = all(fs["m_done"])
        if can_ascend:
            self.add_item(_mk_button("Monter", discord.ButtonStyle.success, self._on_ascend, "🆙"))
        await self._show(undertale_ui.render_floormap(
            floor=self.run.floor, hp=self.run.hp, max_hp=self.run.max_hp, gold=self.run.gold,
            mandatory=list(zip(fs["mandatory"], fs["m_done"])),
            optional=list(zip(fs["optional"], fs["o_done"])), can_ascend=can_ascend))

    def _make_slot_cb(self, group: str, index: int):
        async def cb(interaction):
            await interaction.response.defer()
            self._pending = (group, index)
            key = "mandatory" if group == "m" else "optional"
            await self._resolve_room(self.run.floor_state[key][index])
        return cb

    async def _resolve_room(self, kind: str) -> None:
        handlers = {
            "combat": lambda: self._enter_combat(),
            "repos": self._room_repos,
            "tresor": self._room_tresor,
            "piege": self._room_piege,
            "evenement": self._room_event,
            "enigme": self._room_riddle,
            "casino": self._room_casino,
            "maudite": self._room_maudite,
            "laboratoire": self._room_labo,
            "lore": self._room_lore,
            "mini_boss": lambda: self._enter_combat(mini=True),
        }
        await handlers.get(kind, self._room_repos)()

    # ── Progression ───────────────────────────────────────────────────────────
    def _continue_button(self) -> None:
        self.clear_items()
        self.add_item(_mk_button("Continuer", discord.ButtonStyle.primary, self._on_continue, "➡️"))

    async def _on_continue(self, interaction) -> None:
        """Fin d'une salle : retour à la carte de l'étage (salle marquée faite)."""
        await interaction.response.defer()
        await self._back_to_map(mark=True)

    async def _on_ascend(self, interaction) -> None:
        await interaction.response.defer()
        await self._advance()

    async def _on_continue_start(self, interaction) -> None:
        """Bouton « Entrer dans la Tour » : affiche le premier étage."""
        await interaction.response.defer()
        await self.render_floor()

    async def _back_to_map(self, *, mark: bool) -> None:
        if mark and self._pending is not None:
            group, index = self._pending
            self.run.floor_state["m_done" if group == "m" else "o_done"][index] = True
            await self.run.save(self.bot.db)
        self._pending = None
        await self._render_map()

    async def _ach(self, key: str) -> None:
        await rpg_engine.grant_achievement(self.bot.db, self.run.guild_id, self.run.user_id, key)

    async def _advance(self) -> None:
        self.run.floor += 1
        self.run.floor_state = None  # le prochain étage sera regénéré
        for milestone, key in ((10, "etage_10"), (25, "etage_25"), (50, "etage_50")):
            if self.run.floor >= milestone:
                await self._ach(key)
        await self.run.reach_floor(self.bot.db)
        await self.run.save(self.bot.db)
        await self.render_floor()

    # ── Salles non-combat ─────────────────────────────────────────────────────
    async def _room_repos(self) -> None:
        healed = self.run.heal(int(self.run.max_hp * 0.35))
        await self.run.save(self.bot.db)
        self._continue_button()
        await self._show(undertale_ui.render_scene(
            dialogue=f"* Un feu de camp crépite.\n* Tu récupères {healed} PV.",
            hp=self.run.hp, max_hp=self.run.max_hp, floor=self.run.floor, gold=self.run.gold, label="REPOS"))

    async def _room_tresor(self) -> None:
        gold = random.randint(20, 40) + self.run.floor * 3
        self.run.gold += gold
        bonus = ""
        if random.random() < 0.3:
            self.run.potions += 1
            bonus = " (+1 potion)"
        await self.run.save(self.bot.db)
        self._continue_button()
        await self._show(undertale_ui.render_scene(
            dialogue=f"* Un coffre scintillant !\n* +{gold} or{bonus}.",
            hp=self.run.hp, max_hp=self.run.max_hp, floor=self.run.floor, gold=self.run.gold, label="TRÉSOR"))

    async def _room_piege(self) -> None:
        dmg = random.randint(3, 6) + self.run.floor // 3
        self.run.hp -= dmg
        if self.run.hp <= 0:
            await self._death("un piège mortel")
            return
        await self.run.save(self.bot.db)
        self._continue_button()
        await self._show(undertale_ui.render_scene(
            dialogue=f"* Des pics jaillissent du sol !\n* Tu subis {dmg} dégâts.",
            hp=self.run.hp, max_hp=self.run.max_hp, floor=self.run.floor, gold=self.run.gold, label="PIÈGE"))

    async def _room_event(self) -> None:
        event = random.choice(rpg_data.EVENTS)
        self.clear_items()
        for label, effect in event["options"]:
            self.add_item(_mk_button(label[:80], discord.ButtonStyle.secondary, self._make_event_cb(effect)))
        await self._show(undertale_ui.render_scene(
            dialogue=event["text"], hp=self.run.hp, max_hp=self.run.max_hp,
            floor=self.run.floor, gold=self.run.gold, label="ÉVÉNEMENT"))

    def _make_event_cb(self, effect: dict):
        async def cb(interaction, eff=effect):
            await interaction.response.defer()
            result = self._apply_effect(eff)
            if self.run.hp <= 0:
                await self._death("un événement funeste")
                return
            await self.run.save(self.bot.db)
            self._continue_button()
            await self._show(undertale_ui.render_scene(
                dialogue=f"* {result}", hp=self.run.hp, max_hp=self.run.max_hp,
                floor=self.run.floor, gold=self.run.gold, label="ÉVÉNEMENT"))
        return cb

    def _apply_effect(self, effect: dict) -> str:
        if "random" in effect:
            key, val = random.choice(effect["random"])
            effect = {key: val}
        parts = []
        if "hp" in effect:
            if effect["hp"] >= 0:
                parts.append(f"+{self.run.heal(effect['hp'])} PV")
            else:
                self.run.hp += effect["hp"]
                parts.append(f"{effect['hp']} PV")
        if "gold" in effect:
            self.run.gold = max(0, self.run.gold + effect["gold"])
            sign = "+" if effect["gold"] >= 0 else ""
            parts.append(f"{sign}{effect['gold']} or")
        return ", ".join(parts) or "Rien ne se passe."

    async def _room_riddle(self) -> None:
        riddle = random.choice(rpg_data.RIDDLES)
        self.clear_items()
        for idx, answer in enumerate(riddle["answers"]):
            self.add_item(_mk_button(answer[:80], discord.ButtonStyle.secondary, self._make_riddle_cb(riddle, idx)))
        await self._show(undertale_ui.render_scene(
            dialogue=riddle["q"], hp=self.run.hp, max_hp=self.run.max_hp,
            floor=self.run.floor, gold=self.run.gold, label="ÉNIGME"))

    def _make_riddle_cb(self, riddle: dict, index: int):
        async def cb(interaction, r=riddle, i=index):
            await interaction.response.defer()
            if i == r["correct"]:
                reward = 30 + self.run.floor * 2
                self.run.gold += reward
                msg = f"* Bonne réponse !\n* +{reward} or."
            else:
                dmg = 5 + self.run.floor // 2
                self.run.hp -= dmg
                if self.run.hp <= 0:
                    await self._death("une énigme fatale")
                    return
                msg = f"* Mauvaise réponse...\n* Tu subis {dmg} dégâts."
            await self.run.save(self.bot.db)
            self._continue_button()
            await self._show(undertale_ui.render_scene(
                dialogue=msg, hp=self.run.hp, max_hp=self.run.max_hp,
                floor=self.run.floor, gold=self.run.gold, label="ÉNIGME"))
        return cb

    # ── Salles spéciales (optionnelles) ───────────────────────────────────────
    async def _room_casino(self) -> None:
        stake = min(self.run.gold, 20 + self.run.floor * 5)
        if stake <= 0:
            self._continue_button()
            await self._show(undertale_ui.render_scene(
                dialogue="* Le casino brille... mais tes poches sont vides.",
                hp=self.run.hp, max_hp=self.run.max_hp, floor=self.run.floor, gold=self.run.gold, label="CASINO"))
            return
        if random.random() < 0.5:
            self.run.gold += stake
            msg = f"* Tu mises {stake} or sur le rouge...\n* GAGNÉ ! +{stake} or."
        else:
            self.run.gold -= stake
            msg = f"* Tu mises {stake} or sur le rouge...\n* Perdu. -{stake} or."
        await self.run.save(self.bot.db)
        self._continue_button()
        await self._show(undertale_ui.render_scene(
            dialogue=msg, hp=self.run.hp, max_hp=self.run.max_hp,
            floor=self.run.floor, gold=self.run.gold, label="CASINO"))

    async def _room_maudite(self) -> None:
        loss = max(1, self.run.hp // 5)
        self.run.hp = max(1, self.run.hp - loss)  # une malédiction ne tue pas
        self.run.atk_min += 1
        self.run.atk_max += 1
        await self.run.save(self.bot.db)
        self._continue_button()
        await self._show(undertale_ui.render_scene(
            dialogue=f"* Une aura maudite t'enveloppe...\n* -{loss} PV, mais +1 ATK pour toujours.",
            hp=self.run.hp, max_hp=self.run.max_hp, floor=self.run.floor, gold=self.run.gold, label="MAUDITE"))

    async def _room_labo(self) -> None:
        self.run.potions += 2
        healed = self.run.heal(5)
        await self.run.save(self.bot.db)
        self._continue_button()
        await self._show(undertale_ui.render_scene(
            dialogue=f"* Le laboratoire bouillonne d'alambics.\n* +2 potions, +{healed} PV.",
            hp=self.run.hp, max_hp=self.run.max_hp, floor=self.run.floor, gold=self.run.gold, label="LABO"))

    async def _room_lore(self) -> None:
        reward = 10 + self.run.floor * 2
        self.run.gold += reward
        await self.run.save(self.bot.db)
        self._continue_button()
        await self._show(undertale_ui.render_scene(
            dialogue=f"{random.choice(rpg_data.LORE)}\n* (Tu trouves {reward} or en explorant.)",
            hp=self.run.hp, max_hp=self.run.max_hp, floor=self.run.floor, gold=self.run.gold, label="LORE"))

    # ── Combat (intégré) ──────────────────────────────────────────────────────
    async def _enter_boss(self, interaction) -> None:
        await interaction.response.defer()
        await self._enter_combat(boss=True)

    async def _enter_final(self, interaction) -> None:
        await interaction.response.defer()
        await self._enter_combat(final=True)

    async def _enter_combat(self, *, boss: bool = False, mini: bool = False, final: bool = False) -> None:
        if final:
            monster = rpg_data.final_boss()
        elif boss:
            monster = rpg_data.boss_for_floor(self.run.floor)
        elif mini:
            monster = rpg_data.miniboss_for_floor(self.run.floor)
        else:
            monster = rpg_data.monster_for_floor(self.run.floor)
        battle = Battle(
            self.run.guild_id, self.run.user_id, monster,
            player_hp=self.run.hp, player_max=self.run.max_hp,
            atk=(self.run.atk_min, self.run.atk_max), crit=self.run.crit, potions=self.run.potions,
            lifesteal=("lifesteal" in self.run.specials), gold_mult=self.run.gold_mult,
            is_boss=(boss or final), revive=("revive" in self.run.specials),
            on_hit=self.run.class_def.get("on_hit"), defense=self.run.defense,
        )
        bview = BattleView(self.bot, self.player, battle, on_end=self._after_combat)
        bview.message = self.message
        buf = undertale_ui.render_battle(
            dialogue=monster.get("idle", f"* {monster['name']} surgit !"), lv=1,
            hp=battle.player_hp, max_hp=battle.player_max, monster=monster["key"], monster_name=monster["name"],
        )
        await self.message.edit(attachments=[discord.File(buf, "battle.png")], embed=_scene_embed(), view=bview)

    async def _after_combat(self, bview: BattleView) -> None:
        # Récupère l'état du héros après le combat.
        self.run.hp = bview.b.player_hp
        self.run.potions = next((it["qty"] for it in bview.b.items if it["name"] == "Potion"), 0)

        if bview.outcome == "dead":
            await self._death(f"vaincu par {bview.b.monster['name']}")
            return
        if bview.outcome == "flee":
            await self.run.save(self.bot.db)
            await asyncio.sleep(0.6)
            # Salle de combat fuie : retour à la carte (salle non validée). Boss : pas de fuite.
            if self._pending is not None:
                await self._back_to_map(mark=False)
            else:
                await self.render_floor()
            return
        # Succès liés à la victoire.
        await self._ach("premier_sang")
        if bview.b.phases:
            await self._ach("sommet")
        elif bview.b.is_boss:
            await self._ach("tueur_boss")
        # Victoire / épargne : l'or gagné alimente la cagnotte du run.
        self.run.gold += bview.reward_gold
        if self.run.gold >= 1000:
            await self._ach("fortune")
        await self.run.save(self.bot.db)
        await asyncio.sleep(0.8)
        if self._pending is not None:  # combat d'une salle d'étage
            await self._back_to_map(mark=True)
        else:  # boss / boss final
            await self._advance()

    # ── Fins de run ───────────────────────────────────────────────────────────
    async def _death(self, cause: str) -> None:
        self.clear_items()
        self.stop()
        floor, payout = self.run.floor, self.run.gold
        if payout > 0:
            await bank.add_wallet(self.bot.db, self.run.guild_id, self.run.user_id, payout)
        await self.run.die(self.bot.db, cause)
        await self._show(undertale_ui.render_scene(
            dialogue=f"* Tu péris à l'étage {floor}.\n* Cause : {cause}.\n"
                     f"* Or récupéré : {payout}. Héritage enregistré.",
            hp=0, max_hp=self.run.max_hp, floor=floor, gold=payout, label="GAME OVER"))

    async def _win_tower(self) -> None:
        self.clear_items()
        self.stop()
        payout = self.run.gold
        if payout > 0:
            await bank.add_wallet(self.bot.db, self.run.guild_id, self.run.user_id, payout)
        await self.run.reach_floor(self.bot.db)
        await self.run.delete(self.bot.db)
        await self._show(undertale_ui.render_scene(
            dialogue=f"* Tu atteins le sommet de la Tour !\n* VICTOIRE TOTALE !\n* Or récupéré : {payout}.",
            hp=self.run.hp, max_hp=self.run.max_hp, floor=MAX_FLOOR, gold=payout, label="SOMMET"))


# ── Sélection de classe (démarrage d'un run) ─────────────────────────────────
class ClassSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label=c["name"], value=key, emoji=c["emoji"], description=c["desc"][:100])
            for key, c in rpg_data.CLASSES.items()
        ]
        super().__init__(placeholder="🧙 Choisis ta classe…", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "StartView" = self.view
        if interaction.user.id != view.player.id:
            await interaction.response.send_message(
                embed=embeds.info("Pas ta partie", "Lance la tienne avec `/tour` !"), ephemeral=True)
            return
        await interaction.response.defer()
        run = await Run.create(view.bot.db, interaction.guild.id, interaction.user.id, self.values[0])
        tower = TowerView(view.cog, view.player, run)
        tower.message = view.message
        view.stop()
        # Petit écran d'intro avant le 1er étage.
        cdef, tdef = run.class_def, run.trait_def
        await tower._show(undertale_ui.render_scene(
            dialogue=f"* Classe : {cdef['name']}\n* Trait : {tdef['name']} — {tdef['desc']}\n"
                     f"* PV {run.max_hp} • ATK {run.atk_min}-{run.atk_max}\n* L'ascension commence...",
            hp=run.hp, max_hp=run.max_hp, floor=1, gold=0, label="DÉPART"))
        await asyncio.sleep(0.2)
        tower.clear_items()
        tower.add_item(_mk_button("Entrer dans la Tour", discord.ButtonStyle.success, tower._on_continue_start, "🚪"))
        await tower._show(undertale_ui.render_scene(
            dialogue=f"* {cdef['name']} ({tdef['name']})\n* Prêt ? Entre dans la Tour.",
            hp=run.hp, max_hp=run.max_hp, floor=1, gold=0, label="DÉPART"))


class StartView(discord.ui.View):
    def __init__(self, cog, player) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.bot = cog.bot
        self.player = player
        self.message: discord.Message | None = None
        self.add_item(ClassSelect())


# ════════════════════════════════════════════════════════════════════════════
#  BLACK MARKET (méta-progression permanente)
# ════════════════════════════════════════════════════════════════════════════
class BlackMarketView(discord.ui.View):
    def __init__(self, cog, player, guild_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.bot = cog.bot
        self.player = player
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                embed=embeds.info("Pas ton marché", "Ouvre le tien avec `/blackmarket` !"), ephemeral=True)
            return False
        return True

    async def build(self, status: str | None = None) -> discord.Embed:
        """(Re)construit l'embed + les boutons d'achat selon l'or et les niveaux."""
        gid, uid = self.guild_id, self.player.id
        ups = await rpg_engine.get_upgrades(self.bot.db, gid, uid)
        wallet = (await bank.get_account(self.bot.db, gid, uid))["wallet"]
        cfg = await self.bot.config.get(gid)
        sym = cfg.get("currency_symbol") or "🪙"

        embed = embeds.brand(
            "🛒 Black Market",
            "Dépense ton or en améliorations **permanentes**, appliquées au départ "
            "de chaque nouveau run (`/tour`).")
        embed.add_field(name="Ton or", value=f"**{wallet}** {sym}", inline=False)

        self.clear_items()
        for key, u in rpg_data.UPGRADES.items():
            lvl = ups.get(key, 0)
            if lvl >= u["max"]:
                state = "✅ niveau MAX"
                btn = discord.ui.Button(label=f"{u['name']} (MAX)", emoji=u["emoji"],
                                        style=discord.ButtonStyle.secondary, disabled=True)
            else:
                cost = rpg_data.upgrade_cost(key, lvl)
                state = f"Niv. {lvl}/{u['max']} — prochain : **{cost}** {sym}"
                btn = discord.ui.Button(
                    label=f"{u['name']} ({cost})", emoji=u["emoji"],
                    style=discord.ButtonStyle.success if wallet >= cost else discord.ButtonStyle.secondary)
                btn.callback = self._make_buy_cb(key)
            self.add_item(btn)
            embed.add_field(name=f"{u['emoji']} {u['name']}", value=f"{u['desc']}\n{state}", inline=True)

        if status:
            embed.add_field(name="​", value=status, inline=False)
        return embed

    def _make_buy_cb(self, key: str):
        async def cb(interaction: discord.Interaction):
            gid, uid = self.guild_id, self.player.id
            u = rpg_data.UPGRADES[key]
            lvl = (await rpg_engine.get_upgrades(self.bot.db, gid, uid)).get(key, 0)
            if lvl >= u["max"]:
                await interaction.response.edit_message(embed=await self.build("Déjà au maximum."), view=self)
                return
            cost = rpg_data.upgrade_cost(key, lvl)
            wallet = (await bank.get_account(self.bot.db, gid, uid))["wallet"]
            if wallet < cost:
                await interaction.response.edit_message(embed=await self.build("❌ Fonds insuffisants."), view=self)
                return
            await bank.add_wallet(self.bot.db, gid, uid, -cost)
            await rpg_engine.buy_upgrade(self.bot.db, gid, uid, key)
            await interaction.response.edit_message(embed=await self.build(f"✅ {u['name']} amélioré !"), view=self)
        return cb


# ════════════════════════════════════════════════════════════════════════════
#  FORGE (équipement : armes & armures)
# ════════════════════════════════════════════════════════════════════════════
class ForgeView(discord.ui.View):
    def __init__(self, cog, player, guild_id: int) -> None:
        super().__init__(timeout=180)
        self.cog = cog
        self.bot = cog.bot
        self.player = player
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                embed=embeds.info("Pas ta forge", "Ouvre la tienne avec `/forge` !"), ephemeral=True)
            return False
        return True

    async def build(self, status: str | None = None) -> discord.Embed:
        gid, uid = self.guild_id, self.player.id
        gear = await rpg_engine.get_gear(self.bot.db, gid, uid)
        loadout = await rpg_engine.get_loadout(self.bot.db, gid, uid)
        wallet = (await bank.get_account(self.bot.db, gid, uid))["wallet"]
        cfg = await self.bot.config.get(gid)
        sym = cfg.get("currency_symbol") or "🪙"

        embed = embeds.brand(
            "⚒️ La Forge",
            "Achète puis **équipe** armes et armures. Les bonus s'appliquent au "
            "départ de chaque run (`/tour`).")
        embed.add_field(name="Ton or", value=f"**{wallet}** {sym}", inline=False)
        wname = rpg_data.WEAPONS.get(loadout.get("weapon"), {}).get("name", "—")
        aname = rpg_data.ARMORS.get(loadout.get("armor"), {}).get("name", "—")
        embed.add_field(name="Équipé", value=f"⚔️ {wname}\n🛡️ {aname}", inline=False)

        self.clear_items()
        for slot, table in (("weapon", rpg_data.WEAPONS), ("armor", rpg_data.ARMORS)):
            for key, item in table.items():
                bonus = (f"ATK +{item['atk']}" + (f", crit +{int(item['crit'] * 100)}%" if item.get("crit") else "")
                         if slot == "weapon"
                         else f"PV +{item['hp']}" + (f", DEF +{item['defense']}" if item.get("defense") else ""))
                if loadout.get(slot) == key:
                    state = "✅ équipé"
                    self.add_item(discord.ui.Button(label=f"{item['name']} (équipé)", emoji=item["emoji"],
                                                    style=discord.ButtonStyle.secondary, disabled=True))
                elif key in gear:
                    state = "🎒 possédé"
                    btn = discord.ui.Button(label=f"Équiper {item['name']}", emoji=item["emoji"],
                                            style=discord.ButtonStyle.primary)
                    btn.callback = self._make_equip_cb(slot, key)
                    self.add_item(btn)
                else:
                    state = f"**{item['cost']}** {sym}"
                    btn = discord.ui.Button(label=f"{item['name']} ({item['cost']})", emoji=item["emoji"],
                                            style=discord.ButtonStyle.success if wallet >= item["cost"] else discord.ButtonStyle.secondary)
                    btn.callback = self._make_buy_cb(slot, key)
                    self.add_item(btn)
                embed.add_field(name=f"{item['emoji']} {item['name']}", value=f"{bonus}\n{state}", inline=True)

        if status:
            embed.add_field(name="​", value=status, inline=False)
        return embed

    def _table(self, slot):
        return rpg_data.WEAPONS if slot == "weapon" else rpg_data.ARMORS

    def _make_buy_cb(self, slot: str, key: str):
        async def cb(interaction):
            gid, uid = self.guild_id, self.player.id
            item = self._table(slot)[key]
            if key in await rpg_engine.get_gear(self.bot.db, gid, uid):
                await interaction.response.edit_message(embed=await self.build("Déjà possédé."), view=self)
                return
            wallet = (await bank.get_account(self.bot.db, gid, uid))["wallet"]
            if wallet < item["cost"]:
                await interaction.response.edit_message(embed=await self.build("❌ Fonds insuffisants."), view=self)
                return
            await bank.add_wallet(self.bot.db, gid, uid, -item["cost"])
            await rpg_engine.buy_gear(self.bot.db, gid, uid, key)
            await interaction.response.edit_message(embed=await self.build(f"✅ {item['name']} acheté ! Clique pour l'équiper."), view=self)
        return cb

    def _make_equip_cb(self, slot: str, key: str):
        async def cb(interaction):
            gid, uid = self.guild_id, self.player.id
            await rpg_engine.set_loadout(self.bot.db, gid, uid, **{slot: key})
            loadout = await rpg_engine.get_loadout(self.bot.db, gid, uid)
            if loadout.get("weapon") and loadout.get("armor"):
                await rpg_engine.grant_achievement(self.bot.db, gid, uid, "forgeron")
            await interaction.response.edit_message(
                embed=await self.build(f"✅ {self._table(slot)[key]['name']} équipé !"), view=self)
        return cb


# ════════════════════════════════════════════════════════════════════════════
#  COG
# ════════════════════════════════════════════════════════════════════════════
class RPG(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="combat", description="Lance un combat RPG façon Undertale (autonome).")
    @app_commands.guild_only()
    async def combat(self, interaction: discord.Interaction) -> None:
        monster = rpg_data.monster_for_floor(1)
        battle = Battle(interaction.guild.id, interaction.user.id, monster,
                        player_hp=20, player_max=20, atk=(5, 8), crit=0.12, potions=2)
        view = BattleView(self.bot, interaction.user, battle)
        buf = undertale_ui.render_battle(
            dialogue=f"* {monster['name']} bloque le passage !", lv=1, hp=20, max_hp=20,
            monster=monster["key"], monster_name=monster["name"])
        await interaction.response.send_message(embed=_scene_embed(), file=discord.File(buf, "battle.png"), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="tour", description="Grimpe la Tour : RPG roguelite façon Undertale.")
    @app_commands.guild_only()
    async def tour(self, interaction: discord.Interaction) -> None:
        run = await Run.load(self.bot.db, interaction.guild.id, interaction.user.id)
        if run is not None:
            view = TowerView(self, interaction.user, run)
            await interaction.response.send_message(
                embed=embeds.brand("🗼 La Tour", f"Reprise de ton ascension — étage {run.floor}."))
            view.message = await interaction.original_response()
            await view.render_floor()
            return
        view = StartView(self, interaction.user)
        embed = embeds.brand(
            "🗼 La Tour — Nouveau héros",
            "Choisis ta **classe** dans le menu ci-dessous. Un **trait** te sera attribué au hasard.\n"
            "But : grimper les **100 étages**. La mort est permanente, mais laisse un héritage.")
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="blackmarket", description="Dépense ton or en améliorations permanentes pour la Tour.")
    @app_commands.guild_only()
    async def blackmarket(self, interaction: discord.Interaction) -> None:
        view = BlackMarketView(self, interaction.user, interaction.guild.id)
        embed = await view.build()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="forge", description="Achète et équipe armes & armures pour la Tour.")
    @app_commands.guild_only()
    async def forge(self, interaction: discord.Interaction) -> None:
        view = ForgeView(self, interaction.user, interaction.guild.id)
        embed = await view.build()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="achievements", description="Affiche tes succès dans la Tour.")
    @app_commands.guild_only()
    async def achievements(self, interaction: discord.Interaction) -> None:
        unlocked = await rpg_engine.get_achievements(self.bot.db, interaction.guild.id, interaction.user.id)
        embed = embeds.brand(
            f"🏆 Succès de {interaction.user.display_name}",
            f"Débloqués : **{len(unlocked)}/{len(rpg_data.ACHIEVEMENTS)}**")
        for key, a in rpg_data.ACHIEVEMENTS.items():
            got = key in unlocked
            embed.add_field(
                name=f"{a['emoji']} {a['name']}" + (" ✅" if got else " 🔒"),
                value=a["desc"] if got else f"||{a['desc']}||",
                inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="abandon", description="Abandonne ton run en cours dans la Tour.")
    @app_commands.guild_only()
    async def abandon(self, interaction: discord.Interaction) -> None:
        run = await Run.load(self.bot.db, interaction.guild.id, interaction.user.id)
        if run is None:
            await interaction.response.send_message(
                embed=embeds.info("Aucun run", "Tu n'as pas d'ascension en cours."), ephemeral=True)
            return
        payout = run.gold
        if payout > 0:
            await bank.add_wallet(self.bot.db, run.guild_id, run.user_id, payout)
        await run.reach_floor(self.bot.db)
        await run.delete(self.bot.db)
        await interaction.response.send_message(
            embed=embeds.success("Run abandonné", f"Tu quittes la Tour à l'étage {run.floor}. Or récupéré : {payout}."),
            ephemeral=True)

    @app_commands.command(name="rpgjournal", description="Affiche tes records et tes dernières morts dans la Tour.")
    @app_commands.guild_only()
    async def rpgjournal(self, interaction: discord.Interaction) -> None:
        rec = await self.bot.db.fetchone(
            "SELECT best_floor, runs, deaths FROM rpg_records WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, interaction.user.id))
        deaths = await self.bot.db.fetchall(
            "SELECT floor, cause, created_at FROM rpg_deaths WHERE guild_id = ? AND user_id = ? "
            "ORDER BY id DESC LIMIT 5", (interaction.guild.id, interaction.user.id))
        embed = embeds.brand(f"📜 Journal de {interaction.user.display_name}")
        if rec:
            embed.add_field(name="Meilleur étage", value=str(rec["best_floor"]))
            embed.add_field(name="Runs", value=str(rec["runs"]))
            embed.add_field(name="Morts", value=str(rec["deaths"]))
            embed.add_field(name="Bonus d'héritage", value=f"+{(rec['best_floor'] // 10) * 2} PV au départ", inline=False)
        else:
            embed.description = "Aucune ascension pour l'instant. Lance `/tour` !"
        if deaths:
            embed.add_field(
                name="Dernières morts",
                value="\n".join(f"• Étage {d['floor']} — {d['cause']}" for d in deaths), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RPG(bot))
