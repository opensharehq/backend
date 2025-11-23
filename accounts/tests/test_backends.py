"""Tests for custom authentication backends."""

from unittest.mock import patch

from django.test import TestCase

from accounts.backends import GiteeOAuth2, HuggingFaceOAuth2


class HuggingFaceOAuth2Tests(TestCase):
    """Tests for HuggingFace OAuth2 backend."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = HuggingFaceOAuth2()

    def test_backend_name(self):
        """Test that backend name is correctly set."""
        self.assertEqual(self.backend.name, "huggingface")

    def test_authorization_url(self):
        """Test that authorization URL is correctly set."""
        self.assertEqual(
            self.backend.AUTHORIZATION_URL,
            "https://huggingface.co/oauth/authorize",
        )

    def test_access_token_url(self):
        """Test that access token URL is correctly set."""
        self.assertEqual(
            self.backend.ACCESS_TOKEN_URL,
            "https://huggingface.co/oauth/token",
        )

    def test_user_data_url(self):
        """Test that user data URL is correctly set."""
        self.assertEqual(
            self.backend.USER_DATA_URL,
            "https://huggingface.co/oauth/userinfo",
        )

    def test_default_scope(self):
        """Test that default scope includes required scopes."""
        expected_scopes = ["openid", "profile", "email"]
        self.assertEqual(self.backend.DEFAULT_SCOPE, expected_scopes)

    def test_id_key(self):
        """Test that ID key is correctly set to 'sub' for OpenID Connect."""
        self.assertEqual(self.backend.ID_KEY, "sub")

    def test_get_user_details_with_full_data(self):
        """Test get_user_details with complete response data."""
        response = {
            "sub": "user123",
            "preferred_username": "testuser",
            "name": "Test User",
            "email": "test@example.com",
            "email_verified": True,
            "picture": "https://example.com/avatar.jpg",
            "website": "https://example.com",
            "profile": "https://huggingface.co/testuser",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "testuser")
        self.assertEqual(details["email"], "test@example.com")
        self.assertEqual(details["first_name"], "Test")
        self.assertEqual(details["last_name"], "User")

    def test_get_user_details_with_single_name(self):
        """Test get_user_details with single-word name."""
        response = {
            "preferred_username": "testuser",
            "name": "John",
            "email": "john@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "testuser")
        self.assertEqual(details["email"], "john@example.com")
        self.assertEqual(details["first_name"], "John")
        self.assertEqual(details["last_name"], "")

    def test_get_user_details_with_multiple_last_names(self):
        """Test get_user_details with multiple last names."""
        response = {
            "preferred_username": "testuser",
            "name": "John Doe Smith",
            "email": "john@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["first_name"], "John")
        self.assertEqual(details["last_name"], "Doe Smith")

    def test_get_user_details_without_name(self):
        """Test get_user_details when name is missing."""
        response = {
            "preferred_username": "testuser",
            "email": "test@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "testuser")
        self.assertEqual(details["email"], "test@example.com")
        self.assertEqual(details["first_name"], "")
        self.assertEqual(details["last_name"], "")

    def test_get_user_details_with_empty_name(self):
        """Test get_user_details when name is empty string."""
        response = {
            "preferred_username": "testuser",
            "name": "",
            "email": "test@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["first_name"], "")
        self.assertEqual(details["last_name"], "")

    def test_get_user_details_without_username(self):
        """Test get_user_details when username is missing."""
        response = {
            "name": "Test User",
            "email": "test@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "")
        self.assertEqual(details["email"], "test@example.com")

    def test_get_user_details_without_email(self):
        """Test get_user_details when email is missing."""
        response = {
            "preferred_username": "testuser",
            "name": "Test User",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "testuser")
        self.assertEqual(details["email"], "")

    def test_get_user_details_with_empty_response(self):
        """Test get_user_details with empty response."""
        response = {}

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "")
        self.assertEqual(details["email"], "")
        self.assertEqual(details["first_name"], "")
        self.assertEqual(details["last_name"], "")

    @patch.object(HuggingFaceOAuth2, "get_json")
    def test_user_data_calls_api_with_token(self, mock_get_json):
        """Test that user_data calls API with correct authorization header."""
        mock_get_json.return_value = {
            "sub": "user123",
            "preferred_username": "testuser",
        }

        access_token = "test_access_token_12345"  # noqa: S105
        result = self.backend.user_data(access_token)

        # Verify get_json was called with correct URL and headers
        mock_get_json.assert_called_once_with(
            "https://huggingface.co/oauth/userinfo",
            headers={"Authorization": "Bearer test_access_token_12345"},
        )

        # Verify result matches mock data
        self.assertEqual(result["sub"], "user123")
        self.assertEqual(result["preferred_username"], "testuser")

    @patch.object(HuggingFaceOAuth2, "get_json")
    def test_user_data_handles_api_response(self, mock_get_json):
        """Test that user_data returns API response data."""
        api_response = {
            "sub": "user456",
            "preferred_username": "anotheruser",
            "email": "another@example.com",
            "name": "Another User",
            "picture": "https://example.com/pic.jpg",
        }
        mock_get_json.return_value = api_response

        result = self.backend.user_data("token")

        self.assertEqual(result, api_response)

    def test_extra_data_fields(self):
        """Test that EXTRA_DATA contains correct field mappings."""
        expected_fields = [
            ("sub", "id"),
            ("preferred_username", "username"),
            ("name", "name"),
            ("email", "email"),
            ("email_verified", "email_verified"),
            ("picture", "picture"),
            ("website", "website"),
            ("profile", "profile"),
        ]

        self.assertEqual(self.backend.EXTRA_DATA, expected_fields)

    def test_access_token_method(self):
        """Test that access token method is POST."""
        self.assertEqual(self.backend.ACCESS_TOKEN_METHOD, "POST")

    def test_redirect_state(self):
        """Test that redirect state is False."""
        self.assertFalse(self.backend.REDIRECT_STATE)

    def test_scope_separator(self):
        """Test that scope separator is a space."""
        self.assertEqual(self.backend.SCOPE_SEPARATOR, " ")


class GiteeOAuth2Tests(TestCase):
    """Tests for Gitee OAuth2 backend."""

    def setUp(self):
        """Set up test fixtures."""
        self.backend = GiteeOAuth2()

    def test_backend_name(self):
        """Test that backend name is correctly set."""
        self.assertEqual(self.backend.name, "gitee")

    def test_authorization_url(self):
        """Test that authorization URL is correctly set."""
        self.assertEqual(
            self.backend.AUTHORIZATION_URL,
            "https://gitee.com/oauth/authorize",
        )

    def test_access_token_url(self):
        """Test that access token URL is correctly set."""
        self.assertEqual(
            self.backend.ACCESS_TOKEN_URL,
            "https://gitee.com/oauth/token",
        )

    def test_user_data_url(self):
        """Test that user data URL is correctly set."""
        self.assertEqual(
            self.backend.USER_DATA_URL,
            "https://gitee.com/api/v5/user",
        )

    def test_default_scope(self):
        """Test that default scope includes required scopes."""
        expected_scopes = ["user_info"]
        self.assertEqual(self.backend.DEFAULT_SCOPE, expected_scopes)

    def test_id_key(self):
        """Test that ID key is correctly set to 'id'."""
        self.assertEqual(self.backend.ID_KEY, "id")

    def test_get_user_details_with_full_data(self):
        """Test get_user_details with complete response data."""
        response = {
            "id": 12345,
            "login": "testuser",
            "name": "Test User",
            "email": "test@example.com",
            "avatar_url": "https://gitee.com/avatar.jpg",
            "html_url": "https://gitee.com/testuser",
            "bio": "Test bio",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "testuser")
        self.assertEqual(details["email"], "test@example.com")
        self.assertEqual(details["first_name"], "Test")
        self.assertEqual(details["last_name"], "User")

    def test_get_user_details_with_single_name(self):
        """Test get_user_details with single-word name."""
        response = {
            "login": "testuser",
            "name": "John",
            "email": "john@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "testuser")
        self.assertEqual(details["email"], "john@example.com")
        self.assertEqual(details["first_name"], "John")
        self.assertEqual(details["last_name"], "")

    def test_get_user_details_with_multiple_last_names(self):
        """Test get_user_details with multiple last names."""
        response = {
            "login": "testuser",
            "name": "John Doe Smith",
            "email": "john@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["first_name"], "John")
        self.assertEqual(details["last_name"], "Doe Smith")

    def test_get_user_details_without_name(self):
        """Test get_user_details when name is missing."""
        response = {
            "login": "testuser",
            "email": "test@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "testuser")
        self.assertEqual(details["email"], "test@example.com")
        self.assertEqual(details["first_name"], "")
        self.assertEqual(details["last_name"], "")

    def test_get_user_details_with_empty_name(self):
        """Test get_user_details when name is empty string."""
        response = {
            "login": "testuser",
            "name": "",
            "email": "test@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["first_name"], "")
        self.assertEqual(details["last_name"], "")

    def test_get_user_details_without_username(self):
        """Test get_user_details when username is missing."""
        response = {
            "name": "Test User",
            "email": "test@example.com",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "")
        self.assertEqual(details["email"], "test@example.com")

    def test_get_user_details_without_email(self):
        """Test get_user_details when email is missing."""
        response = {
            "login": "testuser",
            "name": "Test User",
        }

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "testuser")
        self.assertEqual(details["email"], "")

    def test_get_user_details_with_empty_response(self):
        """Test get_user_details with empty response."""
        response = {}

        details = self.backend.get_user_details(response)

        self.assertEqual(details["username"], "")
        self.assertEqual(details["email"], "")
        self.assertEqual(details["first_name"], "")
        self.assertEqual(details["last_name"], "")

    @patch.object(GiteeOAuth2, "get_json")
    def test_user_data_calls_api_with_token(self, mock_get_json):
        """Test that user_data calls API with correct access token parameter."""
        mock_get_json.return_value = {
            "id": 12345,
            "login": "testuser",
        }

        access_token = "test_access_token_12345"  # noqa: S105
        result = self.backend.user_data(access_token)

        # Verify get_json was called with correct URL and params
        mock_get_json.assert_called_once_with(
            "https://gitee.com/api/v5/user",
            params={"access_token": "test_access_token_12345"},
        )

        # Verify result matches mock data
        self.assertEqual(result["id"], 12345)
        self.assertEqual(result["login"], "testuser")

    @patch.object(GiteeOAuth2, "get_json")
    def test_user_data_handles_api_response(self, mock_get_json):
        """Test that user_data returns API response data."""
        api_response = {
            "id": 67890,
            "login": "anotheruser",
            "email": "another@example.com",
            "name": "Another User",
            "avatar_url": "https://gitee.com/avatar.jpg",
        }
        mock_get_json.return_value = api_response

        result = self.backend.user_data("token")

        self.assertEqual(result, api_response)

    def test_extra_data_fields(self):
        """Test that EXTRA_DATA contains correct field mappings."""
        expected_fields = [
            ("id", "id"),
            ("login", "username"),
            ("name", "name"),
            ("email", "email"),
            ("avatar_url", "avatar_url"),
            ("html_url", "profile_url"),
            ("bio", "bio"),
        ]

        self.assertEqual(self.backend.EXTRA_DATA, expected_fields)

    def test_access_token_method(self):
        """Test that access token method is POST."""
        self.assertEqual(self.backend.ACCESS_TOKEN_METHOD, "POST")

    def test_redirect_state(self):
        """Test that redirect state is False."""
        self.assertFalse(self.backend.REDIRECT_STATE)

    def test_scope_separator(self):
        """Test that scope separator is a space."""
        self.assertEqual(self.backend.SCOPE_SEPARATOR, " ")
