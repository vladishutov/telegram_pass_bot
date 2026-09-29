"""
Telegram-бот электронных пропусков.
Главный файл — все обработчики, диспетчер, запуск.

Запуск:  python bot.py
Токен:   переменная окружения BOT_TOKEN
"""

import os
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

import database as db
import keyboards as kb
from states import (
    OrgCreate, AssignRole, IssuePass, CancelPass,
    ExtendPass, GuardAuth, GuardConsole
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("Установите переменную окружения BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ═══════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════

async def get_user_orgs_with_role(user_id: int, min_role: str = "admin"):
    """Возвращает организации, где у пользователя есть нужная роль."""
    roles = await db.get_user_roles_any(user_id)
    role_priority = {"organizer": 1, "admin": 2, "guard": 3}
    min_priority = role_priority.get(min_role, 3)
    result = []
    for r in roles:
        if role_priority.get(r["role"], 3) <= min_priority:
            org = await db.get_organization(r["org_id"])
            if org:
                result.append(org)
    return result


def fmt_datetime(dt_str: str) -> str:
    """Форматирует строку времени для вывода."""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return dt_str


def parse_duration(text: str):
    """Парсит срок действия пропуска.
    Форматы: '3' (3 дня), '5ч' (5 часов), '30.09' (дата), '30.09.2026' (дата)
    """
    text = text.strip().lower()
    now = datetime.now()

    if text.endswith("д"):
        try:
            days = int(text[:-1])
            return (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return None
    elif text.endswith("ч"):
        try:
            hours = int(text[:-1])
            return (now + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return None
    else:
        try:
            days = int(text)
            return (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
        for fmt in ("%d.%m.%Y", "%d.%m"):
            try:
                dt = datetime.strptime(text, fmt)
                if fmt == "%d.%m":
                    dt = dt.replace(year=now.year, hour=23, minute=59)
                else:
                    dt = dt.replace(hour=23, minute=59)
                return dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
    return None


async def safe_edit(call: CallbackQuery, text: str, markup=None):
    """Безопасное редактирование сообщения."""
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        await call.message.answer(text, reply_markup=markup)


# ═══════════════════════════════════════════════
#  /start — ГЛАВНОЕ МЕНЮ
# ═══════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    await db.upsert_user(user.id, user.username or "", user.full_name)
    await message.answer(
        "👋 Добро пожаловать в систему электронных пропусков!\n\n"
        "Выберите вашу роль:",
        reply_markup=kb.main_menu_kb()
    )


@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(call, "Выберите вашу роль:", kb.main_menu_kb())


@dp.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    roles = await db.get_user_roles_any(user_id)
    if not roles:
        await safe_edit(call, "Выберите вашу роль:", kb.main_menu_kb())
        return
    has_organizer = any(r["role"] == "organizer" for r in roles)
    has_admin = any(r["role"] == "admin" for r in roles)
    if has_organizer:
        await safe_edit(call, "Меню организатора:", kb.organizer_menu_kb())
    elif has_admin:
        await safe_edit(call, "Меню администратора:", kb.admin_menu_kb())
    else:
        await safe_edit(call, "Выберите вашу роль:", kb.main_menu_kb())


# ═══════════════════════════════════════════════
#  РОЛЬ: ОРГАНИЗАТОР
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "role_organizer")
async def cb_organizer(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    roles = await db.get_user_roles_any(user_id)
    is_organizer = any(r["role"] == "organizer" for r in roles)
    if is_organizer:
        await safe_edit(call, "Меню организатора:", kb.organizer_menu_kb())
    else:
        await safe_edit(
            call,
            "Вы не являетесь организатором.\n\n"
            "Организатором может назначить другой организатор "
            "или вы можете создать новую организацию, "
            "после чего автоматически станете её организатором.\n\n"
            "Хотите создать организацию?",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Создать организацию", callback_data="org_create")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
            ])
        )


@dp.callback_query(F.data == "org_create")
async def cb_org_create(call: CallbackQuery, state: FSMContext):
    await state.set_state(OrgCreate.waiting_name)
    await safe_edit(call, "Введите название организации:", kb.cancel_kb())


@dp.message(OrgCreate.waiting_name)
async def org_name_received(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 100:
        await message.answer("Название слишком длинное или пустое. Попробуйте ещё раз:")
        return
    await state.update_data(name=name)
    await state.set_state(OrgCreate.waiting_address)
    await message.answer("Введите адрес организации:", reply_markup=kb.cancel_kb())


@dp.message(OrgCreate.waiting_address)
async def org_address_received(message: Message, state: FSMContext):
    address = message.text.strip()
    if not address:
        await message.answer("Адрес не может быть пустым. Попробуйте ещё раз:")
        return
    data = await state.get_data()
    user_id = message.from_user.id
    org_id = await db.create_organization(data["name"], address, user_id)
    await db.assign_role(user_id, org_id, "organizer", user_id)
    await state.clear()
    await message.answer(
        f"✅ Организация создана!\n\n"
        f"Название: {data['name']}\n"
        f"Адрес: {address}\n\n"
        f"Вы назначены организатором этой организации.",
        reply_markup=kb.organizer_menu_kb()
    )


# ── Список организаций ──

@dp.callback_query(F.data == "org_list")
async def cb_org_list(call: CallbackQuery):
    user_id = call.from_user.id
    orgs = await get_user_orgs_with_role(user_id, "organizer")
    if not orgs:
        await safe_edit(call, "У вас пока нет организаций.", kb.back_to_main_kb())
        return
    await safe_edit(call, "Ваши организации:", kb.orgs_list_kb(orgs))


@dp.callback_query(F.data.startswith("org_"))
async def cb_org_select(call: CallbackQuery):
    org_id = int(call.data.split("_")[1])
    org = await db.get_organization(org_id)
    if not org:
        await safe_edit(call, "Организация не найдена.", kb.back_to_main_kb())
        return
    members = await db.get_org_members(org_id)
    members_text = "\n".join(
        f"  • @{m['username'] or 'без username'} — {m['role']}"
        for m in members
    ) if members else "  Нет участников"
    await safe_edit(
        call,
        f"🏢 {org['name']}\n"
        f"📍 {org['address']}\n\n"
        f"Участники:\n{members_text}",
        kb.back_to_main_kb()
    )


# ═══════════════════════════════════════════════
#  РОЛЬ: АДМИНИСТРАТОР
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "role_admin")
async def cb_admin(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    roles = await db.get_user_roles_any(user_id)
    has_admin = any(r["role"] in ("admin", "organizer") for r in roles)
    if has_admin:
        await safe_edit(call, "Меню администратора:", kb.admin_menu_kb())
    else:
        await safe_edit(
            call,
            "Вы не являетесь администратором ни в одной организации.\n\n"
            "Обратитесь к организатору, чтобы вас назначили.",
            kb.back_to_main_kb()
        )


# ═══════════════════════════════════════════════
#  ВЫДАЧА ПРОПУСКА
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "pass_issue")
async def cb_pass_issue(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    orgs = await get_user_orgs_with_role(user_id, "admin")
    if not orgs:
        await safe_edit(call, "Вы не администратор ни в одной организации.", kb.back_to_main_kb())
        return
    await safe_edit(
        call,
        "Выберите организацию для выдачи пропуска:",
        kb.org_select_for_action_kb(orgs, "issue")
    )


@dp.callback_query(F.data.startswith("issue_"))
async def cb_issue_select_org(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    await state.update_data(issue_org_id=org_id)
    await state.set_state(IssuePass.waiting_username)
    await safe_edit(
        call,
        "Введите @username гостя, которому выдать пропуск:\n\n"
        "Пример: @ivanov",
        kb.cancel_kb()
    )


@dp.message(IssuePass.waiting_username)
async def issue_username_received(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    if not username:
        await message.answer("Username не может быть пустым. Попробуйте ещё раз:")
        return
    user_row = await db.get_user_by_username(username)
    if not user_row:
        await message.answer(
            f"Пользователь @{username} не найден в базе.\n\n"
            f"Убедитесь, что гость уже запускал бота (/start), "
            f"и его username указан верно.\n\n"
            f"Попробуйте ещё раз или нажмите «Отмена».",
            reply_markup=kb.cancel_kb()
        )
        return
    await state.update_data(
        issue_user_id=user_row["user_id"], issue_username=username
    )
    await state.set_state(IssuePass.waiting_duration)
    await message.answer(
        "Введите срок действия пропуска.\n\n"
        "Форматы:\n"
        "  • 3 — 3 дня\n"
        "  • 5ч — 5 часов\n"
        "  • 30.09.2026 — до 30 сентября 2026, 23:59\n"
        "  • 30.09 — до 30 сентября этого года, 23:59",
        reply_markup=kb.cancel_kb()
    )


@dp.message(IssuePass.waiting_duration)
async def issue_duration_received(message: Message, state: FSMContext):
    valid_until = parse_duration(message.text)
    if not valid_until:
        await message.answer(
            "Не удалось распознать дату. Попробуйте ещё раз.\n\n"
            "Форматы: 3 (дня), 5ч (часов), 30.09.2026 (дата)",
            reply_markup=kb.cancel_kb()
        )
        return
    data = await state.get_data()
    org = await db.get_organization(data["issue_org_id"])
    await state.update_data(valid_until=valid_until)
    await state.set_state(IssuePass.confirming)
    await message.answer(
        f"Подтвердите выдачу пропуска:\n\n"
        f"👤 Гость: @{data['issue_username']}\n"
        f"🏢 Организация: {org['name']}\n"
        f"📍 Адрес: {org['address']}\n"
        f"📅 Действителен до: {fmt_datetime(valid_until)}",
        reply_markup=kb.confirm_issue_kb()
    )


@dp.callback_query(F.data == "confirm_issue", IssuePass.confirming)
async def cb_confirm_issue(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    pass_code, pass_id = await db.create_pass(
        user_id=data["issue_user_id"],
        username=data["issue_username"],
        org_id=data["issue_org_id"],
        issued_by=call.from_user.id,
        valid_until=data["valid_until"]
    )
    org = await db.get_organization(data["issue_org_id"])
    # Уведомляем гостя
    try:
        await bot.send_message(
            data["issue_user_id"],
            f"🎫 Вам выдан электронный пропуск!\n\n"
            f"Номер: {pass_code}\n"
            f"🏢 Организация: {org['name']}\n"
            f"📍 Адрес: {org['address']}\n"
            f"📅 Действителен до: {fmt_datetime(data['valid_until'])}"
        )
    except TelegramBadRequest:
        pass

    await safe_edit(
        call,
        f"✅ Пропуск выдан!\n\n"
        f"Номер: {pass_code}\n"
        f"Гость: @{data['issue_username']}\n"
        f"Действителен до: {fmt_datetime(data['valid_until'])}",
        kb.back_to_main_kb()
    )


@dp.callback_query(F.data == "cancel_issue")
async def cb_cancel_issue(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(call, "Выдача пропуска отменена.", kb.back_to_main_kb())


# ═══════════════════════════════════════════════
#  АННУЛИРОВАНИЕ ПРОПУСКА
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "pass_cancel")
async def cb_pass_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    orgs = await get_user_orgs_with_role(user_id, "admin")
    if not orgs:
        await safe_edit(call, "Нет доступных организаций.", kb.back_to_main_kb())
        return
    await safe_edit(
        call,
        "Выберите организацию:",
        kb.org_select_for_action_kb(orgs, "cancelorg")
    )


@dp.callback_query(F.data.startswith("cancelorg_"))
async def cb_cancel_select_org(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    await state.update_data(cancel_org_id=org_id)
    await state.set_state(CancelPass.waiting_pass_code)
    await safe_edit(call, "Введите номер пропуска для аннулирования:", kb.cancel_kb())


@dp.message(CancelPass.waiting_pass_code)
async def cancel_pass_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    pass_row = await db.get_pass_by_code(code)
    if not pass_row:
        await message.answer("Пропуск с таким номером не найден. Попробуйте ещё раз:", reply_markup=kb.cancel_kb())
        return
    if not pass_row["active"]:
        await message.answer("Этот пропуск уже аннулирован.", reply_markup=kb.back_to_main_kb())
        await state.clear()
        return
    await db.cancel_pass(pass_row["pass_id"], message.from_user.id)
    try:
        await bot.send_message(
            pass_row["user_id"],
            f"❌ Ваш пропуск №{code} был аннулирован."
        )
    except TelegramBadRequest:
        pass
    await state.clear()
    await message.answer(f"✅ Пропуск №{code} аннулирован.", reply_markup=kb.back_to_main_kb())


# ═══════════════════════════════════════════════
#  ПРОДЛЕНИЕ ПРОПУСКА
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "pass_extend")
async def cb_pass_extend(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    orgs = await get_user_orgs_with_role(user_id, "admin")
    if not orgs:
        await safe_edit(call, "Нет доступных организаций.", kb.back_to_main_kb())
        return
    await safe_edit(
        call,
        "Выберите организацию:",
        kb.org_select_for_action_kb(orgs, "extendorg")
    )


@dp.callback_query(F.data.startswith("extendorg_"))
async def cb_extend_select_org(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    await state.update_data(extend_org_id=org_id)
    await state.set_state(ExtendPass.waiting_pass_code)
    await safe_edit(call, "Введите номер пропуска для продления:", kb.cancel_kb())


@dp.message(ExtendPass.waiting_pass_code)
async def extend_pass_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    pass_row = await db.get_pass_by_code(code)
    if not pass_row:
        await message.answer("Пропуск не найден. Попробуйте ещё раз:", reply_markup=kb.cancel_kb())
        return
    await state.update_data(extend_pass_id=pass_row["pass_id"], extend_code=code)
    await state.set_state(ExtendPass.waiting_new_date)
    await message.answer(
        "Введите новый срок действия пропуска.\n\n"
        "Форматы: 3 (дня), 5ч (часов), 30.09.2026 (дата)",
        reply_markup=kb.cancel_kb()
    )


@dp.message(ExtendPass.waiting_new_date)
async def extend_new_date(message: Message, state: FSMContext):
    valid_until = parse_duration(message.text)
    if not valid_until:
        await message.answer("Не удалось распознать дату. Попробуйте ещё раз:", reply_markup=kb.cancel_kb())
        return
    data = await state.get_data()
    await db.extend_pass(data["extend_pass_id"], valid_until)
    pass_row = await db.get_pass_by_code(data["extend_code"])
    if pass_row:
        try:
            await bot.send_message(
                pass_row["user_id"],
                f"📅 Ваш пропуск №{data['extend_code']} продлён "
                f"до {fmt_datetime(valid_until)}"
            )
        except TelegramBadRequest:
            pass
    await state.clear()
    await message.answer(
        f"✅ Пропуск №{data['extend_code']} продлён до {fmt_datetime(valid_until)}",
        reply_markup=kb.back_to_main_kb()
    )


# ═══════════════════════════════════════════════
#  СПИСОК АКТИВНЫХ ПРОПУСКОВ
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "pass_active_list")
async def cb_pass_active_list(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    orgs = await get_user_orgs_with_role(user_id, "admin")
    if not orgs:
        await safe_edit(call, "Нет доступных организаций.", kb.back_to_main_kb())
        return
    await safe_edit(
        call,
        "Выберите организацию:",
        kb.org_select_for_action_kb(orgs, "activelist")
    )


@dp.callback_query(F.data.startswith("activelist_"))
async def cb_activelist(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    org = await db.get_organization(org_id)
    passes = await db.get_org_passes(org_id, active_only=True)
    if not passes:
        await safe_edit(call, "Активных пропусков нет.", kb.back_to_main_kb())
        return
    text = f"📃 Активные пропуска — {org['name']}:\n\n"
    for p in passes:
        text += (
            f"№{p['pass_code']} | @{p['username']} | "
            f"до {fmt_datetime(p['valid_until'])}\n"
        )
    await safe_edit(call, text, kb.back_to_main_kb())


# ═══════════════════════════════════════════════
#  ЖУРНАЛ ВХОДОВ/ВЫХОДОВ
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "guard_logs")
async def cb_guard_logs(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    orgs = await get_user_orgs_with_role(user_id, "admin")
    if not orgs:
        await safe_edit(call, "Нет доступных организаций.", kb.back_to_main_kb())
        return
    await safe_edit(
        call,
        "Выберите организацию для просмотра журнала:",
        kb.org_select_for_action_kb(orgs, "logs")
    )


@dp.callback_query(F.data.startswith("logs_"))
async def cb_logs_show(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    org = await db.get_organization(org_id)
    logs = await db.get_org_logs(org_id)
    if not logs:
        await safe_edit(call, "Журнал пуст.", kb.back_to_main_kb())
        return
    text = f"📖 Журнал — {org['name']}:\n\n"
    for l in logs:
        time = fmt_datetime(l["created_at"])
        if l["action"] == "entered":
            icon = "🟢"
        elif l["action"] == "denied":
            icon = "🔴"
        else:
            icon = "🔵"
        pass_info = f"пропуск {l['pass_code']}" if l["pass_code"] else "—"
        text += (
            f"{icon} {time} | @{l['pass_username'] or '—'} | "
            f"{l['guard_username']} | {pass_info} | {l['action']}\n"
        )
    await safe_edit(call, text, kb.back_to_main_kb())


# ═══════════════════════════════════════════════
#  НАЗНАЧЕНИЕ АДМИНИСТРАТОРА / ОХРАННИКА
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "assign_admin")
async def cb_assign_admin(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    orgs = await get_user_orgs_with_role(user_id, "organizer")
    if not orgs:
        await safe_edit(call, "Вы не организатор ни в одной организации.", kb.back_to_main_kb())
        return
    await safe_edit(
        call,
        "Выберите организацию:",
        kb.org_select_for_action_kb(orgs, "assignadmin")
    )


@dp.callback_query(F.data == "assign_guard")
async def cb_assign_guard(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    orgs = await get_user_orgs_with_role(user_id, "organizer")
    if not orgs:
        await safe_edit(call, "Вы не организатор ни в одной организации.", kb.back_to_main_kb())
        return
    await safe_edit(
        call,
        "Выберите организацию:",
        kb.org_select_for_action_kb(orgs, "assignguard")
    )


@dp.callback_query(F.data.startswith("assignadmin_"))
async def cb_assignadmin_org(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    await state.update_data(assign_org_id=org_id, assign_role="admin")
    await state.set_state(AssignRole.waiting_username)
    await safe_edit(
        call,
        "Введите @username пользователя для назначения администратором:",
        kb.cancel_kb()
    )


@dp.callback_query(F.data.startswith("assignguard_"))
async def cb_assignguard_org(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    await state.update_data(assign_org_id=org_id, assign_role="guard")
    await state.set_state(AssignRole.waiting_username)
    await safe_edit(
        call,
        "Введите @username пользователя для назначения охранником:",
        kb.cancel_kb()
    )


@dp.message(AssignRole.waiting_username)
async def assign_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    user_row = await db.get_user_by_username(username)
    if not user_row:
        await message.answer(
            f"Пользователь @{username} не найден в базе.\n"
            f"Убедитесь, что он запускал бота (/start).",
            reply_markup=kb.cancel_kb()
        )
        return
    data = await state.get_data()
    role_label = "администратором" if data["assign_role"] == "admin" else "охранником"
    await db.assign_role(
        user_row["user_id"], data["assign_org_id"],
        data["assign_role"], message.from_user.id
    )
    await state.clear()
    try:
        org = await db.get_organization(data["assign_org_id"])
        await bot.send_message(
            user_row["user_id"],
            f"✅ Вы назначены {role_label} организации «{org['name']}»!"
        )
    except TelegramBadRequest:
        pass
    await message.answer(
        f"✅ @{username} назначен {role_label}.",
        reply_markup=kb.back_to_main_kb()
    )


# ═══════════════════════════════════════════════
#  РОЛЬ: ГОСТЬ
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "role_guest")
async def cb_guest(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    passes = await db.get_user_passes(user_id, active_only=True)
    if not passes:
        await safe_edit(
            call,
            "У вас нет активных пропусков.\n\n"
            "Обратитесь к организатору или администратору, "
            "чтобы вам выдали пропуск.",
            kb.back_to_main_kb()
        )
        return
    await safe_edit(call, "Ваши активные пропуска:", kb.passes_list_kb(passes))


@dp.callback_query(F.data.startswith("showpass_"))
async def cb_show_pass(call: CallbackQuery, state: FSMContext):
    pass_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    passes = await db.get_user_passes(user_id, active_only=True)
    pass_row = next((p for p in passes if p["pass_id"] == pass_id), None)
    if not pass_row:
        await safe_edit(call, "Пропуск не найден или истёк.", kb.back_to_main_kb())
        return
    text = (
        "🎫 ЭЛЕКТРОННЫЙ ПРОПУСК\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Номер: {pass_row['pass_code']}\n"
        f"🏢 Организация: {pass_row['org_name']}\n"
        f"📍 Адрес: {pass_row['org_address']}\n"
        f"📅 Действителен до: {fmt_datetime(pass_row['valid_until'])}\n"
        f"👤 Гость: @{pass_row['username']}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Выдан: {fmt_datetime(pass_row['issued_at'])}"
    )
    await call.message.answer(text, reply_markup=kb.pass_details_kb())
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass


# ═══════════════════════════════════════════════
#  РОЛЬ: ОХРАННИК
# ═══════════════════════════════════════════════

@dp.callback_query(F.data == "role_guard")
async def cb_guard(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    orgs = await db.get_guard_orgs(user_id)
    if not orgs:
        await safe_edit(
            call,
            "Вы не назначены охранником ни в одной организации.\n\n"
            "Обратитесь к организатору.",
            kb.back_to_main_kb()
        )
        return
    await safe_edit(call, "Выберите организацию:", kb.guard_orgs_kb(orgs))


@dp.callback_query(F.data.startswith("gorg_"))
async def cb_guard_org_select(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    await state.update_data(guard_org_id=org_id)
    org = await db.get_organization(org_id)
    await safe_edit(
        call,
        f"Заступить на охрану:\n\n{org['name']}\n{org['address']}",
        kb.guard_confirm_kb(org_id)
    )


@dp.callback_query(F.data.startswith("gstart_"))
async def cb_guard_start(call: CallbackQuery, state: FSMContext):
    org_id = int(call.data.split("_")[1])
    await state.update_data(guard_org_id=org_id, guard_user_id=call.from_user.id)
    await state.set_state(GuardAuth.waiting_username)
    org = await db.get_organization(org_id)
    await safe_edit(
        call,
        f"🛡️ Консоль охраны — {org['name']}\n\n"
        f"Для авторизации введите ваш @username:",
        kb.cancel_kb()
    )


@dp.message(GuardAuth.waiting_username)
async def guard_auth_username(message: Message, state: FSMContext):
    username = message.text.strip().lstrip("@")
    user = message.from_user
    if user.username and user.username.lower() != username.lower():
        await message.answer(
            "⚠️ Введённый username не совпадает с вашим.\n"
            "Введите ваш реальный @username:",
            reply_markup=kb.cancel_kb()
        )
        return
    data = await state.get_data()
    orgs = await db.get_guard_orgs(user.id)
    org_ids = [o["org_id"] for o in orgs]
    if data.get("guard_org_id") not in org_ids:
        await message.answer(
            "Вы не назначены охранником этой организации.",
            reply_markup=kb.back_to_main_kb()
        )
        await state.clear()
        return
    await state.set_state(GuardConsole.active)
    await message.answer(
        "✅ Авторизация успешна. Добро пожаловать в консоль.\n\n"
        "Введите номер пропуска или нажмите кнопку:",
        reply_markup=kb.guard_console_kb()
    )


@dp.callback_query(F.data == "gcheck", GuardConsole.active)
async def cb_guard_check(call: CallbackQuery, state: FSMContext):
    await state.set_state(GuardAuth.waiting_pass_code)
    await safe_edit(call, "Введите номер пропуска:", kb.cancel_kb())


@dp.message(GuardAuth.waiting_pass_code)
async def guard_check_pass(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    pass_row = await db.get_pass_by_code(code)
    data = await state.get_data()
    org_id = data.get("guard_org_id")
    if not pass_row:
        await db.log_guard_action(None, message.from_user.id, org_id, "denied")
        await message.answer(
            f"❌ Пропуск №{code} не найден.\n"
            f"Проверьте номер и попробуйте снова.",
            reply_markup=kb.guard_console_kb()
        )
        await state.set_state(GuardConsole.active)
        return
    if pass_row["org_id"] != org_id:
        await db.log_guard_action(
            pass_row["pass_id"], message.from_user.id, org_id, "denied"
        )
        await message.answer(
            "❌ Пропуск не относится к этой организации.",
            reply_markup=kb.guard_console_kb()
        )
        await state.set_state(GuardConsole.active)
        return
    if not db.is_pass_active(pass_row):
        await db.log_guard_action(
            pass_row["pass_id"], message.from_user.id, org_id, "denied"
        )
        await message.answer(
            f"❌ Пропуск №{code} НЕ АКТИВЕН.\n\n"
            f"Возможные причины:\n"
            f"  • Пропуск аннулирован\n"
            f"  • Срок действия истёк\n"
            f"  • Это скриншот старого пропуска\n\n"
            f"Возврат в консоль:",
            reply_markup=kb.guard_console_kb()
        )
        await state.set_state(GuardConsole.active)
        return
    await state.update_data(active_pass_id=pass_row["pass_id"], active_pass_code=code)
    org = await db.get_organization(org_id)
    text = (
        f"✅ Пропуск АКТИВЕН\n\n"
        f"Номер: {code}\n"
        f"👤 Гость: @{pass_row['username']}\n"
        f"🏢 Организация: {org['name']}\n"
        f"📅 Действителен до: {fmt_datetime(pass_row['valid_until'])}"
    )
    await message.answer(text, reply_markup=kb.pass_action_kb(pass_row["pass_id"]))


@dp.callback_query(F.data.startswith("let_"))
async def cb_let_pass(call: CallbackQuery, state: FSMContext):
    pass_id = int(call.data.split("_")[1])
    data = await state.get_data()
    org_id = data.get("guard_org_id")
    await db.log_guard_action(pass_id, call.from_user.id, org_id, "entered")
    pass_row = await db.get_pass_by_code(data.get("active_pass_code", ""))
    if pass_row:
        try:
            org = await db.get_organization(org_id)
            await bot.send_message(
                pass_row["user_id"],
                f"🟢 Вы прошли через охрану.\n"
                f"Организация: {org['name']}\n"
                f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
        except TelegramBadRequest:
            pass
    await safe_edit(
        call, "✅ Гость пропущен. Запись добавлена в журнал.",
        kb.guard_console_kb()
    )
    await state.set_state(GuardConsole.active)


@dp.callback_query(F.data.startswith("deny_"))
async def cb_deny_pass(call: CallbackQuery, state: FSMContext):
    pass_id = int(call.data.split("_")[1])
    data = await state.get_data()
    org_id = data.get("guard_org_id")
    await db.log_guard_action(pass_id, call.from_user.id, org_id, "denied")
    await safe_edit(
        call, "🚫 Гость не пропущен. Запись добавлена в журнал.",
        kb.guard_console_kb()
    )
    await state.set_state(GuardConsole.active)


@dp.callback_query(F.data == "gback_console")
async def cb_gback_console(call: CallbackQuery, state: FSMContext):
    await state.set_state(GuardConsole.active)
    await safe_edit(
        call, "Консоль охраны. Введите номер пропуска:",
        kb.guard_console_kb()
    )


# ═══════════════════════════════════════════════
#  ЗАПУСК БОТА
# ═══════════════════════════════════════════════

async def main():
    await db.init_db()
    print("База данных инициализирована.")
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен!")
    await dp.start_polling(
        bot, allowed_updates=dp.resolve_used_update_types()
    )


if __name__ == "__main__":
    asyncio.run(main())
