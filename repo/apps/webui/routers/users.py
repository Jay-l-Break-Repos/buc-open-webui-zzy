from fastapi import Response, Request
from fastapi import Depends, FastAPI, HTTPException, status, UploadFile, File
from datetime import datetime, timedelta
from typing import List, Union, Optional

from fastapi import APIRouter
from pydantic import BaseModel
import io
import time
import uuid
import logging
import os

from PIL import Image

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
# UploadUserAvatarBySessionUser
############################

# Accepted MIME types mapped to (Pillow format name, file extension)
AVATAR_ALLOWED_CONTENT_TYPES = {
    "image/png": ("PNG", "png"),
    "image/jpeg": ("JPEG", "jpg"),
    "image/webp": ("WEBP", "webp"),
}

# Maximum dimension (width or height) for stored avatars
AVATAR_MAX_SIZE = 256


class AvatarUploadResponse(BaseModel):
    url: str
    width: int
    height: int


@router.post("/user/avatar", response_model=AvatarUploadResponse)
async def upload_user_avatar_by_session_user(
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
):
    """
    Upload a profile avatar for the currently authenticated user.

    Accepted formats: PNG, JPEG, WebP.
    Images are automatically resized to fit within 256×256 pixels
    (aspect ratio preserved via thumbnail scaling; small images are not upscaled).
    Any previously stored avatar file for this user is replaced — no orphaned files.
    The user's profile_image_url is updated to point to the new avatar.

    Returns JSON: { "url": "/avatars/<filename>", "width": <int>, "height": <int> }
    """
    # ── 1. Validate content type ──────────────────────────────────────────────
    content_type = file.content_type
    if content_type not in AVATAR_ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.INVALID_IMAGE_FORMAT,
        )

    pil_format, file_ext = AVATAR_ALLOWED_CONTENT_TYPES[content_type]

    try:
        # ── 2. Read and open the image ────────────────────────────────────────
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))

        # Cross-check: Pillow-detected format must match the declared MIME type
        actual_format = (image.format or "").upper()
        if actual_format != pil_format.upper():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.INVALID_IMAGE_FORMAT,
            )

        # ── 3. Resize if necessary (cap at AVATAR_MAX_SIZE × AVATAR_MAX_SIZE) ─
        if image.width > AVATAR_MAX_SIZE or image.height > AVATAR_MAX_SIZE:
            image.thumbnail((AVATAR_MAX_SIZE, AVATAR_MAX_SIZE), Image.LANCZOS)

        final_width, final_height = image.width, image.height

        # ── 4. Remove any existing avatar file for this user ─────────────────
        for ext in ("png", "jpg", "webp"):
            old_path = os.path.join(AVATAR_DIR, f"{user.id}.{ext}")
            if os.path.isfile(old_path):
                try:
                    os.remove(old_path)
                except OSError as e:
                    log.warning(f"Could not remove old avatar {old_path}: {e}")

        # ── 5. Save the new avatar ────────────────────────────────────────────
        avatar_filename = f"{user.id}.{file_ext}"
        avatar_path = os.path.join(AVATAR_DIR, avatar_filename)

        output = io.BytesIO()
        # JPEG does not support transparency; convert if needed
        if pil_format == "JPEG" and image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        image.save(output, format=pil_format)
        output.seek(0)

        with open(avatar_path, "wb") as f:
            f.write(output.read())

        # ── 6. Update the user's profile_image_url in the database ───────────
        profile_image_url = f"/avatars/{avatar_filename}"
        Users.update_user_profile_image_url_by_id(user.id, profile_image_url)

        return AvatarUploadResponse(
            url=profile_image_url,
            width=final_width,
            height=final_height,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
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
