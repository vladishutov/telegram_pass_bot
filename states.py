"""
FSM-состояния для машины состояний aiogram.
Каждая группа состояний соответствует сценарию.
"""

from aiogram.fsm.state import StatesGroup, State


class OrgCreate(StatesGroup):
    waiting_name = State()
    waiting_address = State()


class AssignRole(StatesGroup):
    waiting_username = State()


class IssuePass(StatesGroup):
    waiting_username = State()
    waiting_duration = State()
    confirming = State()


class CancelPass(StatesGroup):
    waiting_pass_code = State()


class ExtendPass(StatesGroup):
    waiting_pass_code = State()
    waiting_new_date = State()


class GuardAuth(StatesGroup):
    waiting_username = State()
    waiting_pass_code = State()


class GuardConsole(StatesGroup):
    """Состояние активной консоли охранника."""
    active = State()
