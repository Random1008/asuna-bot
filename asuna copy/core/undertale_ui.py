"""Rendu de la scène de combat « façon Undertale » en image (Pillow).

La scène entière (zone de jeu + boîte de dialogue + ligne LV/HP) est dessinée
dans une seule image PNG, que le bot envoie comme image d'embed. Les boutons
FIGHT/ACT/ITEM/MERCY, eux, sont de vrais boutons Discord ajoutés sous l'embed.

Pourquoi tout dessiner en image : dans un embed Discord, l'image s'affiche
*sous* le texte. Pour respecter l'empilement Undertale (jeu en haut, dialogue
au milieu), on rend donc le tout dans l'image, et on garde l'embed minimal.
"""

from __future__ import annotations

import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# ── Dimensions & couleurs ────────────────────────────────────────────────────
W, H = 800, 600
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 200, 40)
YELLOW = (255, 200, 0)
ORANGE = (255, 140, 0)
RED = (220, 50, 50)
DARKRED = (90, 20, 20)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/Library/Fonts/Arial.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ── Sprites pixel-art procéduraux ────────────────────────────────────────────
# Chaque sprite est une grille de caractères ; chaque caractère → une couleur.
# Dessiné case par case en gros « pixels » → look pixel-art authentique.
_PALETTE = {
    "w": WHITE, "g": (80, 220, 90), "p": (200, 120, 230), "r": (230, 70, 70),
    "y": YELLOW, "o": ORANGE, "k": (25, 25, 25), "b": (90, 160, 230),
}

SPRITES: dict[str, list[str]] = {
    "slime": [
        "          ",
        "   gggg   ",
        "  gggggg  ",
        " gggggggg ",
        "gggggggggg",
        "gkggggkggg",
        "gggggggggg",
        "ggkkkkkkgg",
        "gggggggggg",
        "gg g gg gg",
    ],
    "ghost": [
        "  wwwww   ",
        " wwwwwww  ",
        "wwwwwwwww ",
        "wwkwwwkww ",
        "wwwwwwwww ",
        "wwwwwwwww ",
        "wkwwwwwkw ",
        "wwkkkkkww ",
        "wwwwwwwww ",
        "w w w w w ",
    ],
    "golem": [
        " kkkkkkkk ",
        "kbbbbbbbbk",
        "kbrbbbbrbk",
        "kbbbbbbbbk",
        "kbbbkkbbbk",
        "kbbbbbbbbk",
        " kbbbbbbk ",
        "  k kk k  ",
        "  k    k  ",
        "  kk  kk  ",
    ],
    # ── Boss : sprites dédiés ──
    "mirror": [
        "    ww    ",
        "   wbbw   ",
        "  wbbbbw  ",
        " wbbbbbbw ",
        "wbbbwwbbbw",
        " wbbbbbbw ",
        "  wbbbbw  ",
        "   wbbw   ",
        "    ww    ",
    ],
    "vampire": [
        "k k    k k",
        "kkk    kkk",
        "kkkkkkkkkk",
        " kkrkkrkk ",
        " kkkkkkkk ",
        " kkwkkwkk ",
        "  kkkkkk  ",
        "   k  k   ",
    ],
    "final": [
        " pppppppp ",
        "pppppppppp",
        "prpppppprp",
        "pppppppppp",
        "ppwwppwwpp",
        "pppppppppp",
        "pp pppp pp",
        "p  pppp  p",
        "p pp  pp p",
    ],
}


def _draw_sprite(draw: ImageDraw.ImageDraw, grid: list[str], cx: int, cy: int, cell: int = 16) -> None:
    """Dessine un sprite (grille de caractères) centré sur (cx, cy)."""
    rows = len(grid)
    cols = max(len(r) for r in grid)
    x0 = cx - (cols * cell) // 2
    y0 = cy - (rows * cell) // 2
    for j, row in enumerate(grid):
        for i, ch in enumerate(row):
            if ch == " ":
                continue
            color = _PALETTE.get(ch, WHITE)
            x, y = x0 + i * cell, y0 + j * cell
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=color)


# ── Texte avec retour à la ligne ─────────────────────────────────────────────
def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        lines.append(current)
    return lines


# ── Rendu principal ──────────────────────────────────────────────────────────
def render_battle(
    *,
    dialogue: str,
    lv: int,
    hp: int,
    max_hp: int,
    monster: str | None = "slime",
    monster_name: str | None = None,
    flash: bool = False,
    soul: bool = False,
) -> BytesIO:
    """Génère la scène de combat et renvoie un PNG en mémoire (BytesIO).

    - `flash` : inverse brièvement le fond (effet d'impact d'attaque).
    - `soul`  : affiche le cœur rouge (l'âme) dans la zone de jeu (tour de défense).
    """
    bg = WHITE if flash else BLACK
    fg = BLACK if flash else WHITE
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    # Zone de jeu (cadre vert) ------------------------------------------------
    gp = (20, 20, W - 20, 300)
    d.rectangle(gp, outline=(GREEN if not flash else BLACK), width=4)
    cx, cy = W // 2, 160
    if soul:
        # Le cœur (âme) rouge, centré : phase de défense.
        _draw_heart(d, cx, cy, 18)
    elif monster and monster in SPRITES:
        _draw_sprite(d, SPRITES[monster], cx, cy, cell=16)
    if monster_name:
        nf = _font(22)
        tw = d.textlength(monster_name, font=nf)
        d.text((cx - tw / 2, 250), monster_name, font=nf, fill=fg)

    _put_dialogue(d, dialogue, fg=fg)
    _draw_bottom(d, hp=hp, max_hp=max_hp, lv=lv, fg=fg)
    return _png(img)


# ── Helpers partagés (dialogue, ligne du bas, export PNG) ────────────────────
def _png(img: Image.Image) -> BytesIO:
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _put_dialogue(d: ImageDraw.ImageDraw, text: str, fg=WHITE) -> None:
    """Cadre blanc + texte enveloppé (boîte de dialogue Undertale)."""
    box = (40, 330, W - 40, 470)
    d.rectangle(box, outline=fg, width=4)
    font = _font(26)
    ty = box[1] + 22
    for line in _wrap(d, text, font, max_width=(box[2] - box[0]) - 40)[:4]:
        d.text((box[0] + 22, ty), line, font=font, fill=fg)
        ty += 34


def _draw_bottom(d: ImageDraw.ImageDraw, *, hp: int, max_hp: int, lv: int | None = None,
                 gold: int | None = None, fg=WHITE) -> None:
    """Ligne du bas : LV (combat) ou OR (tour) + barre de PV."""
    sf = _font(28)
    y = 515
    if lv is not None:
        d.text((150, y), f"LV {lv}", font=sf, fill=fg)
    elif gold is not None:
        d.text((110, y), f"OR {gold}", font=sf, fill=YELLOW)
    d.text((320, y), "HP", font=sf, fill=fg)
    bar_x, bar_w, bar_h = 372, 130, 26
    d.rectangle((bar_x, y, bar_x + bar_w, y + bar_h), fill=DARKRED)
    fill_w = int(bar_w * max(0, hp) / max_hp) if max_hp else 0
    if fill_w > 0:
        d.rectangle((bar_x, y, bar_x + fill_w, y + bar_h), fill=YELLOW)
    d.text((bar_x + bar_w + 18, y), f"{max(0, hp)} / {max_hp}", font=sf, fill=fg)


def render_tower(*, floor: int, hp: int, max_hp: int, gold: int, doors: list[str]) -> BytesIO:
    """Écran de choix de porte d'un étage."""
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, W - 20, 300), outline=GREEN, width=4)

    title = f"ÉTAGE {floor}"
    tf = _font(36)
    tw = d.textlength(title, font=tf)
    d.text((W / 2 - tw / 2, 38), title, font=tf, fill=WHITE)

    from core.rpg_data import ROOM_LABELS  # import local pour éviter un cycle
    n = len(doors)
    bw, gap = 200, 30
    total = n * bw + (n - 1) * gap
    x0 = (W - total) / 2
    bf = _font(20)
    for i, door in enumerate(doors):
        x = x0 + i * (bw + gap)
        d.rectangle((x, 110, x + bw, 250), outline=WHITE, width=3)
        label = f"Porte {i + 1}"
        lw = d.textlength(label, font=bf)
        d.text((x + bw / 2 - lw / 2, 135), label, font=bf, fill=WHITE)
        kind = ROOM_LABELS.get(door, door.upper())
        kw = d.textlength(kind, font=bf)
        d.text((x + bw / 2 - kw / 2, 195), kind, font=bf, fill=YELLOW)

    _put_dialogue(d, "* Quelle porte vas-tu franchir ?")
    _draw_bottom(d, hp=hp, max_hp=max_hp, gold=gold)
    return _png(img)


def _room_box(d, x, y, w, h, label, done) -> None:
    color = GREEN if done else WHITE
    d.rectangle((x, y, x + w, y + h), outline=color, width=3)
    f = _font(18)
    lw = d.textlength(label, font=f)
    d.text((x + w / 2 - lw / 2, y + h / 2 - 18), label, font=f, fill=(GREEN if done else YELLOW))
    if done:
        tag = "FAIT"
        tw = d.textlength(tag, font=_font(15))
        d.text((x + w / 2 - tw / 2, y + h - 24), tag, font=_font(15), fill=GREEN)


def _row_of_boxes(d, items, top, box_h) -> None:
    """Dessine une rangée de boîtes de salles centrée. items = [(label, done)]."""
    n = len(items)
    bw, gap = 150, 24
    total = n * bw + (n - 1) * gap
    x0 = (W - total) / 2
    for i, (label, done) in enumerate(items):
        _room_box(d, x0 + i * (bw + gap), top, bw, box_h, label, done)


def render_floormap(*, floor: int, hp: int, max_hp: int, gold: int,
                    mandatory: list[tuple[str, bool]], optional: list[tuple[str, bool]],
                    can_ascend: bool) -> BytesIO:
    """Carte d'un étage : 3 salles obligatoires + 2 optionnelles."""
    from core.rpg_data import ROOM_LABELS
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, W - 20, 300), outline=GREEN, width=4)

    title = f"ÉTAGE {floor}"
    tf = _font(30)
    d.text((W / 2 - d.textlength(title, font=tf) / 2, 28), title, font=tf, fill=WHITE)

    sf = _font(16)
    d.text((40, 70), "OBLIGATOIRES", font=sf, fill=WHITE)
    _row_of_boxes(d, [(ROOM_LABELS.get(t, t.upper()), done) for t, done in mandatory], 92, 70)
    d.text((40, 178), "BONUS (optionnel)", font=sf, fill=WHITE)
    _row_of_boxes(d, [(ROOM_LABELS.get(t, t.upper()), done) for t, done in optional], 200, 70)

    msg = ("* Toutes les salles franchies — tu peux monter !" if can_ascend
           else "* Franchis les 3 salles obligatoires pour monter.")
    _put_dialogue(d, msg)
    _draw_bottom(d, hp=hp, max_hp=max_hp, gold=gold)
    return _png(img)


def render_scene(*, dialogue: str, hp: int, max_hp: int, floor: int, gold: int,
                 label: str | None = None, monster: str | None = None) -> BytesIO:
    """Écran générique (repos, trésor, événement, énigme…)."""
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, W - 20, 300), outline=GREEN, width=4)
    d.text((35, 30), f"ÉTAGE {floor}", font=_font(20), fill=WHITE)
    if label:
        lf = _font(40)
        lw = d.textlength(label, font=lf)
        d.text((W / 2 - lw / 2, 90), label, font=lf, fill=YELLOW)
    if monster and monster in SPRITES:
        _draw_sprite(d, SPRITES[monster], W // 2, 180, cell=14)
    _put_dialogue(d, dialogue)
    _draw_bottom(d, hp=hp, max_hp=max_hp, gold=gold)
    return _png(img)


def render_dodge(*, danger: set, soul: int, lanes: int, hp: int, max_hp: int, dialogue: str) -> BytesIO:
    """Phase d'esquive (bullet-hell tour par tour) : couloirs + projectiles + âme."""
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    box = (20, 20, W - 20, 300)
    d.rectangle(box, outline=GREEN, width=4)
    lane_w = (box[2] - box[0]) / lanes
    for i in range(lanes):
        cx = box[0] + lane_w * (i + 0.5)
        # séparateurs de couloirs
        if i > 0:
            x = box[0] + lane_w * i
            d.line((x, box[1] + 6, x, box[3] - 6), fill=(40, 80, 40), width=1)
        if i in danger:  # projectiles rouges qui « tombent »
            for yy in (45, 95, 145):
                d.rectangle((cx - 20, yy, cx + 20, yy + 26), fill=RED)
        if i == soul:    # l'âme (cœur)
            _draw_heart(d, int(cx), 252, 12)
    _put_dialogue(d, dialogue)
    _draw_bottom(d, hp=hp, max_hp=max_hp, lv=1)
    return _png(img)


def _draw_heart(draw: ImageDraw.ImageDraw, cx: int, cy: int, s: int) -> None:
    """Dessine le cœur rouge de l'âme en gros pixels."""
    grid = [
        " rr rr ",
        "rrrrrrr",
        "rrrrrrr",
        " rrrrr ",
        "  rrr  ",
        "   r   ",
    ]
    _draw_sprite(draw, grid, cx, cy, cell=s)


# Exécution directe : génère un aperçu sur disque (pour tester le rendu).
if __name__ == "__main__":
    buf = render_battle(
        dialogue="Un Slime gluant bloque le passage !",
        lv=1, hp=20, max_hp=20, monster="slime", monster_name="Slime gluant",
    )
    with open("/tmp/battle_preview.png", "wb") as f:
        f.write(buf.read())
    print("Aperçu écrit dans /tmp/battle_preview.png")
