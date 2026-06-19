"""Couche d'accès SQLite (asynchrone via aiosqlite).

Expose une petite classe `Database` avec des helpers async (execute / fetchone
/ fetchall) et initialise le schéma au démarrage. Toutes les tables portent un
`guild_id` : le bot est multiserveur par construction.
"""

from __future__ import annotations

import os

import aiosqlite

# ── Schéma ─────────────────────────────────────────────────────────────────
# Idempotent (CREATE TABLE IF NOT EXISTS) : exécuté à chaque démarrage.
SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id              INTEGER PRIMARY KEY,
    prefix                TEXT    DEFAULT '!',
    log_channel_id        INTEGER,
    mute_role_id          INTEGER,
    verify_role_id        INTEGER,
    autorole_id           INTEGER,
    welcome_channel_id    INTEGER,
    welcome_message       TEXT,
    leave_message         TEXT,
    -- Salons de logs dédiés (suivis par ID → robustes au renommage)
    log_category_id           INTEGER,
    log_messages_channel_id   INTEGER,
    log_members_channel_id    INTEGER,
    log_mod_channel_id        INTEGER,
    log_system_channel_id     INTEGER,
    -- Économie & niveaux
    currency_symbol       TEXT    DEFAULT '🪙',
    currency_name         TEXT    DEFAULT 'pièces',
    daily_amount          INTEGER DEFAULT 200,
    xp_enabled            INTEGER DEFAULT 1,
    levelup_channel_id    INTEGER,
    levelup_announce      INTEGER DEFAULT 1,
    -- AutoMod (0 = off, 1 = on)
    anti_spam             INTEGER DEFAULT 0,
    anti_links            INTEGER DEFAULT 0,
    anti_invites          INTEGER DEFAULT 0,
    max_mentions          INTEGER DEFAULT 0,
    -- Anti-raid
    antiraid_enabled      INTEGER DEFAULT 0,
    antiraid_threshold    INTEGER DEFAULT 5,
    antiraid_window       INTEGER DEFAULT 10
);

CREATE TABLE IF NOT EXISTS warnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    moderator_id  INTEGER NOT NULL,
    reason        TEXT,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS blacklist_words (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id  INTEGER NOT NULL,
    word      TEXT    NOT NULL,
    UNIQUE(guild_id, word)
);

CREATE TABLE IF NOT EXISTS custom_commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    response    TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS autoresponses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    trigger     TEXT    NOT NULL,
    response    TEXT    NOT NULL,
    match_type  TEXT    DEFAULT 'contains'
);

CREATE TABLE IF NOT EXISTS reaction_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    emoji       TEXT    NOT NULL,
    role_id     INTEGER NOT NULL,
    UNIQUE(guild_id, message_id, emoji)
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    number      INTEGER NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open',
    claimed_by  INTEGER,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_open ON tickets(guild_id, user_id, status);

CREATE TABLE IF NOT EXISTS polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    message_id  INTEGER,
    author_id   INTEGER NOT NULL,
    question    TEXT    NOT NULL,
    options     TEXT    NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    choice      INTEGER NOT NULL,
    PRIMARY KEY (poll_id, user_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    due_at      TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(due_at);

CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    text        TEXT    NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

-- ── Statistiques ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS message_stats (
    guild_id    INTEGER NOT NULL,
    day         TEXT    NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, day)
);

CREATE TABLE IF NOT EXISTS user_message_stats (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS command_stats (
    guild_id    INTEGER NOT NULL,
    command     TEXT    NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, command)
);

-- ── Sécurité & sauvegardes ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS security_whitelist (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS user_blacklist (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    reason      TEXT,
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS backups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backups_guild ON backups(guild_id);

-- ── Économie & niveaux ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS economy (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    wallet      INTEGER NOT NULL DEFAULT 0,
    bank        INTEGER NOT NULL DEFAULT 0,
    last_daily  TEXT,
    last_work   TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS levels (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    xp          INTEGER NOT NULL DEFAULT 0,
    last_msg    REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    description TEXT,
    price       INTEGER NOT NULL,
    role_id     INTEGER,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS inventory (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    item_id     INTEGER NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, user_id, item_id)
);

CREATE TABLE IF NOT EXISTS level_rewards (
    guild_id    INTEGER NOT NULL,
    level       INTEGER NOT NULL,
    role_id     INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);

-- ── RPG « la Tour » ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rpg_runs (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    cls         TEXT    NOT NULL,
    trait       TEXT    NOT NULL,
    floor       INTEGER NOT NULL DEFAULT 1,
    hp          INTEGER NOT NULL,
    max_hp      INTEGER NOT NULL,
    atk_min     INTEGER NOT NULL,
    atk_max     INTEGER NOT NULL,
    crit        REAL    NOT NULL DEFAULT 0.12,
    potions     INTEGER NOT NULL DEFAULT 3,
    gold        INTEGER NOT NULL DEFAULT 0,
    gold_mult   REAL    NOT NULL DEFAULT 1.0,
    specials    TEXT    NOT NULL DEFAULT '[]',
    floor_state TEXT,
    defense     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS rpg_records (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    best_floor  INTEGER NOT NULL DEFAULT 0,
    runs        INTEGER NOT NULL DEFAULT 0,
    deaths      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS rpg_deaths (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    floor       INTEGER NOT NULL,
    cause       TEXT,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS rpg_upgrades (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    upgrade     TEXT    NOT NULL,
    level       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, upgrade)
);

CREATE TABLE IF NOT EXISTS rpg_gear (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    item_key    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id, item_key)
);

CREATE TABLE IF NOT EXISTS rpg_loadout (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    weapon      TEXT,
    armor       TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS rpg_achievements (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    achievement TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id, achievement)
);

CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_reaction_roles_msg   ON reaction_roles(message_id);
CREATE INDEX IF NOT EXISTS idx_levels_guild_xp      ON levels(guild_id, xp);
CREATE INDEX IF NOT EXISTS idx_rpg_records_floor    ON rpg_records(guild_id, best_floor);
"""

# Colonnes ajoutées après coup : on les crée si elles manquent (migration douce),
# pour ne pas casser une base de données déjà existante. Structure : table → {colonne: DDL}.
_MIGRATIONS: dict[str, dict[str, str]] = {
    "guild_config": {
        "log_category_id": "INTEGER",
        "log_messages_channel_id": "INTEGER",
        "log_members_channel_id": "INTEGER",
        "log_mod_channel_id": "INTEGER",
        "log_system_channel_id": "INTEGER",
        "currency_symbol": "TEXT DEFAULT '🪙'",
        "currency_name": "TEXT DEFAULT 'pièces'",
        "daily_amount": "INTEGER DEFAULT 200",
        "xp_enabled": "INTEGER DEFAULT 1",
        "levelup_channel_id": "INTEGER",
        "levelup_announce": "INTEGER DEFAULT 1",
        "ticket_category_id": "INTEGER",
        "ticket_staff_role_id": "INTEGER",
        "ticket_log_channel_id": "INTEGER",
        "ticket_counter": "INTEGER DEFAULT 0",
        "antinuke_enabled": "INTEGER DEFAULT 0",
        "antinuke_threshold": "INTEGER DEFAULT 3",
        "antinuke_window": "INTEGER DEFAULT 30",
        "antinuke_action": "TEXT DEFAULT 'strip'",
        "welcome_image": "TEXT",
        "leave_image": "TEXT",
        "ticket_panel_title": "TEXT",
        "ticket_panel_message": "TEXT",
        "ticket_panel_image": "TEXT",
    },
    "rpg_runs": {
        "floor_state": "TEXT",
        "defense": "INTEGER DEFAULT 0",
    },
}


class Database:
    """Connexion SQLite asynchrone partagée par tout le bot (bot.db)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Ouvre la connexion, active le mode WAL et crée le schéma."""
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row  # accès colonnes par nom
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        await self.conn.execute("PRAGMA foreign_keys=ON;")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        """Ajoute les colonnes manquantes (mise à niveau douce, multi-tables)."""
        changed = False
        for table, columns in _MIGRATIONS.items():
            async with self.conn.execute(f"PRAGMA table_info({table})") as cur:
                existing = {row[1] for row in await cur.fetchall()}
            for col, ddl in columns.items():
                if col not in existing:
                    await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                    changed = True
        if changed:
            await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    async def execute(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        """Exécute une requête d'écriture et committe."""
        assert self.conn is not None, "Database non connectée"
        cur = await self.conn.execute(query, params)
        await self.conn.commit()
        return cur

    async def fetchone(self, query: str, params: tuple = ()) -> aiosqlite.Row | None:
        assert self.conn is not None, "Database non connectée"
        async with self.conn.execute(query, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
        assert self.conn is not None, "Database non connectée"
        async with self.conn.execute(query, params) as cur:
            return list(await cur.fetchall())
