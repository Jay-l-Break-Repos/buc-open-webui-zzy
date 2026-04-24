"""
Integration tests for the POST /api/v1/users/user/avatar endpoint.

Tests cover:
- Successful upload of PNG, JPEG, and WebP images
- Rejection of unsupported file formats (GIF, PDF, plain text)
- Resizing of images larger than 256x256
- Replacement of an existing avatar when a new one is uploaded
- Unauthenticated requests are rejected (401)
"""

import io
import os

import pytest

from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


def _make_png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Return raw bytes of a minimal PNG image of the given dimensions."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    """Return raw bytes of a minimal JPEG image of the given dimensions."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_webp_bytes(width: int = 100, height: int = 100) -> bytes:
    """Return raw bytes of a minimal WebP image of the given dimensions."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=(0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


def _make_gif_bytes() -> bytes:
    """Return raw bytes of a minimal GIF image (unsupported format)."""
    from PIL import Image

    img = Image.new("RGB", (10, 10), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


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

    # ──────────────────────────────────────────────────────────────────────────
    # Happy-path: supported formats
    # ──────────────────────────────────────────────────────────────────────────

    def test_upload_png_avatar(self):
        png_bytes = _make_png_bytes()
        with mock_webui_user(id="user-avatar-1"):
            response = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={"file": ("avatar.png", io.BytesIO(png_bytes), "image/png")},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["profile_image_url"].startswith("/avatars/")
        assert data["profile_image_url"].endswith(".png")

    def test_upload_jpeg_avatar(self):
        jpeg_bytes = _make_jpeg_bytes()
        with mock_webui_user(id="user-avatar-1"):
            response = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={"file": ("avatar.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["profile_image_url"].startswith("/avatars/")
        assert data["profile_image_url"].endswith(".jpg")

    def test_upload_webp_avatar(self):
        webp_bytes = _make_webp_bytes()
        with mock_webui_user(id="user-avatar-1"):
            response = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={"file": ("avatar.webp", io.BytesIO(webp_bytes), "image/webp")},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["profile_image_url"].startswith("/avatars/")
        assert data["profile_image_url"].endswith(".webp")

    # ──────────────────────────────────────────────────────────────────────────
    # Validation: unsupported formats are rejected
    # ──────────────────────────────────────────────────────────────────────────

    def test_upload_gif_rejected(self):
        gif_bytes = _make_gif_bytes()
        with mock_webui_user(id="user-avatar-1"):
            response = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={"file": ("avatar.gif", io.BytesIO(gif_bytes), "image/gif")},
            )
        assert response.status_code == 400
        assert "Unsupported image format" in response.json()["detail"]

    def test_upload_pdf_rejected(self):
        fake_pdf = b"%PDF-1.4 fake content"
        with mock_webui_user(id="user-avatar-1"):
            response = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={
                    "file": ("document.pdf", io.BytesIO(fake_pdf), "application/pdf")
                },
            )
        assert response.status_code == 400
        assert "Unsupported image format" in response.json()["detail"]

    def test_upload_plain_text_rejected(self):
        text_content = b"hello world"
        with mock_webui_user(id="user-avatar-1"):
            response = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={
                    "file": ("note.txt", io.BytesIO(text_content), "text/plain")
                },
            )
        assert response.status_code == 400
        assert "Unsupported image format" in response.json()["detail"]

    # ──────────────────────────────────────────────────────────────────────────
    # Resizing: images larger than 256x256 are downscaled
    # ──────────────────────────────────────────────────────────────────────────

    def test_large_image_is_resized(self):
        """A 512x512 PNG must be stored as a 256x256 image."""
        from PIL import Image
        from config import AVATAR_DIR

        large_png = _make_png_bytes(width=512, height=512)
        with mock_webui_user(id="user-avatar-1"):
            response = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={
                    "file": ("big.png", io.BytesIO(large_png), "image/png")
                },
            )
        assert response.status_code == 200
        avatar_url = response.json()["profile_image_url"]
        avatar_filename = avatar_url.split("/avatars/", 1)[-1]
        saved_path = os.path.join(AVATAR_DIR, avatar_filename)

        assert os.path.isfile(saved_path), "Avatar file was not saved to disk"
        saved_image = Image.open(saved_path)
        assert saved_image.width <= 256
        assert saved_image.height <= 256

    def test_small_image_is_not_upscaled(self):
        """A 64x64 PNG must remain 64x64 (thumbnail never upscales)."""
        from PIL import Image
        from config import AVATAR_DIR

        small_png = _make_png_bytes(width=64, height=64)
        with mock_webui_user(id="user-avatar-1"):
            response = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={
                    "file": ("small.png", io.BytesIO(small_png), "image/png")
                },
            )
        assert response.status_code == 200
        avatar_url = response.json()["profile_image_url"]
        avatar_filename = avatar_url.split("/avatars/", 1)[-1]
        saved_path = os.path.join(AVATAR_DIR, avatar_filename)

        saved_image = Image.open(saved_path)
        assert saved_image.width == 64
        assert saved_image.height == 64

    # ──────────────────────────────────────────────────────────────────────────
    # Replacement: uploading a second avatar removes the first
    # ──────────────────────────────────────────────────────────────────────────

    def test_avatar_replacement(self):
        """Uploading a second avatar replaces the first one on disk."""
        from config import AVATAR_DIR

        # First upload
        png1 = _make_png_bytes()
        with mock_webui_user(id="user-avatar-1"):
            r1 = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={"file": ("first.png", io.BytesIO(png1), "image/png")},
            )
        assert r1.status_code == 200
        first_url = r1.json()["profile_image_url"]
        first_filename = first_url.split("/avatars/", 1)[-1]
        first_path = os.path.join(AVATAR_DIR, first_filename)
        assert os.path.isfile(first_path), "First avatar should exist on disk"

        # Second upload (different format to produce a different filename)
        jpeg1 = _make_jpeg_bytes()
        with mock_webui_user(id="user-avatar-1"):
            r2 = self.fast_api_client.post(
                self.create_url("/user/avatar"),
                files={"file": ("second.jpg", io.BytesIO(jpeg1), "image/jpeg")},
            )
        assert r2.status_code == 200
        second_url = r2.json()["profile_image_url"]
        assert second_url != first_url or first_url.endswith(".jpg")

        # The old file should have been removed
        assert not os.path.isfile(first_path), (
            "Old avatar file should have been deleted after replacement"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Auth: unauthenticated requests are rejected
    # ──────────────────────────────────────────────────────────────────────────

    def test_unauthenticated_upload_rejected(self):
        """Requests without a valid session must receive a 401/403 response."""
        png_bytes = _make_png_bytes()
        # No mock_webui_user context → dependency_overrides is empty → real auth
        response = self.fast_api_client.post(
            self.create_url("/user/avatar"),
            files={"file": ("avatar.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert response.status_code in (401, 403)
