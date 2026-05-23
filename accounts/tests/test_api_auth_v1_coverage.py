"""Additional coverage for API v1 authentication edge cases."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.cache.backends.dummy import DummyCache
from django.db import IntegrityError
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from social_django.models import UserSocialAuth

from accounts import api_v1
from accounts.models import RefreshToken
from accounts.services.jwt_tokens import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_user_from_refresh_token,
    revoke_all_refresh_tokens_for_user,
    revoke_refresh_token,
    rotate_refresh_token,
)
from accounts.services.social_exchange_store import (
    RedisSocialExchangeStore,
)
from accounts.services.social_exchange_store import (
    SocialExchangeUnavailableError as StoreUnavailableError,
)
from config.api_common import ApiError


class _MissingCacheMethods:
    """Cache-shaped object without the required persistence methods."""


class _SimpleCacheBackend:
    """Minimal generic cache backend for store branch coverage."""

    def __init__(self):
        """Initialize the in-memory cache slot."""
        self.values = {}
        self.deleted = []

    def set(self, key, value, timeout=None):
        """Store a value."""
        self.values[key] = (value, timeout)

    def get(self, key):
        """Return a stored value."""
        stored = self.values.get(key)
        return stored[0] if stored else None

    def delete(self, key):
        """Delete a value."""
        self.deleted.append(key)
        self.values.pop(key, None)


class _FallbackCacheHandler:
    """Cache handler that forces social_exchange to fall back to default."""

    def __init__(self, default_cache):
        """Store the default cache object returned by __getitem__."""
        self.default_cache = default_cache

    def __getitem__(self, alias):
        """Return default cache unless social_exchange is requested."""
        if alias == "social_exchange":
            raise KeyError(alias)
        if alias == "default":
            return self.default_cache
        raise KeyError(alias)


class _MissingRedisAccess:
    """RedisCache-shaped object whose client access is not callable."""

    _cache = object()

    def make_and_validate_key(self, key):
        """Return the key unchanged."""
        return key


class _ImportFailingRedisCache:
    """RedisCache-shaped object whose client property raises ImportError."""

    def make_and_validate_key(self, key):
        """Return the key unchanged."""
        return key

    @property
    def _cache(self):
        """Raise like a Redis backend without importable client support."""
        raise ImportError("redis missing")


class _RedisClient:
    """Minimal Redis client for store/consume branch coverage."""

    def __init__(self):
        """Initialize the in-memory payload slot."""
        self.value = None
        self.deleted = False

    def set(self, key, value, **kwargs):
        """Store a serialized value."""
        del key, kwargs
        self.value = value
        return True

    def delete(self, key):
        """Record deletion."""
        del key
        self.deleted = True
        self.value = None
        return 1

    def eval(self, script, numkeys, key):
        """Return and clear the current value."""
        del script, numkeys, key
        value = self.value
        self.value = None
        return value or False


class _RedisInnerCache:
    """Minimal Django Redis cache inner client holder."""

    def __init__(self, client):
        """Store the fake client."""
        self.client = client

    def get_client(self, key, *, write=False):
        """Return the fake Redis client."""
        del key, write
        return self.client


class _RedisCacheLike:
    """RedisCache-shaped object used with isinstance patched to True."""

    def __init__(self, client):
        """Initialize fake cache metadata."""
        self._cache = _RedisInnerCache(client)

    def make_and_validate_key(self, key):
        """Return a deterministic Redis key."""
        return f"prefix:{key}"

    def get_backend_timeout(self, timeout):
        """Return the timeout unchanged."""
        return timeout


class ApiAuthV1CoverageTests(TestCase):
    """Exercise auth API branches not covered by the main flow tests."""

    def setUp(self):
        """Create a user fixture."""
        self.User = get_user_model()
        self.password = "CoveragePass123!"  # noqa: S105
        self.user = self.User.objects.create_user(
            username="auth-coverage",
            email="auth-coverage@example.com",
            password=self.password,
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }

    def test_social_helper_functions_cover_extraction_and_provider_errors(self):
        """Social helper functions should cover configured and fallback branches."""
        social_auth = SimpleNamespace(
            extra_data={
                "login": "octocat",
                "html_url": "https://github.com/octocat",
            }
        )
        template_info = {"profile_url_template": "https://example.com/{username}"}
        no_url_auth = SimpleNamespace(extra_data={"preferred_username": "preferred"})

        self.assertEqual(api_v1._extract_social_username(social_auth), "octocat")
        self.assertEqual(
            api_v1._extract_social_profile_url(social_auth, {}),
            "https://github.com/octocat",
        )
        self.assertEqual(
            api_v1._extract_social_profile_url(no_url_auth, template_info),
            "https://example.com/preferred",
        )
        self.assertIsNone(api_v1._extract_social_profile_url(SimpleNamespace(), {}))
        self.assertIsNone(api_v1._extract_social_username(SimpleNamespace()))

        with self.assertRaises(ApiError):
            api_v1._get_provider_or_error("missing-provider")

        with patch.dict(
            "accounts.api_v1.SOCIAL_PROVIDERS",
            {
                "fake": {
                    "name": "Fake",
                    "icon": "fake",
                    "key": "FAKE_SOCIAL_KEY",
                    "secret": "FAKE_SOCIAL_SECRET",
                }
            },
            clear=True,
        ):
            with self.assertRaises(ApiError):
                api_v1._get_provider_or_error("fake")

        with patch(
            "accounts.api_v1.build_social_callback_url",
            side_effect=api_v1.FrontendSocialCallbackNotConfigured(),
        ):
            with self.assertRaises(ApiError):
                api_v1._build_frontend_social_callback_url("github")

    @override_settings(SOCIAL_AUTH_GITHUB_KEY="key", SOCIAL_AUTH_GITHUB_SECRET="secret")
    def test_social_providers_and_connections_cover_configured_states(self):
        """Social provider listing should reflect configured providers."""
        UserSocialAuth.objects.create(
            user=self.user,
            provider="github",
            uid="github-uid",
            extra_data={"username": "auth-coverage"},
        )

        providers_response = self.client.get("/api/v1/auth/social/providers")
        connections_response = self.client.get(
            "/api/v1/auth/social/connections",
            **self.headers,
        )

        self.assertEqual(providers_response.status_code, 200)
        self.assertEqual(
            providers_response.json()["providers"][0]["provider"], "github"
        )
        self.assertEqual(connections_response.status_code, 200)
        connection = connections_response.json()["connections"][0]
        self.assertTrue(connection["is_connected"])
        self.assertEqual(connection["username"], "auth-coverage")

    def test_disconnect_social_account_error_and_success_branches(self):
        """Social disconnection should cover not-found, last-method, and success."""
        not_found = self.client.delete(
            "/api/v1/auth/social/connections/github/999",
            **self.headers,
        )
        self.assertEqual(not_found.status_code, 404)

        passwordless = self.User.objects.create_user(
            username="social-last-method",
            email="social-last@example.com",
            password=None,
        )
        passwordless.set_unusable_password()
        passwordless.save(update_fields=["password"])
        social_auth = UserSocialAuth.objects.create(
            user=passwordless,
            provider="github",
            uid="only",
        )
        passwordless_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(passwordless)}"
        }
        last_method = self.client.delete(
            f"/api/v1/auth/social/connections/github/{social_auth.id}",
            **passwordless_headers,
        )
        self.assertEqual(last_method.status_code, 400)

        removable = UserSocialAuth.objects.create(
            user=self.user,
            provider="github",
            uid="removable",
        )
        success = self.client.delete(
            f"/api/v1/auth/social/connections/github/{removable.id}",
            **self.headers,
        )
        self.assertEqual(success.status_code, 200)
        self.assertFalse(UserSocialAuth.objects.filter(id=removable.id).exists())

    @override_settings(
        FRONTEND_APP_URL="https://frontend.example",
        FRONTEND_SOCIAL_CALLBACK_PATH="/auth/social/callback",
        SOCIAL_AUTH_GITHUB_KEY="key",
        SOCIAL_AUTH_GITHUB_SECRET="secret",
    )
    def test_social_start_and_callback_cover_redirect_branches(self):
        """Social start and callback should cover login, anonymous, and missing provider."""
        factory = RequestFactory()
        access_token = create_access_token(self.user)

        no_token_request = factory.get("/api/v1/auth/social/github/start")
        no_token_response = api_v1.social_start_endpoint(
            no_token_request,
            provider="github",
        )
        no_token_query = parse_qs(urlparse(no_token_response.url).query)
        self.assertEqual(
            no_token_query["next"],
            ["/api/v1/auth/social/github/callback"],
        )

        with patch("accounts.api_v1.django_login") as login_mock:
            request = factory.get(
                f"/api/v1/auth/social/github/start?access_token={access_token}"
            )
            response = api_v1.social_start_endpoint(
                request,
                provider="github",
                access_token=access_token,
            )
        self.assertEqual(response.status_code, 302)
        login_mock.assert_called_once()
        begin_query = parse_qs(urlparse(response.url).query)
        self.assertEqual(
            begin_query["next"],
            ["/api/v1/auth/social/github/callback"],
        )

        inactive = self.User.objects.create_user(
            username="inactive-social-start",
            email="inactive-social-start@example.com",
            password=self.password,
            is_active=False,
        )
        with patch("accounts.api_v1.django_login") as inactive_login_mock:
            inactive_request = factory.get("/api/v1/auth/social/github/start")
            inactive_response = api_v1.social_start_endpoint(
                inactive_request,
                provider="github",
                access_token=create_access_token(inactive),
            )
        self.assertEqual(inactive_response.status_code, 302)
        inactive_login_mock.assert_not_called()

        callback_response = self.client.get("/api/v1/auth/social/github/callback")
        query = parse_qs(urlparse(callback_response.url).query)
        self.assertEqual(query["error"], ["authentication_failed"])

        self.client.force_login(self.user)
        provider_missing = self.client.get("/api/v1/auth/social/github/callback")
        query = parse_qs(urlparse(provider_missing.url).query)
        self.assertEqual(query["error"], ["provider_not_connected"])

    def test_refresh_logout_me_and_change_endpoints_cover_error_branches(self):
        """Auth endpoints should cover invalid token and validation branches."""
        refresh_response = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": "invalid"},
            content_type="application/json",
        )
        logout_response = self.client.post(
            "/api/v1/auth/logout",
            {"refresh_token": "invalid"},
            content_type="application/json",
        )
        me_response = self.client.get("/api/v1/auth/me", **self.headers)

        with patch(
            "accounts.api_v1.ChangeEmailDjangoForm.save",
            create=True,
        ):
            pass

        self.assertEqual(refresh_response.status_code, 401)
        self.assertEqual(logout_response.status_code, 401)
        self.assertEqual(me_response.status_code, 200)

    def test_change_email_integrity_error_branch(self):
        """Email changes should map save-time uniqueness races to validation errors."""
        request = RequestFactory().post("/api/v1/auth/email/change")
        request.auth = self.user
        payload = api_v1.EmailChangeRequestSchema(
            email="race@example.com",
            password=self.password,
        )
        with patch.object(
            type(self.user),
            "save",
            side_effect=IntegrityError("duplicate"),
            autospec=True,
        ):
            with self.assertRaises(ApiError) as cm:
                api_v1.change_email_endpoint(request, payload)

        self.assertEqual(cm.exception.status_code, 422)

    def test_change_email_success_returns_updated_user_payload(self):
        """Email changes should return the authenticated user schema on success."""
        response = self.client.post(
            "/api/v1/auth/email/change",
            {"email": "updated-auth-coverage@example.com", "password": self.password},
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "updated-auth-coverage@example.com")
        self.assertEqual(response.json()["email"], self.user.email)

    @override_settings(
        FRONTEND_APP_URL="https://frontend.example",
        FRONTEND_SOCIAL_CALLBACK_PATH="/auth/social/callback",
        SOCIAL_AUTH_GITHUB_KEY="key",
        SOCIAL_AUTH_GITHUB_SECRET="secret",
    )
    @patch("accounts.api_v1.create_exchange_code", return_value="exchange-code")
    def test_social_callback_success_redirects_with_exchange_code(self, _code_mock):
        """A connected callback should issue a one-time exchange code."""
        self.client.force_login(self.user)
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="github")

        response = self.client.get("/api/v1/auth/social/github/callback")

        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.url).query)
        self.assertEqual(query["exchange_code"], ["exchange-code"])

    def test_social_exchange_rejects_inactive_or_merged_users(self):
        """Exchange payloads for unusable users should be rejected."""
        inactive = self.User.objects.create_user(
            username="exchange-inactive",
            email="exchange-inactive@example.com",
            password=self.password,
            is_active=False,
        )
        target = self.User.objects.create_user(
            username="exchange-target",
            email="exchange-target@example.com",
            password=self.password,
        )
        merged = self.User.objects.create_user(
            username="exchange-merged",
            email="exchange-merged@example.com",
            password=self.password,
            is_active=False,
            merged_into=target,
        )

        for user in (inactive, merged):
            with patch(
                "accounts.api_v1.consume_exchange_code",
                return_value={"user_id": user.id, "provider": "github"},
            ):
                response = self.client.post(
                    "/api/v1/auth/social/exchange",
                    {"exchange_code": "code"},
                    content_type="application/json",
                )
            self.assertEqual(response.status_code, 401)

    @patch("accounts.api_v1.SignUpForm.save", side_effect=IntegrityError("duplicate"))
    def test_register_integrity_error_returns_validation_error(self, _save_mock):
        """Registration should map database uniqueness races to validation errors."""
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "username": "race-user",
                "email": "race@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_register_form_validation_error(self):
        """Registration should return validation errors before saving invalid forms."""
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "username": "",
                "email": "not-an-email",
                "password1": "short",
                "password2": "different",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_password_and_email_validation_errors(self):
        """Password and email endpoints should expose validation branches."""
        weak_password_response = self.client.post(
            "/api/v1/auth/password/change",
            {
                "old_password": "wrong",
                "new_password1": "short",
                "new_password2": "different",
            },
            content_type="application/json",
            **self.headers,
        )
        email_form_response = self.client.post(
            "/api/v1/auth/email/change",
            {"email": self.user.email, "password": "wrong"},
            content_type="application/json",
            **self.headers,
        )
        other = self.User.objects.create_user(
            username="email-race",
            email="email-race@example.com",
            password=self.password,
        )
        with patch(
            "accounts.api_v1.ChangeEmailDjangoForm.cleaned_data",
            {"email": other.email},
            create=True,
        ):
            pass

        self.assertEqual(weak_password_response.status_code, 422)
        self.assertEqual(email_form_response.status_code, 422)

    def test_password_reset_validation_and_invalid_token_branches(self):
        """Password reset endpoints should cover invalid form and invalid token branches."""
        invalid_request = self.client.post(
            "/api/v1/auth/password/reset/request",
            {"email": "not-an-email"},
            content_type="application/json",
        )
        invalid_uid = self.client.post(
            "/api/v1/auth/password/reset/confirm",
            {
                "uidb64": "bad",
                "token": "bad",
                "new_password1": "StrongPass123!",
                "new_password2": "StrongPass123!",
            },
            content_type="application/json",
        )
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        invalid_password = self.client.post(
            "/api/v1/auth/password/reset/confirm",
            {
                "uidb64": uidb64,
                "token": token,
                "new_password1": "short",
                "new_password2": "different",
            },
            content_type="application/json",
        )

        self.assertEqual(invalid_request.status_code, 422)
        self.assertEqual(invalid_uid.status_code, 400)
        self.assertEqual(invalid_password.status_code, 422)

    def test_password_reset_passwordless_social_user_with_provider(self):
        """Passwordless social accounts should return the generic reset response."""
        passwordless = self.User.objects.create_user(
            username="passwordless-social",
            email="passwordless-social@example.com",
            password=None,
        )
        passwordless.set_unusable_password()
        passwordless.save(update_fields=["password"])
        UserSocialAuth.objects.create(
            user=passwordless,
            provider="github",
            uid="passwordless-social-uid",
        )

        response = self.client.post(
            "/api/v1/auth/password/reset/request",
            {"email": passwordless.email},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "If the email is registered, a reset link will be sent.",
        )

    def test_password_reset_passwordless_user_without_provider(self):
        """Passwordless users without social providers still get a generic response."""
        passwordless = self.User.objects.create_user(
            username="passwordless-no-provider",
            email="passwordless-no-provider@example.com",
            password=None,
        )
        passwordless.set_unusable_password()
        passwordless.save(update_fields=["password"])

        response = self.client.post(
            "/api/v1/auth/password/reset/request",
            {"email": passwordless.email},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "If the email is registered, a reset link will be sent.",
        )

    def test_jwt_refresh_helpers_cover_invalid_payloads_and_revocation(self):
        """JWT helper functions should cover malformed and inactive refresh records."""
        self.assertIsNone(decode_refresh_token("not-a-token"))
        self.assertIsNone(get_user_from_refresh_token("not-a-token"))
        self.assertFalse(revoke_refresh_token("not-a-token"))
        self.assertIsNone(rotate_refresh_token("not-a-token"))

        refresh_token = create_refresh_token(self.user)
        self.assertEqual(get_user_from_refresh_token(refresh_token), self.user)
        payload = decode_refresh_token(refresh_token)
        self.assertIsNotNone(payload)
        record = RefreshToken.objects.get(jti=payload["jti"])

        wrong_subject = jwt.encode(
            {
                **payload,
                "sub": str(self.user.id + 1000),
                "type": REFRESH_TOKEN_TYPE,
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        self.assertIsNone(get_user_from_refresh_token(wrong_subject))

        record.expires_at = timezone.now() - timedelta(seconds=1)
        record.save(update_fields=["expires_at"])
        self.assertIsNone(get_user_from_refresh_token(refresh_token))
        self.assertFalse(revoke_refresh_token(refresh_token))
        self.assertIsNone(rotate_refresh_token(refresh_token))

        first = create_refresh_token(self.user)
        self.assertGreaterEqual(revoke_all_refresh_tokens_for_user(self.user), 1)
        self.assertFalse(revoke_refresh_token(first))

    def test_social_exchange_store_error_paths(self):
        """Store adapter should raise stable errors for unsupported backends."""
        with self.assertRaises(StoreUnavailableError):
            RedisSocialExchangeStore(DummyCache("dummy", {})).store(
                "key",
                {"provider": "github", "user_id": self.user.id},
                60,
            )

        with self.assertRaises(StoreUnavailableError):
            RedisSocialExchangeStore(_MissingCacheMethods()).store(
                "key",
                {"provider": "github", "user_id": self.user.id},
                60,
            )

        redis_store = RedisSocialExchangeStore.__new__(RedisSocialExchangeStore)
        with self.assertRaises(StoreUnavailableError):
            redis_store._redis_client(
                _ImportFailingRedisCache(),
                "key",
                write=True,
                required_methods=("set",),
            )
        with self.assertRaises(StoreUnavailableError):
            redis_store._redis_client(
                _MissingRedisAccess(),
                "key",
                write=True,
                required_methods=("set",),
            )

        store = RedisSocialExchangeStore(Mock())
        for payload in (b"not-json", b"[]", b'{"provider":"github"}'):
            with self.assertRaises(StoreUnavailableError):
                store._deserialize(payload)

    def test_social_exchange_store_default_cache_and_generic_timeout_zero_paths(self):
        """Default cache selection and generic timeout=0 should use fallback branches."""
        default_cache = _SimpleCacheBackend()

        with patch(
            "accounts.services.social_exchange_store.caches",
            _FallbackCacheHandler(default_cache),
        ):
            store = RedisSocialExchangeStore()

        self.assertIs(store.cache_backend, default_cache)

        store.store("delete-me", {"provider": "github", "user_id": self.user.id}, 0)
        self.assertEqual(default_cache.deleted, ["delete-me"])
        self.assertEqual(default_cache.values, {})

        store.store("consume-me", {"provider": "github", "user_id": self.user.id}, 60)
        self.assertEqual(
            store.consume("consume-me"),
            {"provider": "github", "user_id": self.user.id},
        )
        self.assertIn("consume-me", default_cache.deleted)
        self.assertIsNone(store.consume("consume-me"))

    def test_social_exchange_store_redis_store_and_consume_paths(self):
        """Redis-backed store paths should store, delete, and atomically consume."""
        client = _RedisClient()
        cache_backend = _RedisCacheLike(client)
        store = RedisSocialExchangeStore(cache_backend)

        with patch(
            "accounts.services.social_exchange_store.RedisCache", _RedisCacheLike
        ):
            store.store("key", {"provider": "github", "user_id": self.user.id}, 60)
            consumed = store.consume("key")
            store.store("delete-me", {"provider": "github", "user_id": self.user.id}, 0)

        self.assertEqual(consumed, {"provider": "github", "user_id": self.user.id})
        self.assertTrue(client.deleted)
