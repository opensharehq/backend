"""Custom authentication backends for social-auth."""

from social_core.backends.oauth import BaseOAuth2


class GiteeOAuth2(BaseOAuth2):
    """
    Gitee OAuth2 authentication backend.

    Based on Gitee OAuth documentation:
    https://gitee.com/api/v5/oauth_doc
    """

    name = "gitee"
    AUTHORIZATION_URL = "https://gitee.com/oauth/authorize"
    ACCESS_TOKEN_URL = "https://gitee.com/oauth/token"  # noqa: S105
    ACCESS_TOKEN_METHOD = "POST"  # noqa: S105
    REDIRECT_STATE = False
    USER_DATA_URL = "https://gitee.com/api/v5/user"

    # Default scopes for user authentication
    DEFAULT_SCOPE = ["user_info"]
    SCOPE_SEPARATOR = " "

    # User ID key in the API response
    ID_KEY = "id"

    # Extra data to store from the user info response
    EXTRA_DATA = [
        ("id", "id"),
        ("login", "username"),
        ("name", "name"),
        ("email", "email"),
        ("avatar_url", "avatar_url"),
        ("html_url", "profile_url"),
        ("bio", "bio"),
    ]

    def get_user_details(self, response):
        """
        Return user details from Gitee account.

        Args:
            response: Dictionary containing user data from Gitee API

        Returns:
            Dictionary with user details in format expected by social-auth

        """
        name = response.get("name", "")
        return {
            "username": response.get("login", ""),
            "email": response.get("email", ""),
            "first_name": name.split()[0] if name else "",
            "last_name": " ".join(name.split()[1:])
            if name and len(name.split()) > 1
            else "",
        }

    def user_data(self, access_token, *args, **kwargs):
        """
        Load user data from Gitee user endpoint.

        Args:
            access_token: OAuth2 access token
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            Dictionary containing user data from Gitee

        """
        return self.get_json(
            self.USER_DATA_URL,
            params={"access_token": access_token},
        )


class HuggingFaceOAuth2(BaseOAuth2):
    """
    HuggingFace OAuth2 authentication backend.

    Based on HuggingFace OAuth documentation:
    https://huggingface.co/docs/hub/oauth
    """

    name = "huggingface"
    AUTHORIZATION_URL = "https://huggingface.co/oauth/authorize"
    ACCESS_TOKEN_URL = "https://huggingface.co/oauth/token"  # noqa: S105
    ACCESS_TOKEN_METHOD = "POST"  # noqa: S105
    REDIRECT_STATE = False
    USER_DATA_URL = "https://huggingface.co/oauth/userinfo"

    # Default scopes for user authentication
    DEFAULT_SCOPE = ["openid", "profile", "email"]
    SCOPE_SEPARATOR = " "

    # User ID key in the API response
    ID_KEY = "sub"

    # Extra data to store from the user info response
    EXTRA_DATA = [
        ("sub", "id"),
        ("preferred_username", "username"),
        ("name", "name"),
        ("email", "email"),
        ("email_verified", "email_verified"),
        ("picture", "picture"),
        ("website", "website"),
        ("profile", "profile"),
    ]

    def get_user_details(self, response):
        """
        Return user details from HuggingFace account.

        Args:
            response: Dictionary containing user data from HuggingFace API

        Returns:
            Dictionary with user details in format expected by social-auth

        """
        return {
            "username": response.get("preferred_username", ""),
            "email": response.get("email", ""),
            "first_name": response.get("name", "").split()[0]
            if response.get("name")
            else "",
            "last_name": " ".join(response.get("name", "").split()[1:])
            if response.get("name") and len(response.get("name", "").split()) > 1
            else "",
        }

    def user_data(self, access_token, *args, **kwargs):
        """
        Load user data from HuggingFace userinfo endpoint.

        Args:
            access_token: OAuth2 access token
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            Dictionary containing user data from HuggingFace

        """
        return self.get_json(
            self.USER_DATA_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
