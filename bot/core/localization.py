def get_tg_strings(user_lang_code: str = 'en'):
    # Russian strings
    if user_lang_code == "ru":
        return {
            "start_choose_lang": "Пожалуйста, выберите ваш язык:",
            "lang_set_to": "Язык установлен на Русский.",
            "prompt_username": "Привет! Пожалуйста, введите имя пользователя для регистрации.",
            "already_registered_tg": "Вы уже зарегистрировали одну учетную запись TeamTalk с этого Telegram аккаунта. Разрешена только одна регистрация.",
            "username_taken": "Извините, это имя пользователя уже занято. Пожалуйста, выберите другое имя.",
            "prompt_password": "Теперь введите пароль.",
            "reg_request_sent_to_admin": "Запрос на регистрацию отправлен администраторам. Ожидайте подтверждения.",
            "admin_reg_request_header": "Запрос на регистрацию пользователя:",
            "admin_approve_button": "Да",
            "admin_decline_button": "Нет",
            "admin_approve_question": "Принять регистрацию?",
            "reg_success": "Пользователь {} успешно зарегистрирован.",
            "tt_file_caption": "Ваш .tt файл для быстрого подключения",
            "tt_link_caption": "Или используйте эту TT ссылку:\n",
            "reg_failed_admin_or_later": "Ошибка регистрации. Пожалуйста, попробуйте позже или свяжитесь с администратором.",
            "admin_req_not_found": "Запрос на регистрацию не найден или устарел.",
            "admin_user_already_registered_on_approve": "Этот Telegram аккаунт уже зарегистрировал учетную запись TeamTalk.",
            "user_approved_notification": "Ваша регистрация подтверждена администратором. Вы можете теперь использовать TeamTalk.",
            "user_declined_notification": "Ваша регистрация отклонена администратором.",
            "admin_approved_log": "Регистрация пользователя {} подтверждена.",
            "admin_declined_log": "Регистрация пользователя {} отклонена.",
            "admin_broadcast_user_registered_tt": "Пользователь {} был зарегистрирован."
        }
    # English strings (default)
    else:
        return {
            "start_choose_lang": "Please choose your language:",
            "lang_set_to": "Language set to English.",
            "prompt_username": "Hello! Please enter a username for registration.",
            "already_registered_tg": "You have already registered one TeamTalk account from this Telegram account. Only one registration is allowed.",
            "username_taken": "Sorry, this username is already taken. Please choose another username.",
            "prompt_password": "Now enter a password.",
            "reg_request_sent_to_admin": "Registration request sent to administrators. Please wait for approval.",
            "admin_reg_request_header": "Registration request:",
            "admin_approve_button": "Yes",
            "admin_decline_button": "No",
            "admin_approve_question": "Approve registration?",
            "reg_success": "User {} successfully registered.",
            "tt_file_caption": "Your .tt file for quick connection",
            "tt_link_caption": "Or use this TT link:\n",
            "reg_failed_admin_or_later": "Registration error. Please try again later or contact an administrator.",
            "admin_req_not_found": "Registration request not found or outdated.",
            "admin_user_already_registered_on_approve": "This Telegram account has already registered a TeamTalk account.",
            "user_approved_notification": "Your registration has been approved by the administrator. You can now use TeamTalk.",
            "user_declined_notification": "Your registration has been declined by the administrator.",
            "admin_approved_log": "User {} registration approved.",
            "admin_declined_log": "User {} registration declined.",
            "admin_broadcast_user_registered_tt": "User {} was registered."
        }

def get_flask_strings(lang_code_numeric_str: str): # lang_code_numeric_str is "0" for en, "1" for ru
    if lang_code_numeric_str == "1": # Russian
        return {
            "title": "Регистрация в TeamTalk",
            "header": "Регистрация в TeamTalk",
            "intro_p1": "Если вы хотите зарегистрироваться на сервере",
            "intro_p2": "пожалуйста, заполните форму ниже.",
            "username_label": "Имя пользователя:",
            "password_label": "Пароль:",
            "register_button": "Зарегистрироваться",
            "msg_required_fields": "Имя пользователя и пароль обязательны.",
            "msg_username_taken": "Извините, это имя пользователя уже занято. Пожалуйста, выберите другое имя.",
            "msg_reg_success_prefix": "Пользователь ",
            "msg_reg_success_suffix": " успешно зарегистрирован!",
            "msg_reg_failed": "Ошибка регистрации. Имя пользователя может быть неверным или произошла внутренняя ошибка.",
            "msg_unexpected_error": "Произошла непредвиденная ошибка во время регистрации: ",
            "quick_connect_link_text": "Ссылка для быстрого подключения:",
            "download_tt_file_text": "Скачать .tt файл",
            "module_not_initialized": "Модуль регистрации не полностью инициализирован.",
            "download_time_info": "У вас есть <span id=\"countdown-timer\">10:00</span>, чтобы скачать ваш .tt файл, клиент или использовать ссылку для быстрого подключения.",
            "download_filename_text": "Скачать",
            "msg_ip_already_registered": "С вашего IP-адреса уже была произведена регистрация. Разрешена только одна регистрация на IP-адрес.",
            "download_client_zip_text": "Скачать преднастроенный клиент TeamTalk (ZIP)",
            "creating_zip_info": "Пожалуйста, подождите, генерируется ZIP-архив клиента...",
            "choose_lang_title": "Выберите язык",
            "choose_lang_header": "Добро пожаловать на регистрацию на сервере",
            "choose_lang_english": "English 🇬🇧",
            "choose_lang_russian": "Русский 🇷🇺",
        }
    else: # English (default)
        return {
            "title": "TeamTalk Registration",
            "header": "TeamTalk Registration",
            "intro_p1": "If you want to register on the server",
            "intro_p2": "please fill out the form below.",
            "username_label": "Username:",
            "password_label": "Password:",
            "register_button": "Register",
            "msg_required_fields": "Username and password are required.",
            "msg_username_taken": "Sorry, this username is already taken. Please choose another username.",
            "msg_reg_success_prefix": "User ",
            "msg_reg_success_suffix": " successfully registered!",
            "msg_reg_failed": "Registration failed. The username might be invalid or an internal error occurred.",
            "msg_unexpected_error": "An unexpected error occurred during registration: ",
            "quick_connect_link_text": "Quick Connect Link:",
            "download_tt_file_text": "Download .tt file",
            "module_not_initialized": "Registration module not fully initialized.",
            "download_time_info": "You have <span id=\"countdown-timer\">10:00</span> to download your .tt file, client or use the quick connect link.",
            "download_filename_text": "Download",
            "msg_ip_already_registered": "An account has already been registered from your IP address. Only one registration per IP is allowed.",
            "download_client_zip_text": "Download pre-configured TeamTalk Client (ZIP)",
            "creating_zip_info": "Please wait, generating client ZIP archive...",
            "choose_lang_title": "Choose Language",
            "choose_lang_header": "Welcome to server registration",
            "choose_lang_english": "English 🇬🇧",
            "choose_lang_russian": "Русский 🇷🇺",
        }

# Helper to get admin language based on config for TG bot internal messages
def get_admin_lang_code():
    from .config import ENV_LANG_NUMERIC
    return 'ru' if ENV_LANG_NUMERIC == "1" else 'en'