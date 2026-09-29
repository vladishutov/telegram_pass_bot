"""
Inline-клавиатуры для всех экранов бота.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 Организатор", callback_data="role_organizer")],
        [InlineKeyboardButton(text="👨‍💼 Администратор", callback_data="role_admin")],
        [InlineKeyboardButton(text="🛡️ Охранник", callback_data="role_guard")],
        [InlineKeyboardButton(text="🎫 Гость", callback_data="role_guest")],
    ])


def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])


def organizer_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать организацию", callback_data="org_create")],
        [InlineKeyboardButton(text="📋 Мои организации", callback_data="org_list")],
        [InlineKeyboardButton(text="🎫 Выдать пропуск", callback_data="pass_issue")],
        [InlineKeyboardButton(text="❌ Аннулировать пропуск", callback_data="pass_cancel")],
        [InlineKeyboardButton(text="📅 Продлить пропуск", callback_data="pass_extend")],
        [InlineKeyboardButton(text="📃 Активные пропуска", callback_data="pass_active_list")],
        [InlineKeyboardButton(text="📖 Журнал входов/выходов", callback_data="guard_logs")],
        [InlineKeyboardButton(text="👤 Назначить администратора", callback_data="assign_admin")],
        [InlineKeyboardButton(text="🛡️ Назначить охранника", callback_data="assign_guard")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")],
    ])


def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎫 Выдать пропуск", callback_data="pass_issue")],
        [InlineKeyboardButton(text="❌ Аннулировать пропуск", callback_data="pass_cancel")],
        [InlineKeyboardButton(text="📅 Продлить пропуск", callback_data="pass_extend")],
        [InlineKeyboardButton(text="📃 Активные пропуска", callback_data="pass_active_list")],
        [InlineKeyboardButton(text="📖 Журнал входов/выходов", callback_data="guard_logs")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")],
    ])


def orgs_list_kb(orgs):
    rows = []
    for org in orgs:
        rows.append([InlineKeyboardButton(
            text=org["name"], callback_data=f"org_{org['org_id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def guard_orgs_kb(orgs):
    rows = []
    for org in orgs:
        rows.append([InlineKeyboardButton(
            text=org["name"], callback_data=f"gorg_{org['org_id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def guard_confirm_kb(org_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Заступить", callback_data=f"gstart_{org_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="role_guard")],
    ])


def guard_console_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Проверить пропуск", callback_data="gcheck")],
        [InlineKeyboardButton(text="⬅️ Выйти из консоли", callback_data="main_menu")],
    ])


def pass_action_kb(pass_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Пропустить", callback_data=f"let_{pass_id}")],
        [InlineKeyboardButton(text="🚫 Не пропускать", callback_data=f"deny_{pass_id}")],
        [InlineKeyboardButton(text="⬅️ В консоль", callback_data="gback_console")],
    ])


def passes_list_kb(passes):
    rows = []
    for p in passes:
        label = f"№{p['pass_code']} — {p['org_name']}"
        rows.append([InlineKeyboardButton(
            text=label, callback_data=f"showpass_{p['pass_id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pass_details_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К списку пропусков", callback_data="role_guest")]
    ])


def confirm_issue_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_issue")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_issue")],
    ])


def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")],
    ])


def org_select_for_action_kb(orgs, action: str):
    rows = []
    for org in orgs:
        rows.append([InlineKeyboardButton(
            text=org["name"], callback_data=f"{action}_{org['org_id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
