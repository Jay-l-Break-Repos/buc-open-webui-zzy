"""
Integration tests for the avatar settings UI page.

Tests cover:
- GET /api/v1/settings/avatar returns 200 with HTML content
- The page contains all required UI elements (avatar preview, file input,
  upload button, error/success containers, token input)
- The page references the correct API endpoint
- The page accepts only the allowed MIME types
- Static avatar files are served at /api/v1/avatars/<filename>
"""

import io
import os

from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


class TestAvatarSettingsUI(AbstractPostgresTest):

    BASE_PATH = "/api/v1/settings"

    def setup_class(cls):
        super().setup_class()
        from apps.webui.models.users import Users

        cls.users = Users

    def setup_method(self):
        super().setup_method()
        self.users.insert_new_user(
            id="ui-test-user-1",
            name="UI Test User",
            email="uitest@openwebui.com",
            profile_image_url="/user.png",
            role="user",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Page availability
    # ──────────────────────────────────────────────────────────────────────────

    def test_settings_avatar_page_returns_200(self):
        """The settings avatar page must be reachable without authentication."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert response.status_code == 200

    def test_settings_avatar_page_content_type_is_html(self):
        """The response must be an HTML document."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert "text/html" in response.headers.get("content-type", "")

    # ──────────────────────────────────────────────────────────────────────────
    # Required UI elements
    # ──────────────────────────────────────────────────────────────────────────

    def test_page_contains_avatar_preview_img(self):
        """Page must include an <img> element for the avatar preview."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'id="avatar-preview"' in response.text

    def test_page_contains_file_input(self):
        """Page must include a file <input> element."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'type="file"' in response.text
        assert 'id="file-input"' in response.text

    def test_page_contains_upload_button(self):
        """Page must include an upload <button>."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'id="upload-btn"' in response.text

    def test_page_contains_error_message_container(self):
        """Page must include a container for error messages."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'id="error-msg"' in response.text

    def test_page_contains_success_message_container(self):
        """Page must include a container for success messages."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'id="success-msg"' in response.text

    def test_page_contains_token_input(self):
        """Page must include a token input field for authentication."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'id="token-input"' in response.text

    def test_page_contains_drop_zone(self):
        """Page must include a drag-and-drop zone."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'id="drop-zone"' in response.text

    def test_page_contains_progress_indicator(self):
        """Page must include a progress indicator for upload feedback."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'id="progress-bar"' in response.text

    # ──────────────────────────────────────────────────────────────────────────
    # Correct API endpoint reference
    # ──────────────────────────────────────────────────────────────────────────

    def test_page_references_correct_api_endpoint(self):
        """The JS in the page must reference the avatar upload API endpoint."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert "/api/v1/users/user/avatar" in response.text

    # ──────────────────────────────────────────────────────────────────────────
    # Allowed MIME types declared in the file input
    # ──────────────────────────────────────────────────────────────────────────

    def test_file_input_accepts_png(self):
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert "image/png" in response.text

    def test_file_input_accepts_jpeg(self):
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert "image/jpeg" in response.text

    def test_file_input_accepts_webp(self):
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert "image/webp" in response.text

    def test_file_input_accept_attribute_set(self):
        """The <input> accept attribute must list the three allowed types."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert 'accept="image/png,image/jpeg,image/webp"' in response.text

    # ──────────────────────────────────────────────────────────────────────────
    # Client-side validation messages present in the page source
    # ──────────────────────────────────────────────────────────────────────────

    def test_page_mentions_unsupported_format_error(self):
        """Page JS must contain a client-side error for unsupported formats."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert "Unsupported format" in response.text

    def test_page_mentions_file_too_large_error(self):
        """Page JS must contain a client-side error for oversized files."""
        response = self.fast_api_client.get(self.create_url("/avatar"))
        assert "too large" in response.text.lower()

    # ──────────────────────────────────────────────────────────────────────────
    # Avatars static mount
    # ──────────────────────────────────────────────────────────────────────────

    def test_avatar_static_route_serves_uploaded_file(self):
        """
        After a successful upload, the avatar file must be accessible at
        /api/v1/avatars/<filename>.
        """
        from PIL import Image
        from config import AVATAR_DIR

        # Create a tiny PNG and write it directly to AVATAR_DIR
        img = Image.new("RGB", (32, 32), color=(100, 149, 237))
        test_filename = "ui-test-user-1.png"
        test_path = os.path.join(AVATAR_DIR, test_filename)
        img.save(test_path, format="PNG")

        try:
            response = self.fast_api_client.get(f"/api/v1/avatars/{test_filename}")
            assert response.status_code == 200
            assert "image" in response.headers.get("content-type", "")
        finally:
            if os.path.isfile(test_path):
                os.remove(test_path)

    def test_avatar_static_route_404_for_missing_file(self):
        """Requesting a non-existent avatar must return 404."""
        response = self.fast_api_client.get(
            "/api/v1/avatars/nonexistent-avatar-xyz.png"
        )
        assert response.status_code == 404

    # ──────────────────────────────────────────────────────────────────────────
    # End-to-end: upload then verify avatar URL is served
    # ──────────────────────────────────────────────────────────────────────────

    def test_upload_then_serve_avatar(self):
        """
        Full round-trip: upload a PNG via the API, then fetch the returned URL
        from the static mount and verify it returns a valid image.
        """
        from PIL import Image

        img = Image.new("RGB", (64, 64), color=(255, 165, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Upload
        with mock_webui_user(id="ui-test-user-1"):
            upload_resp = self.fast_api_client.post(
                "/api/v1/users/user/avatar",
                files={"file": ("test.png", io.BytesIO(png_bytes), "image/png")},
            )
        assert upload_resp.status_code == 200
        avatar_url = upload_resp.json()["profile_image_url"]
        assert avatar_url.startswith("/avatars/")

        # Serve — the webui app mounts /avatars at /api/v1/avatars
        serve_path = "/api/v1" + avatar_url
        serve_resp = self.fast_api_client.get(serve_path)
        assert serve_resp.status_code == 200
        assert "image" in serve_resp.headers.get("content-type", "")
