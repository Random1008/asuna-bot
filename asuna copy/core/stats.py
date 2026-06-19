"""Suivi et agrégation des statistiques du serveur (messages, commandes).

Helpers réutilisés par la commande /stats et par le dashboard web.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.database import Database


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ── Incrémentation ────────────────────────────────────────────────────────────
async def incr_message(db: Database, guild_id: int, user_id: int) -> None:
    await db.execute(
        "INSERT INTO message_stats (guild_id, day, count) VALUES (?, ?, 1) "
        "ON CONFLICT(guild_id, day) DO UPDATE SET count = count + 1", (guild_id, _today()))
    await db.execute(
        "INSERT INTO user_message_stats (guild_id, user_id, count) VALUES (?, ?, 1) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1", (guild_id, user_id))


async def incr_command(db: Database, guild_id: int, command: str) -> None:
    await db.execute(
        "INSERT INTO command_stats (guild_id, command, count) VALUES (?, ?, 1) "
        "ON CONFLICT(guild_id, command) DO UPDATE SET count = count + 1", (guild_id, command))


# ── Agrégation ────────────────────────────────────────────────────────────────
async def daily_series(db: Database, guild_id: int, days: int = 14) -> list[tuple[str, int]]:
    """Messages par jour sur les `days` derniers jours (zéros inclus)."""
    start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    rows = await db.fetchall(
        "SELECT day, count FROM message_stats WHERE guild_id = ? AND day >= ?",
        (guild_id, start.isoformat()))
    found = {r["day"]: r["count"] for r in rows}
    return [((start + timedelta(days=i)).isoformat(), found.get((start + timedelta(days=i)).isoformat(), 0))
            for i in range(days)]


async def messages_total(db: Database, guild_id: int) -> int:
    r = await db.fetchone("SELECT COALESCE(SUM(count), 0) AS s FROM message_stats WHERE guild_id = ?", (guild_id,))
    return r["s"] if r else 0


async def messages_window(db: Database, guild_id: int, days: int) -> int:
    start = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    r = await db.fetchone(
        "SELECT COALESCE(SUM(count), 0) AS s FROM message_stats WHERE guild_id = ? AND day >= ?", (guild_id, start))
    return r["s"] if r else 0


async def messages_today(db: Database, guild_id: int) -> int:
    r = await db.fetchone("SELECT count FROM message_stats WHERE guild_id = ? AND day = ?", (guild_id, _today()))
    return r["count"] if r else 0


async def top_users(db: Database, guild_id: int, n: int = 10) -> list:
    return await db.fetchall(
        "SELECT user_id, count FROM user_message_stats WHERE guild_id = ? ORDER BY count DESC LIMIT ?", (guild_id, n))


async def top_commands(db: Database, guild_id: int, n: int = 10) -> list:
    return await db.fetchall(
        "SELECT command, count FROM command_stats WHERE guild_id = ? ORDER BY count DESC LIMIT ?", (guild_id, n))


async def economy_top(db: Database, guild_id: int, n: int = 10) -> list:
    return await db.fetchall(
        "SELECT user_id, (wallet + bank) AS total FROM economy WHERE guild_id = ? ORDER BY total DESC LIMIT ?",
        (guild_id, n))


async def levels_top(db: Database, guild_id: int, n: int = 10) -> list:
    return await db.fetchall(
        "SELECT user_id, xp FROM levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ?", (guild_id, n))
