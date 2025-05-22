from aiogram.fsm.state import State, StatesGroup

class RegistrationStates(StatesGroup):
    choosing_language = State()
    awaiting_username = State()
    awaiting_password = State()
    waiting_admin_approval = State()