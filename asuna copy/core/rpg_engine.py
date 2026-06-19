"""Moteur de run du RPG : état du héros, persistance, progression, mort.

Un « run » = une tentative d'ascension de la Tour. Il est sauvegardé en base
(table rpg_runs) pour survivre aux redémarrages et permettre de reprendre via
/tour. Les records (meilleur étage, morts) alimentent un petit bonus d'héritage.
"""

from __future__ import annotations

import json
import random

import discord

from core import rpg_data
from core.database import Database

MAX_FLOOR = 100


class Run:
    """État courant d'un héros dans la Tour."""

    def __init__(self, guild_id: int, user_id: int, **kw) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        self.cls: str = kw["cls"]
        self.trait: str = kw["trait"]
        self.floor: int = kw.get("floor", 1)
        self.hp: int = kw["hp"]
        self.max_hp: int = kw["max_hp"]
        self.atk_min: int = kw["atk_min"]
        self.atk_max: int = kw["atk_max"]
        self.crit: float = kw["crit"]
        self.potions: int = kw["potions"]
        self.gold: int = kw.get("gold", 0)
        self.gold_mult: float = kw["gold_mult"]
        self.specials: list[str] = kw.get("specials", [])
        self.defense: int = kw.get("defense", 0)
        # État de l'étage courant (3 salles obligatoires + 2 optionnelles).
        # None tant qu'il n'a pas été généré ; dict une fois en cours.
        self.floor_state: dict | None = kw.get("floor_state")

    # ── Construction d'un nouveau run ─────────────────────────────────────────
    @classmethod
    async def create(cls, db: Database, guild_id: int, user_id: int, class_key: str) -> "Run":
        cdef = rpg_data.CLASSES[class_key]
        trait_key = random.choice(list(rpg_data.TRAITS))
        tdef = rpg_data.TRAITS[trait_key]

        max_hp = cdef["hp"] + tdef["hp"]
        atk_min = max(1, cdef["atk"][0] + tdef["atk"])
        atk_max = max(atk_min, cdef["atk"][1] + tdef["atk"])
        crit = round(cdef["crit"] + tdef["crit"], 3)
        gold_mult = round(cdef["gold_mult"] + tdef["gold_mult"], 2)
        potions = 0 if tdef["no_potions"] else 3
        specials = list(cdef["specials"])

        # Bonus d'héritage : +2 PV par tranche de 10 étages déjà atteinte.
        best = await _best_floor(db, guild_id, user_id)
        max_hp += (best // 10) * 2

        # Améliorations permanentes du Black Market.
        ups = await get_upgrades(db, guild_id, user_id)
        max_hp += 5 * ups.get("vitalite", 0)
        atk_min += ups.get("force", 0)
        atk_max += ups.get("force", 0)
        crit = round(crit + 0.03 * ups.get("precision", 0), 3)
        if not tdef["no_potions"]:
            potions += ups.get("alchimie", 0)
        start_gold = 50 * ups.get("fortune", 0)
        if ups.get("ame", 0) >= 1 and "revive" not in specials:
            specials.append("revive")

        # Équipement de la Forge (arme + armure équipées).
        defense = 0
        loadout = await get_loadout(db, guild_id, user_id)
        if loadout.get("weapon") in rpg_data.WEAPONS:
            w = rpg_data.WEAPONS[loadout["weapon"]]
            atk_min += w["atk"]
            atk_max += w["atk"]
            crit = round(crit + w["crit"], 3)
        if loadout.get("armor") in rpg_data.ARMORS:
            a = rpg_data.ARMORS[loadout["armor"]]
            max_hp += a["hp"]
            defense += a["defense"]

        run = cls(
            guild_id, user_id, cls=class_key, trait=trait_key, floor=1,
            hp=max_hp, max_hp=max_hp, atk_min=atk_min, atk_max=atk_max,
            crit=crit, potions=potions, gold=start_gold, gold_mult=gold_mult,
            specials=specials, defense=defense,
        )
        await run.save(db)
        await _bump_records(db, guild_id, user_id, runs=1)
        return run

    # ── Chargement / sauvegarde ───────────────────────────────────────────────
    @classmethod
    async def load(cls, db: Database, guild_id: int, user_id: int) -> "Run | None":
        row = await db.fetchone(
            "SELECT * FROM rpg_runs WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        if row is None:
            return None
        data = dict(row)
        data["specials"] = json.loads(data.get("specials") or "[]")
        data["floor_state"] = json.loads(data["floor_state"]) if data.get("floor_state") else None
        return cls(guild_id, user_id, **{k: data[k] for k in (
            "cls", "trait", "floor", "hp", "max_hp", "atk_min", "atk_max",
            "crit", "potions", "gold", "gold_mult", "specials", "floor_state", "defense",
        )})

    async def save(self, db: Database) -> None:
        floor_state = json.dumps(self.floor_state) if self.floor_state is not None else None
        await db.execute(
            "INSERT INTO rpg_runs (guild_id, user_id, cls, trait, floor, hp, max_hp, "
            "atk_min, atk_max, crit, potions, gold, gold_mult, specials, floor_state, defense) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
            "cls=excluded.cls, trait=excluded.trait, floor=excluded.floor, hp=excluded.hp, "
            "max_hp=excluded.max_hp, atk_min=excluded.atk_min, atk_max=excluded.atk_max, "
            "crit=excluded.crit, potions=excluded.potions, gold=excluded.gold, "
            "gold_mult=excluded.gold_mult, specials=excluded.specials, floor_state=excluded.floor_state, "
            "defense=excluded.defense",
            (self.guild_id, self.user_id, self.cls, self.trait, self.floor, self.hp,
             self.max_hp, self.atk_min, self.atk_max, self.crit, self.potions,
             self.gold, self.gold_mult, json.dumps(self.specials), floor_state, self.defense),
        )

    async def delete(self, db: Database) -> None:
        await db.execute(
            "DELETE FROM rpg_runs WHERE guild_id = ? AND user_id = ?", (self.guild_id, self.user_id)
        )

    async def die(self, db: Database, cause: str) -> None:
        """Termine le run : journalise la mort, met à jour les records, supprime le run."""
        await db.execute(
            "INSERT INTO rpg_deaths (guild_id, user_id, floor, cause, created_at) VALUES (?, ?, ?, ?, ?)",
            (self.guild_id, self.user_id, self.floor, cause, discord.utils.utcnow().isoformat()),
        )
        await _bump_records(db, self.guild_id, self.user_id, deaths=1, best=self.floor)
        await self.delete(db)

    async def reach_floor(self, db: Database) -> None:
        """Met à jour le meilleur étage atteint (héritage)."""
        await _bump_records(db, self.guild_id, self.user_id, best=self.floor)

    # ── Confort ───────────────────────────────────────────────────────────────
    @property
    def class_def(self) -> dict:
        return rpg_data.CLASSES[self.cls]

    @property
    def trait_def(self) -> dict:
        return rpg_data.TRAITS[self.trait]

    def heal(self, amount: int) -> int:
        healed = min(amount, self.max_hp - self.hp)
        self.hp += healed
        return healed


# ── Records / héritage ────────────────────────────────────────────────────────
async def _best_floor(db: Database, guild_id: int, user_id: int) -> int:
    row = await db.fetchone(
        "SELECT best_floor FROM rpg_records WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
    )
    return row["best_floor"] if row else 0


async def get_upgrades(db: Database, guild_id: int, user_id: int) -> dict[str, int]:
    """Niveaux d'améliorations du Black Market pour un joueur."""
    rows = await db.fetchall(
        "SELECT upgrade, level FROM rpg_upgrades WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    return {r["upgrade"]: r["level"] for r in rows}


async def buy_upgrade(db: Database, guild_id: int, user_id: int, key: str) -> None:
    """Incrémente d'un niveau l'amélioration donnée."""
    await db.execute(
        "INSERT INTO rpg_upgrades (guild_id, user_id, upgrade, level) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(guild_id, user_id, upgrade) DO UPDATE SET level = level + 1",
        (guild_id, user_id, key),
    )


# ── Forge : équipement ────────────────────────────────────────────────────────
async def get_gear(db: Database, guild_id: int, user_id: int) -> set[str]:
    rows = await db.fetchall(
        "SELECT item_key FROM rpg_gear WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    return {r["item_key"] for r in rows}


async def buy_gear(db: Database, guild_id: int, user_id: int, item_key: str) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO rpg_gear (guild_id, user_id, item_key) VALUES (?, ?, ?)",
        (guild_id, user_id, item_key))


async def get_loadout(db: Database, guild_id: int, user_id: int) -> dict:
    row = await db.fetchone(
        "SELECT weapon, armor FROM rpg_loadout WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    return {"weapon": row["weapon"], "armor": row["armor"]} if row else {"weapon": None, "armor": None}


async def set_loadout(db: Database, guild_id: int, user_id: int, *, weapon=..., armor=...) -> None:
    current = await get_loadout(db, guild_id, user_id)
    w = current["weapon"] if weapon is ... else weapon
    a = current["armor"] if armor is ... else armor
    await db.execute(
        "INSERT INTO rpg_loadout (guild_id, user_id, weapon, armor) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET weapon = excluded.weapon, armor = excluded.armor",
        (guild_id, user_id, w, a))


# ── Succès ─────────────────────────────────────────────────────────────────────
async def get_achievements(db: Database, guild_id: int, user_id: int) -> set[str]:
    rows = await db.fetchall(
        "SELECT achievement FROM rpg_achievements WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    return {r["achievement"] for r in rows}


async def grant_achievement(db: Database, guild_id: int, user_id: int, key: str) -> bool:
    """Débloque un succès. Retourne True s'il vient juste d'être débloqué."""
    cur = await db.execute(
        "INSERT OR IGNORE INTO rpg_achievements (guild_id, user_id, achievement, created_at) "
        "VALUES (?, ?, ?, ?)",
        (guild_id, user_id, key, discord.utils.utcnow().isoformat()))
    return cur.rowcount > 0


async def _bump_records(
    db: Database, guild_id: int, user_id: int, *, runs: int = 0, deaths: int = 0, best: int = 0
) -> None:
    await db.execute(
        "INSERT INTO rpg_records (guild_id, user_id, best_floor, runs, deaths) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
        "best_floor = MAX(best_floor, excluded.best_floor), "
        "runs = runs + excluded.runs, deaths = deaths + excluded.deaths",
        (guild_id, user_id, best, runs, deaths),
    )
