"""Opérations de monnaie virtuelle, réutilisables par tous les modules.

Centraliser ici permet à d'autres systèmes (jeux, récompenses…) de créditer ou
débiter un joueur sans dupliquer la logique SQL.
"""

from __future__ import annotations

from core.database import Database


async def get_account(db: Database, guild_id: int, user_id: int) -> dict:
    """Retourne {wallet, bank} en garantissant l'existence du compte."""
    await db.execute(
        "INSERT OR IGNORE INTO economy (guild_id, user_id) VALUES (?, ?)",
        (guild_id, user_id),
    )
    row = await db.fetchone(
        "SELECT wallet, bank FROM economy WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    return {"wallet": row["wallet"], "bank": row["bank"]}


async def add_wallet(db: Database, guild_id: int, user_id: int, amount: int) -> None:
    """Crédite (ou débite si négatif) le porte-monnaie."""
    await get_account(db, guild_id, user_id)
    await db.execute(
        "UPDATE economy SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
        (amount, guild_id, user_id),
    )


async def deposit(db: Database, guild_id: int, user_id: int, amount: int) -> bool:
    """Déplace `amount` du porte-monnaie vers la banque. False si fonds insuffisants."""
    acc = await get_account(db, guild_id, user_id)
    if amount <= 0 or acc["wallet"] < amount:
        return False
    await db.execute(
        "UPDATE economy SET wallet = wallet - ?, bank = bank + ? WHERE guild_id = ? AND user_id = ?",
        (amount, amount, guild_id, user_id),
    )
    return True


async def withdraw(db: Database, guild_id: int, user_id: int, amount: int) -> bool:
    """Déplace `amount` de la banque vers le porte-monnaie. False si fonds insuffisants."""
    acc = await get_account(db, guild_id, user_id)
    if amount <= 0 or acc["bank"] < amount:
        return False
    await db.execute(
        "UPDATE economy SET bank = bank - ?, wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
        (amount, amount, guild_id, user_id),
    )
    return True


async def transfer(
    db: Database, guild_id: int, sender_id: int, receiver_id: int, amount: int
) -> bool:
    """Transfère depuis le porte-monnaie de l'émetteur vers celui du destinataire."""
    sender = await get_account(db, guild_id, sender_id)
    if amount <= 0 or sender["wallet"] < amount:
        return False
    await add_wallet(db, guild_id, sender_id, -amount)
    await add_wallet(db, guild_id, receiver_id, amount)
    return True
