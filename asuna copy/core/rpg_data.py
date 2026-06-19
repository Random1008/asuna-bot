"""Données du RPG « la Tour » : classes, traits, salles, monstres, boss,
événements et énigmes. Tout est data-driven pour rester facile à étendre.

Inspiré de idea/RPG_Discord_Design.md (roguelite, tour de 100 étages).
"""

from __future__ import annotations

import random

# ── Classes de départ ────────────────────────────────────────────────────────
# Chaque classe définit les stats de base du héros.
CLASSES: dict[str, dict] = {
    "berserker": {
        "name": "Berserker", "emoji": "🪓",
        "desc": "Frappe fort mais fragile. Fait saigner.",
        "hp": 18, "atk": (7, 11), "crit": 0.15, "gold_mult": 1.0, "specials": [],
        "on_hit": {"status": "saignement", "chance": 0.25, "turns": 3, "potency": 4},
    },
    "gardien": {
        "name": "Gardien", "emoji": "🛡️",
        "desc": "Robuste, dégâts modestes.",
        "hp": 30, "atk": (3, 6), "crit": 0.08, "gold_mult": 1.0, "specials": [],
    },
    "assassin": {
        "name": "Assassin", "emoji": "🗡️",
        "desc": "Critiques fréquents, peu de PV. Fait saigner.",
        "hp": 16, "atk": (6, 9), "crit": 0.30, "gold_mult": 1.0, "specials": [],
        "on_hit": {"status": "saignement", "chance": 0.35, "turns": 2, "potency": 4},
    },
    "mage": {
        "name": "Mage instable", "emoji": "✨",
        "desc": "Dégâts imprévisibles. Enflamme l'ennemi.",
        "hp": 20, "atk": (2, 13), "crit": 0.15, "gold_mult": 1.0, "specials": [],
        "on_hit": {"status": "brulure", "chance": 0.30, "turns": 3, "potency": 3},
    },
    "lame": {
        "name": "Lame sanguine", "emoji": "🩸",
        "desc": "Vole des PV à chaque coup.",
        "hp": 22, "atk": (5, 8), "crit": 0.12, "gold_mult": 1.0, "specials": ["lifesteal"],
    },
    "chanceux": {
        "name": "Aventurier chanceux", "emoji": "🍀",
        "desc": "Plus d'or et de chance.",
        "hp": 20, "atk": (5, 8), "crit": 0.20, "gold_mult": 1.5, "specials": ["luck"],
    },
    "revenant": {
        "name": "Revenant", "emoji": "💀",
        "desc": "Ressuscite une fois par run.",
        "hp": 20, "atk": (5, 8), "crit": 0.12, "gold_mult": 1.0, "specials": ["revive"],
    },
}

# ── Traits de départ (modificateurs appliqués par-dessus la classe) ──────────
TRAITS: dict[str, dict] = {
    "chance": {
        "name": "Chance insolente", "desc": "Critiques bien plus fréquents.",
        "hp": 0, "atk": 0, "crit": 0.15, "gold_mult": 0.0, "no_potions": False,
    },
    "fragile": {
        "name": "Fragile mais dangereux", "desc": "-PV mais +ATK.",
        "hp": -6, "atk": 3, "crit": 0.0, "gold_mult": 0.0, "no_potions": False,
    },
    "prudent": {
        "name": "Prudent", "desc": "+PV mais -ATK.",
        "hp": 6, "atk": -2, "crit": 0.0, "gold_mult": 0.0, "no_potions": False,
    },
    "instable": {
        "name": "Instable", "desc": "Bonus aléatoires d'ATK et de crit.",
        "hp": 0, "atk": 1, "crit": 0.10, "gold_mult": 0.0, "no_potions": False,
    },
    "maudit": {
        "name": "Maudit", "desc": "-PV mais beaucoup plus d'or.",
        "hp": -4, "atk": 0, "crit": 0.0, "gold_mult": 0.6, "no_potions": False,
    },
    "sans_potion": {
        "name": "Sans potion", "desc": "Pas de potions, mais +ATK.",
        "hp": 0, "atk": 2, "crit": 0.0, "gold_mult": 0.0, "no_potions": True,
    },
}

# ── Black Market : améliorations permanentes (méta-progression) ──────────────
# Achetées avec l'or du portefeuille (économie), elles s'appliquent au DÉPART de
# chaque nouveau run. C'est ce qui « boucle » le roguelite : mourir rapporte de
# l'or → on s'améliore → on grimpe plus haut.
UPGRADES: dict[str, dict] = {
    "vitalite":  {"name": "Vitalité",        "desc": "+5 PV max",          "emoji": "❤️", "max": 10, "base": 150, "step": 120},
    "force":     {"name": "Force",           "desc": "+1 ATK",             "emoji": "💪", "max": 8,  "base": 200, "step": 150},
    "precision": {"name": "Précision",       "desc": "+3% critique",       "emoji": "🎯", "max": 6,  "base": 180, "step": 140},
    "alchimie":  {"name": "Alchimie",        "desc": "+1 potion au départ", "emoji": "🧪", "max": 5, "base": 160, "step": 130},
    "fortune":   {"name": "Fortune",         "desc": "+50 or au départ",   "emoji": "💰", "max": 5,  "base": 120, "step": 100},
    "ame":       {"name": "Âme persistante", "desc": "Ressuscite 1× / run", "emoji": "💀", "max": 1, "base": 800, "step": 0},
}


def upgrade_cost(key: str, level: int) -> int:
    """Coût de la prochaine amélioration (croît avec le niveau déjà atteint)."""
    u = UPGRADES[key]
    return u["base"] + u["step"] * level


# ── Équipement (acheté à la Forge, équipé en permanence) ─────────────────────
WEAPONS: dict[str, dict] = {
    "dague":   {"name": "Dague",           "emoji": "🔪", "atk": 1, "crit": 0.05, "cost": 300},
    "epee":    {"name": "Épée longue",     "emoji": "⚔️", "atk": 3, "crit": 0.00, "cost": 750},
    "rapiere": {"name": "Rapière",         "emoji": "🤺", "atk": 2, "crit": 0.10, "cost": 1100},
    "hache":   {"name": "Hache de guerre", "emoji": "🪓", "atk": 5, "crit": 0.00, "cost": 1600},
}
ARMORS: dict[str, dict] = {
    "cuir":   {"name": "Armure de cuir",    "emoji": "🟫", "hp": 8,  "defense": 0, "cost": 300},
    "maille": {"name": "Cotte de mailles",  "emoji": "🔗", "hp": 16, "defense": 1, "cost": 800},
    "plaque": {"name": "Armure de plaques", "emoji": "🛡️", "hp": 28, "defense": 2, "cost": 1700},
}


# ── Succès (achievements) ────────────────────────────────────────────────────
ACHIEVEMENTS: dict[str, dict] = {
    "premier_sang": {"name": "Premier sang",  "desc": "Gagner un combat.",                "emoji": "🩸"},
    "etage_10":     {"name": "Grimpeur",      "desc": "Atteindre l'étage 10.",            "emoji": "🧗"},
    "etage_25":     {"name": "Alpiniste",     "desc": "Atteindre l'étage 25.",            "emoji": "⛰️"},
    "etage_50":     {"name": "Vertige",       "desc": "Atteindre l'étage 50.",            "emoji": "🌄"},
    "tueur_boss":   {"name": "Tueur de boss", "desc": "Vaincre un boss d'étage.",         "emoji": "👑"},
    "sommet":       {"name": "Au sommet",     "desc": "Vaincre le Gardien du Sommet.",    "emoji": "🌟"},
    "fortune":      {"name": "Fortune",       "desc": "Accumuler 1000 or dans un run.",   "emoji": "💰"},
    "increvable":   {"name": "Increvable",    "desc": "Ressusciter en plein combat.",     "emoji": "💀"},
    "forgeron":     {"name": "Forgeron",      "desc": "Équiper une arme et une armure.",  "emoji": "⚒️"},
}


# ── Monstres (gabarits de base, mis à l'échelle selon l'étage) ───────────────
MONSTERS: list[dict] = [
    {
        "key": "slime", "name": "Slime gluant", "hp": 26, "atk": 3, "gold": 40, "xp": 15,
        "idle": "* Le Slime gluant dégouline tranquillement.",
        "acts": {
            "Vérifier": "* SLIME GLUANT — ATK 3 / DEF 1.\n* Il colle à tout.",
            "Complimenter": "* Tu complimentes le Slime.\n* Il frétille de bonheur.",
        },
        "spare_act": "Complimenter",
        "attacks": ["* Le Slime t'éclabousse !", "* Le Slime te fonce dessus !"],
    },
    {
        "key": "ghost", "name": "Petit Fantôme", "hp": 22, "atk": 4, "gold": 55, "xp": 20,
        "idle": "* Le Petit Fantôme dit « zzz » à voix basse.",
        "acts": {
            "Vérifier": "* PETIT FANTÔME — ATK 4 / DEF 0.\n* Il fait semblant de dormir.",
            "Consoler": "* Tu réconfortes le Fantôme.\n* Il se sent mieux.",
        },
        "spare_act": "Consoler",
        "attacks": ["* Le Fantôme lance des larmes !", "* Le Fantôme traverse ton cœur !"],
    },
    {
        "key": "golem", "name": "Golem de pierre", "hp": 40, "atk": 5, "gold": 80, "xp": 35,
        "idle": "* Le Golem de pierre gronde sourdement.",
        "acts": {
            "Vérifier": "* GOLEM DE PIERRE — ATK 5 / DEF 3.\n* Robuste mais lent.",
            "Apaiser": "* Tu poses ta main sur la pierre tiède.\n* Le Golem s'adoucit.",
        },
        "spare_act": "Apaiser",
        "attacks": ["* Le Golem écrase le sol !", "* Le Golem te charge !"],
    },
    {
        "key": "slime", "name": "Champignon vénéneux", "hp": 30, "atk": 4, "gold": 60, "xp": 25,
        "idle": "* Le Champignon vénéneux libère des spores.",
        "acts": {
            "Vérifier": "* CHAMPIGNON — ATK 4 / DEF 1.\n* Ses spores piquent les yeux.",
            "Renifler": "* Tu renifles le Champignon.\n* Atchoum ! Il a l'air flatté.",
        },
        "spare_act": "Renifler",
        "attacks": ["* Le Champignon crache des spores !", "* Une vague de pollen t'irrite !"],
        "inflicts": {"status": "brulure", "chance": 0.4, "turns": 3, "potency": 2},
    },
    {
        "key": "golem", "name": "Armure hantée", "hp": 36, "atk": 6, "gold": 75, "xp": 32,
        "idle": "* L'Armure hantée s'entrechoque toute seule.",
        "acts": {
            "Vérifier": "* ARMURE HANTÉE — ATK 6 / DEF 2.\n* Vide à l'intérieur... ou presque.",
            "Saluer": "* Tu salues l'Armure poliment.\n* Elle te rend ton salut, surprise.",
        },
        "spare_act": "Saluer",
        "attacks": ["* L'Armure abat son épée rouillée !", "* L'Armure te bouscule !"],
    },
]

# ── Boss (un tous les 10 étages, mécanique unique) ───────────────────────────
# mechanic : appliquée en combat — miroir (renvoie une part des dégâts subis),
# faux_heros (se régénère), vampire (vole des PV en frappant), horloger (frappe
# parfois deux fois), paresseux (saute parfois son tour), instable (effet aléatoire).
BOSSES: list[dict] = [
    {"key": "mirror", "name": "Gardien Miroir", "hp": 70, "atk": 7, "gold": 200, "xp": 120,
     "mechanic": "miroir",
     "idle": "* Le Gardien Miroir copie tes mouvements.",
     "acts": {"Vérifier": "* GARDIEN MIROIR — renvoie une partie de tes coups."},
     "spare_act": None,
     "attacks": ["* Le Miroir renvoie ton reflet tranchant !", "* Le Miroir éclate en éclats !"]},
    {"key": "ghost", "name": "Faux Héros", "hp": 80, "atk": 8, "gold": 240, "xp": 150,
     "mechanic": "faux_heros",
     "idle": "* Le Faux Héros sourit avec arrogance.",
     "acts": {"Vérifier": "* FAUX HÉROS — se régénère sans cesse."},
     "spare_act": None,
     "attacks": ["* Le Faux Héros porte un coup déloyal !", "* Le Faux Héros invoque des lames !"]},
    {"key": "vampire", "name": "Vampire Ancien", "hp": 85, "atk": 8, "gold": 260, "xp": 170,
     "mechanic": "vampire",
     "idle": "* Le Vampire Ancien lèche ses crocs.",
     "acts": {"Vérifier": "* VAMPIRE ANCIEN — se soigne en te blessant."},
     "spare_act": None,
     "attacks": ["* Le Vampire plante ses crocs !", "* Le Vampire draine ta vie !"],
     "inflicts": {"status": "saignement", "chance": 0.5, "turns": 3, "potency": 4}},
    {"key": "golem", "name": "Horloger Fou", "hp": 95, "atk": 9, "gold": 300, "xp": 200,
     "mechanic": "horloger",
     "idle": "* L'Horloger Fou remonte le temps.",
     "acts": {"Vérifier": "* HORLOGER FOU — agit parfois deux fois."},
     "spare_act": None,
     "attacks": ["* Le Temps se distord autour de toi !", "* L'Horloger accélère et frappe !"]},
    {"key": "golem", "name": "Colosse Paresseux", "hp": 110, "atk": 11, "gold": 320, "xp": 220,
     "mechanic": "paresseux",
     "idle": "* Le Colosse Paresseux baille bruyamment.",
     "acts": {"Vérifier": "* COLOSSE PARESSEUX — saute parfois son tour, mais frappe fort."},
     "spare_act": None,
     "attacks": ["* Le Colosse s'écroule sur toi !", "* Le Colosse balaie le sol !"]},
    {"key": "ghost", "name": "Spectre Instable", "hp": 90, "atk": 9, "gold": 340, "xp": 240,
     "mechanic": "instable",
     "idle": "* Le Spectre Instable clignote dans tous les sens.",
     "acts": {"Vérifier": "* SPECTRE INSTABLE — comportement imprévisible."},
     "spare_act": None,
     "attacks": ["* Le Spectre se dédouble et frappe !", "* Le Spectre hurle dans ta tête !"],
     "inflicts": {"status": "brulure", "chance": 0.45, "turns": 3, "potency": 3}},
]

# ── Boss final (étage 100) — multi-phase avec dialogue ───────────────────────
FINAL_BOSS: dict = {
    "key": "final", "name": "Gardien du Sommet", "atk": 10, "gold": 1500, "xp": 1500,
    "idle": "* Le Gardien du Sommet t'attend au bout du voyage.",
    "acts": {"Vérifier": "* GARDIEN DU SOMMET — l'ultime épreuve."},
    "spare_act": None,
    "attacks": ["* Le Gardien déchaîne sa puissance !", "* Une onde de choc te frappe !",
                "* Le Sommet tout entier tremble !"],
    "phases": [
        {"hp": 90, "mechanic": None, "dialogue": "* « Montre-moi ta détermination. »"},
        {"hp": 110, "mechanic": "vampire", "dialogue": "* « Tu m'impressionnes, mortel... »"},
        {"hp": 140, "mechanic": "horloger", "dialogue": "* PHASE FINALE — « VA-T'EN !!! »"},
    ],
}


def final_boss() -> dict:
    return dict(FINAL_BOSS)

# ── Salles ───────────────────────────────────────────────────────────────────
ROOM_LABELS = {
    "combat": "COMBAT", "repos": "REPOS", "tresor": "TRÉSOR",
    "piege": "PIÈGE", "evenement": "ÉVÉNEMENT", "enigme": "ÉNIGME", "boss": "BOSS",
    # Salles optionnelles (spéciales)
    "casino": "CASINO", "maudite": "MAUDITE", "laboratoire": "LABO",
    "lore": "LORE", "mini_boss": "MINI-BOSS",
}
ROOM_EMOJI = {
    "combat": "⚔️", "repos": "💤", "tresor": "💰", "piege": "🗡️",
    "evenement": "❓", "enigme": "🧩", "casino": "🎰", "maudite": "☠️",
    "laboratoire": "⚗️", "lore": "📖", "mini_boss": "👹",
}

_MAIN_TYPES = ["combat", "repos", "tresor", "piege", "evenement", "enigme"]
_SPECIAL_TYPES = ["casino", "maudite", "laboratoire", "lore", "mini_boss"]


def generate_floor(floor: int) -> dict:
    """Génère un étage : 3 salles obligatoires (différentes) + 2 optionnelles.

    Reproduit la structure « 3 salles principales + 2 salles optionnelles » du
    document de design. Le combat est favorisé parmi les obligatoires.
    """
    mandatory = random.sample(_MAIN_TYPES, 3)
    if "combat" not in mandatory and random.random() < 0.6:
        mandatory[random.randrange(3)] = "combat"
    optional = random.sample(_SPECIAL_TYPES, 2)
    return {
        "mandatory": mandatory, "m_done": [False, False, False],
        "optional": optional, "o_done": [False, False],
    }


def scale_monster(base: dict, floor: int) -> dict:
    """Renvoie une copie du monstre mise à l'échelle de l'étage."""
    m = dict(base)
    m["hp"] = int(base["hp"] * (1 + 0.12 * floor))
    m["atk"] = base["atk"] + floor // 4
    m["gold"] = int(base["gold"] * (1 + 0.10 * floor))
    m["xp"] = int(base["xp"] * (1 + 0.10 * floor))
    return m


def monster_for_floor(floor: int) -> dict:
    return scale_monster(random.choice(MONSTERS), floor)


def miniboss_for_floor(floor: int) -> dict:
    """Monstre d'élite (salle optionnelle mini-boss) : plus coriace, mieux payé."""
    m = scale_monster(random.choice(MONSTERS), floor)
    m["hp"] = int(m["hp"] * 1.5)
    m["atk"] += 2
    m["gold"] = int(m["gold"] * 1.6)
    m["xp"] = int(m["xp"] * 1.5)
    m["name"] = "Élite : " + m["name"]
    return m


def boss_for_floor(floor: int) -> dict:
    """Choisit un boss selon l'étage (cycle dans la liste)."""
    idx = (floor // 10 - 1) % len(BOSSES)
    return scale_monster(BOSSES[idx], floor)


# ── Événements (texte + 2 choix) ─────────────────────────────────────────────
# effect : dict appliqué au héros — clés possibles : hp, gold (deltas).
EVENTS: list[dict] = [
    {
        "text": "* Un autel ancien réclame une offrande.",
        "options": [
            ("Offrir de l'or (-30 or, +6 PV)", {"gold": -30, "hp": 6}),
            ("Ignorer l'autel", {}),
        ],
    },
    {
        "text": "* Un marchand louche te propose une fiole douteuse.",
        "options": [
            ("Boire la fiole (??)", {"random": [("hp", 8), ("hp", -6)]}),
            ("Refuser poliment", {}),
        ],
    },
    {
        "text": "* Un prisonnier t'implore de le libérer.",
        "options": [
            ("Le libérer (+50 or)", {"gold": 50}),
            ("Passer ton chemin", {}),
        ],
    },
    {
        "text": "* Une fontaine scintillante coule devant toi.",
        "options": [
            ("Boire (+10 PV)", {"hp": 10}),
            ("Remplir tes poches (+20 or)", {"gold": 20}),
        ],
    },
    {
        "text": "* Un coffre piégé claque de ses serrures.",
        "options": [
            ("Le forcer (??)", {"random": [("gold", 70), ("hp", -10)]}),
            ("Ne pas y toucher", {}),
        ],
    },
]

# ── Bribes de lore (salle optionnelle « lore ») ──────────────────────────────
LORE: list[str] = [
    "* On raconte que la Tour pousse d'un étage à chaque âme perdue.",
    "* Des gravures parlent d'un héros qui n'est jamais redescendu.",
    "* « La détermination seule fait gravir les étages. »",
    "* Un mur murmure ton nom... puis se tait.",
    "* Tu trouves le journal d'un aventurier. La dernière page est vierge.",
]

# ── Énigmes (QCM) ─────────────────────────────────────────────────────────────
RIDDLES: list[dict] = [
    {
        "q": "* « Plus j'ai de gardiens, moins je suis sûr. » Qui suis-je ?",
        "answers": ["Un secret", "Un trésor", "Un roi"],
        "correct": 0,
    },
    {
        "q": "* « Je monte mais ne descends jamais. » Quoi ?",
        "answers": ["L'âge", "La pluie", "L'ombre"],
        "correct": 0,
    },
    {
        "q": "* Combien d'étages compte la Tour ?",
        "answers": ["50", "100", "13"],
        "correct": 1,
    },
    {
        "q": "* « Je suis pris avant d'être donné. » Quoi ?",
        "answers": ["Un coup", "Un nom", "Le temps"],
        "correct": 0,
    },
]
