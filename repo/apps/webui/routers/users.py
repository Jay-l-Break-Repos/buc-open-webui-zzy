from fastapi import Response, Request
from fastapi import Depends, FastAPI, HTTPException, status, UploadFile, File
from datetime import datetime, timedelta
from typing import List, Union, Optional

from fastapi import APIRouter
from pydantic import BaseModel
import time
import uuid
import logging
import os

from apps.webui.models.users import (
    UserModel,
    UserUpdateForm,
    UserRoleUpdateForm,
    UserSettings,
    Users,
)
from apps.webui.models.auths import Auths
from apps.webui.models.chats import Chats

from utils.utils import (
    get_verified_user,
    get_password_hash,
    get_current_user,
    get_admin_user,
)
from constants import ERROR_MESSAGES

from config import SRC_LOG_LEVELS, AVATAR_DIR

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()

############################
# GetUsers
############################


@router.get("/", response_model=List[UserModel])
async def get_users(skip: int = 0, limit: int = 50, user=Depends(get_admin_user)):
    return Users.get_users(skip, limit)


############################
# User Permissions
############################


@router.get("/permissions/user")
async def get_user_permissions(request: Request, user=Depends(get_admin_user)):
    return request.app.state.config.USER_PERMISSIONS


@router.post("/permissions/user")
async def update_user_permissions(
    request: Request, form_data: dict, user=Depends(get_admin_user)
):
    request.app.state.config.USER_PERMISSIONS = form_data
    return request.app.state.config.USER_PERMISSIONS


############################
# UpdateUserRole
############################


@router.post("/update/role", response_model=Optional[UserModel])
async def update_user_role(form_data: UserRoleUpdateForm, user=Depends(get_admin_user)):

    if user.id != form_data.id and form_data.id != Users.get_first_user().id:
        return Users.update_user_role_by_id(form_data.id, form_data.role)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=ERROR_MESSAGES.ACTION_PROHIBITED,
    )


############################
# GetUserSettingsBySessionUser
############################


@router.get("/user/settings", response_model=Optional[UserSettings])
async def get_user_settings_by_session_user(user=Depends(get_verified_user)):
    user = Users.get_user_by_id(user.id)
    if user:
        return user.settings
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserSettingsBySessionUser
############################


@router.post("/user/settings/update", response_model=UserSettings)
async def update_user_settings_by_session_user(
    form_data: UserSettings, user=Depends(get_verified_user)
):
    user = Users.update_user_by_id(user.id, {"settings": form_data.model_dump()})
    if user:
        return user.settings
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserInfoBySessionUser
############################


@router.get("/user/info", response_model=Optional[dict])
async def get_user_info_by_session_user(user=Depends(get_verified_user)):
    user = Users.get_user_by_id(user.id)
    if user:
        return user.info
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserInfoBySessionUser
############################


@router.post("/user/info/update", response_model=Optional[dict])
async def update_user_info_by_session_user(
    form_data: dict, user=Depends(get_verified_user)
):
    user = Users.get_user_by_id(user.id)
    if user:
        if user.info is None:
            user.info = {}

        user = Users.update_user_by_id(user.id, {"info": {**user.info, **form_data}})
        if user:
            return user.info
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.USER_NOT_FOUND,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UploadUserAvatar
############################

# Allowed MIME types and their corresponding file extensions
ALLOWED_AVATAR_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

# Maximum output dimensions for resized avatars
AVATAR_MAX_SIZE = (256, 256)


@router.post("/user/avatar", response_model=UserModel)
async def upload_user_avatar(
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
):
    """
    Upload and store a profile avatar for the authenticated user.

    Accepts PNG, JPEG, or WebP images only. The image is resized to fit
    within 256x256 pixels (preserving aspect ratio) before being saved.
    Any previously stored avatar for the user is replaced.
    """
    # ── 1. Validate content type ──────────────────────────────────────────────
    content_type = file.content_type or ""
    if content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.AVATAR_FORMAT_NOT_SUPPORTED,
        )

    try:
        from PIL import Image
        import io

        # ── 2. Read & decode the uploaded image ───────────────────────────────
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))

        # Verify the actual image format matches the declared content type
        pil_format = (image.format or "").upper()
        format_map = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
        if format_map.get(pil_format) != content_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.AVATAR_FORMAT_NOT_SUPPORTED,
            )

        # ── 3. Resize to max 256x256 (thumbnail preserves aspect ratio) ───────
        image.thumbnail(AVATAR_MAX_SIZE, Image.LANCZOS)

        # ── 4. Remove any existing avatar file for this user ──────────────────
        existing_user = Users.get_user_by_id(user.id)
        if existing_user and existing_user.profile_image_url:
            old_url = existing_user.profile_image_url
            # Only remove files we stored ourselves (paths starting with /avatars/)
            if old_url.startswith("/avatars/"):
                old_filename = old_url.split("/avatars/", 1)[-1]
                old_path = os.path.join(AVATAR_DIR, old_filename)
                if os.path.isfile(old_path):
                    try:
                        os.remove(old_path)
                    except OSError as remove_err:
                        log.warning(
                            f"Could not remove old avatar '{old_path}': {remove_err}"
                        )

        # ── 5. Persist the resized image ──────────────────────────────────────
        ext = ALLOWED_AVATAR_TYPES[content_type]
        avatar_filename = f"{user.id}.{ext}"
        avatar_path = os.path.join(AVATAR_DIR, avatar_filename)

        # JPEG requires RGB mode (no alpha channel)
        save_format = pil_format  # PNG / JPEG / WEBP
        if save_format == "JPEG" and image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        image.save(avatar_path, format=save_format)

        # ── 6. Update the user record with the new avatar URL ─────────────────
        avatar_url = f"/avatars/{avatar_filename}"
        updated_user = Users.update_user_profile_image_url_by_id(user.id, avatar_url)

        if updated_user:
            return updated_user

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.AVATAR_UPLOAD_FAILED,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.AVATAR_UPLOAD_FAILED,
        )


############################
# GetUserById
############################


class UserResponse(BaseModel):
    name: str
    profile_image_url: str


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(user_id: str, user=Depends(get_verified_user)):

    # Check if user_id is a shared chat
    # If it is, get the user_id from the chat
    if user_id.startswith("shared-"):
        chat_id = user_id.replace("shared-", "")
        chat = Chats.get_chat_by_id(chat_id)
        if chat:
            user_id = chat.user_id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.USER_NOT_FOUND,
            )

    user = Users.get_user_by_id(user_id)

    if user:
        return UserResponse(name=user.name, profile_image_url=user.profile_image_url)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserById
############################


@router.post("/{user_id}/update", response_model=Optional[UserModel])
async def update_user_by_id(
    user_id: str,
    form_data: UserUpdateForm,
    session_user=Depends(get_admin_user),
):
    user = Users.get_user_by_id(user_id)

    if user:
        if form_data.email.lower() != user.email:
            email_user = Users.get_user_by_email(form_data.email.lower())
            if email_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.EMAIL_TAKEN,
                )

        if form_data.password:
            hashed = get_password_hash(form_data.password)
            log.debug(f"hashed: {hashed}")
            Auths.update_user_password_by_id(user_id, hashed)

        Auths.update_email_by_id(user_id, form_data.email.lower())
        updated_user = Users.update_user_by_id(
            user_id,
            {
                "name": form_data.name,
                "email": form_data.email.lower(),
                "profile_image_url": form_data.profile_image_url,
            },
        )

        if updated_user:
            return updated_user

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(),
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.USER_NOT_FOUND,
    )


############################
# DeleteUserById
############################


@router.delete("/{user_id}", response_model=bool)
async def delete_user_by_id(user_id: str, user=Depends(get_admin_user)):
    if user.id != user_id:
        result = Auths.delete_auth_by_id(user_id)

        if result:
            return True

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_MESSAGES.DELETE_USER_ERROR,
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=ERROR_MESSAGES.ACTION_PROHIBITED,
    )
