"""
Модуль работы с базой данных SQLite (асинхронный, через aiosqlite).
Все таблицы создаются автоматически при первом запуске.
"""

import aiosqlite
import os
from datetime import datetime, timedelta
import secrets

DB_PATH = os.environ.get("DB_PATH", "passes.db")


async def init_db():
    """Создаёт все таблицы, если их ещё нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                full_name  TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                org_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                address     TEXT NOT NULL,
                created_by  INTEGER,
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (created_by) REFERENCES users(user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                user_id     INTEGER,
                org_id      INTEGER,
                role        TEXT NOT NULL,
                assigned_by INTEGER,
                assigned_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, org_id, role),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (org_id) REFERENCES organizations(org_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS passes (
                pass_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                pass_code    TEXT UNIQUE NOT NULL,
                user_id      INTEGER NOT NULL,
                username     TEXT NOT NULL,
                org_id       INTEGER NOT NULL,
                issued_by    INTEGER NOT NULL,
                issued_at    TEXT DEFAULT (datetime('now')),
                valid_until  TEXT NOT NULL,
                active       INTEGER DEFAULT 1,
                cancelled_at  TEXT,
                cancelled_by  INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (org_id) REFERENCES organizations(org_id),
                FOREIGN KEY (issued_by) REFERENCES users(user_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS guard_logs (
                log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                pass_id     INTEGER,
                guard_id    INTEGER NOT NULL,
                org_id      INTEGER NOT NULL,
                action      TEXT NOT NULL,
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (pass_id) REFERENCES passes(pass_id),
                FOREIGN KEY (guard_id) REFERENCES users(user_id),
                FOREIGN KEY (org_id) REFERENCES organizations(org_id)
            )
        """)

        await db.commit()


# ── Пользователи ──

async def upsert_user(user_id: int, username: str, full_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=?, full_name=?",
            (user_id, username, full_name, username, full_name)
        )
        await db.commit()


async def get_user_by_username(username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        )
        return await cur.fetchone()


# ── Организации ──

async def create_organization(name: str, address: str, created_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO organizations (name, address, created_by) VALUES (?, ?, ?)",
            (name, address, created_by)
        )
        await db.commit()
        return cur.lastrowid


async def get_all_organizations():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM organizations ORDER BY name")
        return await cur.fetchall()


async def get_organization(org_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM organizations WHERE org_id = ?", (org_id,))
        return await cur.fetchone()


# ── Роли ──

async def assign_role(user_id: int, org_id: int, role: str, assigned_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO roles (user_id, org_id, role, assigned_by) "
            "VALUES (?, ?, ?, ?)",
            (user_id, org_id, role, assigned_by)
        )
        await db.commit()


async def get_user_role(user_id: int, org_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT role FROM roles WHERE user_id = ? AND org_id = ? "
            "ORDER BY CASE role "
            "WHEN 'organizer' THEN 1 WHEN 'admin' THEN 2 WHEN 'guard' THEN 3 "
            "END LIMIT 1",
            (user_id, org_id)
        )
        row = await cur.fetchone()
        return row["role"] if row else None


async def get_user_roles_any(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT r.*, o.name as org_name, o.address as org_address "
            "FROM roles r JOIN organizations o ON r.org_id = o.org_id "
            "WHERE r.user_id = ?", (user_id,)
        )
        return await cur.fetchall()


async def get_org_members(org_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT r.*, u.username, u.full_name FROM roles r "
            "JOIN users u ON r.user_id = u.user_id "
            "WHERE r.org_id = ? ORDER BY r.role", (org_id,)
        )
        return await cur.fetchall()


async def get_guard_orgs(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT o.* FROM roles r JOIN organizations o ON r.org_id = o.org_id "
            "WHERE r.user_id = ? AND r.role = 'guard'", (user_id,)
        )
        return await cur.fetchall()


# ── Пропуска ──

async def create_pass(user_id: int, username: str, org_id: int,
                      issued_by: int, valid_until: str):
    pass_code = secrets.token_hex(8).upper()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO passes (pass_code, user_id, username, org_id, "
            "issued_by, valid_until) VALUES (?, ?, ?, ?, ?, ?)",
            (pass_code, user_id, username, org_id, issued_by, valid_until)
        )
        await db.commit()
        return pass_code, cur.lastrowid


async def get_pass_by_code(pass_code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM passes WHERE pass_code = ?", (pass_code,)
        )
        return await cur.fetchone()


async def get_user_passes(user_id: int, active_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        q = ("SELECT p.*, o.name as org_name, o.address as org_address "
             "FROM passes p JOIN organizations o ON p.org_id = o.org_id "
             "WHERE p.user_id = ?")
        if active_only:
            q += f" AND p.active = 1 AND p.valid_until > '{now}'"
        q += " ORDER BY p.valid_until DESC"
        cur = await db.execute(q, (user_id,))
        return await cur.fetchall()


async def get_org_passes(org_id: int, active_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        q = ("SELECT p.*, o.name as org_name FROM passes p "
             "JOIN organizations o ON p.org_id = o.org_id "
             "WHERE p.org_id = ?")
        if active_only:
            q += f" AND p.active = 1 AND p.valid_until > '{now}'"
        q += " ORDER BY p.valid_until DESC"
        cur = await db.execute(q, (org_id,))
        return await cur.fetchall()


async def cancel_pass(pass_id: int, cancelled_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE passes SET active = 0, cancelled_at = datetime('now'), "
            "cancelled_by = ? WHERE pass_id = ?",
            (cancelled_by, pass_id)
        )
        await db.commit()


async def extend_pass(pass_id: int, new_valid_until: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE passes SET valid_until = ?, active = 1 "
            "WHERE pass_id = ?",
            (new_valid_until, pass_id)
        )
        await db.commit()


def is_pass_active(pass_row) -> bool:
    if not pass_row or not pass_row["active"]:
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return pass_row["valid_until"] > now


# ── Журнал охраны ──

async def log_guard_action(pass_id, guard_id: int, org_id: int,
                           action: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO guard_logs (pass_id, guard_id, org_id, action) "
            "VALUES (?, ?, ?, ?)",
            (pass_id, guard_id, org_id, action)
        )
        await db.commit()


async def get_org_logs(org_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT gl.*, p.pass_code, p.username as pass_username, "
            "u.username as guard_username "
            "FROM guard_logs gl "
            "LEFT JOIN passes p ON gl.pass_id = p.pass_id "
            "JOIN users u ON gl.guard_id = u.user_id "
            "WHERE gl.org_id = ? ORDER BY gl.created_at DESC LIMIT 50",
            (org_id,)
        )
        return await cur.fetchall()
