from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    choosing_language = State()
    awaiting_username = State()
    awaiting_password = State()
    awaiting_nickname_choice = State()
    awaiting_nickname = State()
    awaiting_tt_account_type = State()
    waiting_admin_approval = State()
