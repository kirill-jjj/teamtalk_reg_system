from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    choosing_language = State()
    awaiting_username = State()
    awaiting_password = State()
    awaiting_nickname_choice = State()
    awaiting_nickname = State()
    awaiting_tt_account_type = State()
    waiting_admin_approval = State()


class AdminActions(StatesGroup):
    # This state group is currently empty.
    # It can be used for future admin-related states.
    pass
