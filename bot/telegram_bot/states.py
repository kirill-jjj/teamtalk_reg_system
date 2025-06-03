from aiogram.fsm.state import State, StatesGroup

class RegistrationStates(StatesGroup):
    choosing_language = State()
    awaiting_username = State()
    awaiting_password = State()
    awaiting_nickname_choice = State() # New state
    awaiting_nickname = State()      # New state
    waiting_admin_approval = State()