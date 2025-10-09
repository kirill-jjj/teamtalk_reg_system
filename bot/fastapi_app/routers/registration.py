"""FastAPI routes for user registration."""
from datetime import UTC, datetime, timedelta
import logging

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
import pytalk
from pytalk.enums import UserType as PyTalkUserType
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.config import settings
from bot.core.db import (
    add_fastapi_download_token,
    add_fastapi_registered_ip,
    get_fastapi_download_token,
    is_fastapi_ip_registered,
    mark_fastapi_download_token_used,
)
from bot.core.localization import (
    DEFAULT_LANG_CODE,
    get_admin_lang_code,
    get_available_languages_for_display,
    get_translator,
)
from bot.fastapi_app.helpers import (
    create_client_zip_for_user,
    generate_random_token,
    get_generated_files_path,
    get_generated_zips_path,
    get_user_ip_fastapi,
    schedule_temp_file_deletion,
)
from bot.fastapi_app.schemas import (
    Downloadables,
    RegistrationPayload,
)
from bot.teamtalk import users as teamtalk_users_service
from bot.utils.file_generator import generate_tt_file_content, generate_tt_link
from bot.utils.schemas import (
    TeamTalkRegistrationArtefacts,
    TTConnectionInfo,
    TTUserInfo,
    WebSourceInfo,
)

# Import DB dependency and CRUD functions
from ..dependencies import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


async def _execute_tt_registration_for_web(
    username: str,
    password: str,
    nickname: str | None,
    source_info_data: dict,
    pytalk_bot_instance: pytalk.TeamTalkBot,
) -> tuple[bool, TeamTalkRegistrationArtefacts | None]:
    # Return success status and artefact_data
    try:
        broadcast_text_for_tt = None
        if settings.teamtalk_registration_broadcast_enabled:
            # Use admin language for the broadcast message from web context as well
            admin_lang_translator = get_translator(get_admin_lang_code())
            broadcast_text_for_tt = admin_lang_translator(
                "User {} was registered."
            ).format(username)

        reg_success_bool, _msg_key, tt_artefact_data = (
            await teamtalk_users_service.perform_teamtalk_registration(
                pytalk_bot_instance,
                username_str=username,
                password_str=password,
                usertype_to_create=PyTalkUserType.DEFAULT,  # Explicitly default for web
                nickname_str=nickname,
                source_info=source_info_data,
                broadcast_message_text=broadcast_text_for_tt,
                teamtalk_default_user_rights=settings.teamtalk_default_user_rights,
                registration_broadcast_enabled=settings.teamtalk_registration_broadcast_enabled,
                host_name=settings.host_name,
                tcp_port=settings.port,
                udp_port=settings.udp_port,
                encrypted=settings.encrypted,
                server_name=settings.server_name,
                teamtalk_public_hostname=settings.tt_public_hostname,
            )
        )
        if not reg_success_bool:
            logger.error(
                "TeamTalk registration failed for user %s via web, "
                "perform_teamtalk_registration returned False.",
                username,
            )
            return False, None
    except Exception:
        logger.exception(
            "Exception during TeamTalk registration for web user %s:",
            username,
        )
        return False, None
    else:
        logger.info("TeamTalk registration successful for user %s via web.", username)
        return True, tt_artefact_data



async def _prepare_downloadables_for_web(
    request: Request,
    background_tasks: BackgroundTasks,
    artefact_data: TeamTalkRegistrationArtefacts,
    db: AsyncSession,
) -> Downloadables:
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    connection_info = TTConnectionInfo(
        server_name=artefact_data.server_name,
        host=artefact_data.effective_hostname,
        tcpport=artefact_data.tcp_port,
        udpport=artefact_data.udp_port,
        encrypted=artefact_data.encrypted,
    )
    user_info = TTUserInfo(
        username=artefact_data.username,
        password=artefact_data.password,
        nickname=artefact_data.final_nickname,
    )

    tt_content = generate_tt_file_content(connection_info, user_info)
    tt_file_name_for_user = f"{artefact_data.server_name}.tt"
    tt_file_path = get_generated_files_path() / tt_file_name_for_user

    try:
        async with aiofiles.open(tt_file_path, mode="w", encoding="utf-8") as f:
            await f.write(tt_content)
    except OSError:
        logger.exception("Failed to write .tt file %s:", tt_file_path)
        return Downloadables(
            tt_download_link_token=None,
            tt_file_name_for_user=None,
            client_zip_token=None,
            client_zip_filename_for_user=None,
            tt_quick_link=None,
            file_generation_error=True,
        )

    tt_token = generate_random_token()
    expires_at_dt = datetime.now(UTC) + timedelta(
        seconds=settings.generated_file_ttl_seconds
    )
    await add_fastapi_download_token(
        db=db,
        token=tt_token,
        filepath_on_server=tt_file_path.name,  # Store only filename
        original_filename=tt_file_name_for_user,
        token_type="tt_config",  # noqa: S106
        expires_at=expires_at_dt,
    )
    # schedule_temp_file_deletion now needs the token to remove it from DB
    schedule_temp_file_deletion(
        background_tasks,
        request.app,
        tt_file_path.name,
        "files",
        tt_token,  # Pass tt_file_path.name
        delay_seconds=settings.generated_file_ttl_seconds,
    )

    tt_quick_link = generate_tt_link(connection_info, user_info)

    zip_token: str | None = None
    actual_client_zip_filename_for_user: str | None = None
    if settings.teamtalk_client_template_dir:
        (
            zip_file_path_on_server,
            client_zip_user_download_name,
        ) = create_client_zip_for_user(
            app=request.app,
            username=artefact_data.username,
            password=artefact_data.password,
            tt_file_name_on_server=tt_file_name_for_user,
            lang_code=user_lang_code,
        )
        if zip_file_path_on_server and client_zip_user_download_name:
            zip_token = generate_random_token()
            actual_client_zip_filename_for_user = client_zip_user_download_name
            await add_fastapi_download_token(
                db=db,
                token=zip_token,
                filepath_on_server=zip_file_path_on_server.name,  # Store only filename
                original_filename=actual_client_zip_filename_for_user,
                token_type="client_zip",  # noqa: S106
                expires_at=expires_at_dt,
                # Use same expiry for both tokens from one request
            )
            # schedule_temp_file_deletion now needs the token to remove it from DB
            schedule_temp_file_deletion(
                background_tasks,
                request.app,
                zip_file_path_on_server.name,
                "zips",
                zip_token,  # Pass zip_file_path_on_server.name
                delay_seconds=settings.generated_file_ttl_seconds,
            )
        else:
            logger.warning(
                "Failed to create client ZIP for web user %s", artefact_data.username
            )

    return Downloadables(
        tt_download_link_token=tt_token,
        tt_file_name_for_user=tt_file_name_for_user,
        client_zip_token=zip_token,
        client_zip_filename_for_user=actual_client_zip_filename_for_user,
        tt_quick_link=tt_quick_link,
        file_generation_error=False,
    )


@router.post("/set_lang_and_reload")
async def set_language_and_reload(
    request: Request, lang_code: str = Form(...)
) -> RedirectResponse:
    """Sets the user's language preference and reloads the registration page."""
    response = RedirectResponse(
        url=request.url_for("register_page_get"), status_code=302
    )
    response.set_cookie(key="user_web_lang", value=lang_code)
    return response


@router.get("/register")
async def register_page_get(request: Request) -> Response:
    """Displays the registration page."""
    effective_lang_code = DEFAULT_LANG_CODE


    if settings.force_user_lang:
        _ = get_translator(settings.force_user_lang)
        original_string = "Username:"  # Test string for validation
        translated_string = _(original_string)
        if translated_string != original_string:
            effective_lang_code = settings.force_user_lang

            logger.info("Web: Language forced to %s by config.", effective_lang_code)
        else:
            logger.warning(
                "Web: FORCE_USER_LANG set to '%s' but seems invalid/incomplete. "
                "Falling back.",
                settings.force_user_lang,
            )
            # Fallback to cookie or default
            effective_lang_code = request.cookies.get(
                "user_web_lang", DEFAULT_LANG_CODE
            )
    else:
        # No force, use cookie or default
        effective_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)

    available_languages = get_available_languages_for_display()

    context = {
        "title": _("TeamTalk Registration"),
        "message": "",
        "show_form": True,
        "current_lang": effective_lang_code,
        "server_name_from_env": request.app.state.cached_server_name,
        "available_languages": available_languages,
        "registration_complete": False,
        "tt_link": None,
        "download_tt_token": None,
        "actual_tt_filename_for_user": None,
        "download_client_zip_token": None,
        "actual_client_zip_filename_for_user": None,
    }
    return request.app.state.templates.TemplateResponse("register.html", context)


@router.post("/register")
async def register_page_post(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
    username: str = Form(...),
    password: str = Form(...),
    nickname: str | None = Form(None),
) -> Response:
    """Handles the POST request for user registration via the web interface."""
    payload = RegistrationPayload(
        username=username, password=password, nickname=nickname
    )
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    translator = get_translator(user_lang_code)
    user_ip = get_user_ip_fastapi(request)

    pytalk_bot_instance = request.app.state.pytalk_bot_instance
    if await is_fastapi_ip_registered(db, user_ip):
        logger.warning(
            "Validation failed for IP %s (Username: %s): IP already registered.",
            user_ip, payload.username
        )
        raise HTTPException(
            status_code=400,
            detail=translator(
                "This IP address has already been used to register an account."
            ),
        )

    try:
        username_exists = await teamtalk_users_service.check_username_exists(
            pytalk_bot_instance, username=payload.username
        )
        if username_exists is True:
            logger.warning(
                "Validation failed for IP %s (Username: %s): Username already taken.",
                user_ip, payload.username
            )
            raise HTTPException(  # noqa: TRY301
                status_code=400,
                detail=translator(
                    "Sorry, this username is already taken. Please choose another one."
                ),
            )
        if username_exists is None:
            logger.error(
                "Validation failed for IP %s (Username: %s): "
                "check_username_exists returned None (error).",
                user_ip, payload.username,
            )
            raise HTTPException(  # noqa: TRY301
                status_code=500,
                detail=translator(
                    "An error occurred during registration. "
                    "Please try again later or contact an administrator."
                ),
            )
    except Exception:
        logger.exception(
            "Exception during username existence check for %s (IP: %s):",
            payload.username, user_ip,
        )
        raise HTTPException(  # noqa: B904
            status_code=500,
            detail=translator(
                "An error occurred during registration. "
                "Please try again later or contact an administrator."
            ),
        )

    final_nickname = (
        payload.nickname
        if payload.nickname and payload.nickname.strip()
        else payload.username
    )
    source_info_data = WebSourceInfo(
        ip_address=user_ip,
        user_lang=user_lang_code,
        nickname=final_nickname,
    )
    pytalk_bot_instance = request.app.state.pytalk_bot_instance

    (
        registration_successful,
        tt_artefact_data_from_reg,
    ) = await _execute_tt_registration_for_web(
        username=payload.username,
        password=payload.password,
        nickname=final_nickname,
        source_info_data=source_info_data.model_dump(exclude_unset=True),
        pytalk_bot_instance=pytalk_bot_instance,
    )

    if not registration_successful or not tt_artefact_data_from_reg:
        message = translator(
            "An error occurred during TeamTalk registration. "
            "Please try again later or contact an administrator."
        )
        available_languages = get_available_languages_for_display()
        return request.app.state.templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "title": translator("TeamTalk Registration"),
                "message": message,
                "show_form": True,
                "current_lang": user_lang_code,
                "server_name_from_env": request.app.state.cached_server_name,
                "available_languages": available_languages,
            },
            status_code=500,
        )

    try:
        await add_fastapi_registered_ip(
            db, ip_address=user_ip, username=payload.username
        )
    except Exception:
        logger.exception(
            "Failed to add/update registered IP %s for user %s to DB:",
            user_ip, payload.username,
        )

    downloadables_context = await _prepare_downloadables_for_web(
        request,
        background_tasks,
        artefact_data=tt_artefact_data_from_reg,
        db=db,
    )

    if downloadables_context.file_generation_error:
        message = translator(
            "Registration was successful, but there was an error generating "
            "the connection files. Please contact an administrator."
        )
        available_languages = get_available_languages_for_display()
        return request.app.state.templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "title": translator("TeamTalk Registration"),
                "message": message,
                "show_form": True,
                "current_lang": user_lang_code,
                "server_name_from_env": request.app.state.cached_server_name,
                "available_languages": available_languages,
            },
            status_code=500,
        )

    success_title = translator("Registration Successful")
    success_message = translator(
        "Your registration was successful. You can now connect to the server."
    )
    available_languages = get_available_languages_for_display()

    final_context = {
        "request": request,
        "title": success_title,
        "message": success_message,
        "message_class": "success",
        "show_form": False,
        "registration_complete": True,
        "current_lang": user_lang_code,
        "server_name_from_env": request.app.state.cached_server_name,
        "available_languages": available_languages,
        "tt_link": downloadables_context.tt_quick_link,
        "download_tt_token": downloadables_context.tt_download_link_token,
        "actual_tt_filename_for_user": downloadables_context.tt_file_name_for_user,
        "download_client_zip_token": downloadables_context.client_zip_token,
        "actual_client_zip_filename_for_user": (
            downloadables_context.client_zip_filename_for_user
        ),
    }
    return request.app.state.templates.TemplateResponse("register.html", final_context)


@router.get("/download_tt/{token}")
async def download_tt_file(
    request: Request, token: str, db: AsyncSession = Depends(get_db_session),  # noqa: B008  # noqa: B008
) -> FileResponse:
    """Handles the download of a .tt configuration file using a token."""
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    translator = get_translator(user_lang_code)

    token_info_model = await get_fastapi_download_token(db, token)

    if token_info_model and token_info_model.token_type == "tt_config":  # noqa: S105
        server_filename = token_info_model.filepath_on_server
        user_download_filename = token_info_model.original_filename
        file_path = get_generated_files_path() / server_filename

        if file_path.exists():
            await mark_fastapi_download_token_used(db, token)
            return FileResponse(
                path=file_path,
                media_type="application/octet-stream",
                filename=user_download_filename,
            )
    raise HTTPException(
        status_code=404,
        detail=translator(
            "The requested file could not be found or the link has expired."
        ),
    )


@router.get("/download_client_zip/{token}")
async def download_client_zip_file(
    request: Request, token: str, db: AsyncSession = Depends(get_db_session)  # noqa: B008
) -> FileResponse:
    """Handles the download of a pre-configured client ZIP file using a token."""
    user_lang_code = request.cookies.get("user_web_lang", DEFAULT_LANG_CODE)
    translator = get_translator(user_lang_code)

    token_info_model = await get_fastapi_download_token(db, token)

    if token_info_model and token_info_model.token_type == "client_zip":  # noqa: S105
        server_filename = token_info_model.filepath_on_server
        user_download_filename = token_info_model.original_filename
        file_path = get_generated_zips_path() / server_filename

        if file_path.exists():
            await mark_fastapi_download_token_used(db, token)
            return FileResponse(
                path=file_path,
                media_type="application/zip",
                filename=user_download_filename,
            )
    return HTTPException(
        status_code=404,
        detail=translator(
            "The requested file could not be found or the link has expired."
        ),
    )
