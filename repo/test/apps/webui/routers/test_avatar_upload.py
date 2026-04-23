"""
Integration tests for the POST /api/v1/users/user/avatar endpoint.

Covers:
- Successful upload of PNG, JPEG, and WebP images
- Automatic resizing of oversized images (> 256×256)
- Rejection of unsupported MIME types
- Replacement of an existing avatar file on re-upload
"""

import io
import os

import pytest
from PIL import Image

from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


def _create_image_bytes(width: int, height: int, fmt: str) -> bytes:
    """Return raw image bytes for a solid-colour image in the requested format."""
    img = Image.new("RGB", (width, height), color=(100, 149, 237))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf.read()


# MIME type → (Pillow format string, expected file extension)
_FORMAT_MAP = {
    "image/png": ("PNG", "png"),
    "image/jpeg": ("JPEG", "jpg"),
    "image/webp": ("WEBP", "webp"),
}


class TestAvatarUpload(AbstractPostgresTest):

    BASE_PATH = "/api/v1/users"

    def setup_class(cls):
        super().setup_class()
        from apps.webui.models.users import Users

        cls.users = Users

    def setup_method(self):
        super().setup_method()
        self.users.insert_new_user(
            id="user-avatar-1",
            name="Avatar User",
            email="avatar@openwebui.com",
            profile_image_url="/user.png",
            role="user",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _upload_avatar(self, user_id: str, image_bytes: bytes, content_type: str):
        with mock_webui_user(id=user_id):
            return self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={"file": ("avatar", image_bytes, content_type)},
            )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("content_type", list(_FORMAT_MAP.keys()))
    def test_upload_accepted_formats(self, content_type):
        """PNG, JPEG, and WebP images should be accepted and stored."""
        pil_fmt, ext = _FORMAT_MAP[content_type]
        image_bytes = _create_image_bytes(100, 100, pil_fmt)

        response = self._upload_avatar("user-avatar-1", image_bytes, content_type)

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["profile_image_url"] == f"/avatars/user-avatar-1.{ext}"

        # The file must exist on disk
        from config import AVATAR_DIR

        avatar_path = os.path.join(AVATAR_DIR, f"user-avatar-1.{ext}")
        assert os.path.isfile(avatar_path), f"Avatar file not found: {avatar_path}"

        # Verify dimensions are within the 256×256 cap
        with Image.open(avatar_path) as img:
            assert img.width <= 256
            assert img.height <= 256

    def test_upload_resizes_large_image(self):
        """An image larger than 256×256 must be resized to fit within 256×256."""
        image_bytes = _create_image_bytes(512, 512, "PNG")

        response = self._upload_avatar("user-avatar-1", image_bytes, "image/png")

        assert response.status_code == 200, response.text

        from config import AVATAR_DIR

        avatar_path = os.path.join(AVATAR_DIR, "user-avatar-1.png")
        assert os.path.isfile(avatar_path)

        with Image.open(avatar_path) as img:
            assert img.width <= 256
            assert img.height <= 256

    def test_upload_preserves_aspect_ratio_on_resize(self):
        """Resizing must preserve the original aspect ratio (thumbnail behaviour)."""
        # 512 wide × 256 tall → should become 256 × 128 after thumbnail(256, 256)
        image_bytes = _create_image_bytes(512, 256, "PNG")

        response = self._upload_avatar("user-avatar-1", image_bytes, "image/png")

        assert response.status_code == 200, response.text

        from config import AVATAR_DIR

        with Image.open(os.path.join(AVATAR_DIR, "user-avatar-1.png")) as img:
            assert img.width == 256
            assert img.height == 128

    def test_upload_rejects_unsupported_format(self):
        """GIF and other unsupported MIME types must be rejected with HTTP 400."""
        gif_bytes = _create_image_bytes(50, 50, "GIF")

        response = self._upload_avatar("user-avatar-1", gif_bytes, "image/gif")

        assert response.status_code == 400

    def test_upload_replaces_existing_avatar(self):
        """Re-uploading an avatar should delete the old file and store the new one."""
        from config import AVATAR_DIR

        # First upload (PNG)
        png_bytes = _create_image_bytes(100, 100, "PNG")
        r1 = self._upload_avatar("user-avatar-1", png_bytes, "image/png")
        assert r1.status_code == 200

        old_path = os.path.join(AVATAR_DIR, "user-avatar-1.png")
        assert os.path.isfile(old_path)

        # Second upload (JPEG) — the PNG file should be removed
        jpg_bytes = _create_image_bytes(100, 100, "JPEG")
        r2 = self._upload_avatar("user-avatar-1", jpg_bytes, "image/jpeg")
        assert r2.status_code == 200

        assert not os.path.isfile(old_path), "Old PNG avatar was not removed"

        new_path = os.path.join(AVATAR_DIR, "user-avatar-1.jpg")
        assert os.path.isfile(new_path), "New JPEG avatar was not created"

        data = r2.json()
        assert data["profile_image_url"] == "/avatars/user-avatar-1.jpg"

    def test_upload_updates_profile_image_url_in_db(self):
        """After a successful upload the user record must reflect the new URL."""
        png_bytes = _create_image_bytes(64, 64, "PNG")
        response = self._upload_avatar("user-avatar-1", png_bytes, "image/png")

        assert response.status_code == 200

        user = self.users.get_user_by_id("user-avatar-1")
        assert user is not None
        assert user.profile_image_url == "/avatars/user-avatar-1.png"

    def test_upload_small_image_not_resized(self):
        """Images already within 256×256 must not be upscaled."""
        image_bytes = _create_image_bytes(64, 64, "PNG")
        response = self._upload_avatar("user-avatar-1", image_bytes, "image/png")

        assert response.status_code == 200

        from config import AVATAR_DIR

        with Image.open(os.path.join(AVATAR_DIR, "user-avatar-1.png")) as img:
            assert img.width == 64
            assert img.height == 64
