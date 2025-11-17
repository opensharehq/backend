"""Django settings for fullsite project."""

import os
import sys
from pathlib import Path

import environ

from .settings_helpers import build_cache_settings, determine_email_backend

BASE_DIR = Path(__file__).resolve().parent.parent
environ.Env.read_env(BASE_DIR / ".env")  # 这个路径是项目的根目录


env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(
        str,
        "PLACEHOLDER_SECRET_KEY_CHANGE_ME!",
    ),
    DATABASE_URL=(str, "sqlite:///db.sqlite3"),
    ALLOWED_HOSTS=(list, []),
    TIME_ZONE=(str, "Asia/Shanghai"),
    LANGUAGE_CODE=(str, "zh-hans"),
    USE_I18N=(bool, True),
    USE_TZ=(bool, True),
    DEFAULT_AUTO_FIELD=(str, "django.db.models.BigAutoField"),
    AWS_S3_ACCESS_KEY_ID=(str, ""),
    AWS_S3_SECRET_ACCESS_KEY=(str, ""),
    AWS_STORAGE_BUCKET_NAME=(str, ""),
    AWS_LOCATION=(str, ""),
    AWS_S3_REGION_NAME=(str, ""),
    AWS_S3_CUSTOM_DOMAIN=(str, ""),
    AWS_S3_ENDPOINT_URL=(str, ""),
    SOCIAL_AUTH_GITHUB_KEY=(str, ""),
    SOCIAL_AUTH_GITHUB_SECRET=(str, ""),
    SOCIAL_AUTH_GITHUB_SCOPE=(list, []),
    SOCIAL_AUTH_GOOGLE_OAUTH2_KEY=(str, ""),
    SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET=(str, ""),
    SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE=(list, ["openid", "email", "profile"]),
    SOCIAL_AUTH_BITBUCKET_OAUTH2_KEY=(str, ""),
    SOCIAL_AUTH_BITBUCKET_OAUTH2_SECRET=(str, ""),
    SOCIAL_AUTH_BITBUCKET_OAUTH2_SCOPE=(list, []),
    SOCIAL_AUTH_DOCKER_KEY=(str, ""),
    SOCIAL_AUTH_DOCKER_SECRET=(str, ""),
    SOCIAL_AUTH_DOCKER_SCOPE=(list, []),
    SOCIAL_AUTH_FACEBOOK_KEY=(str, ""),
    SOCIAL_AUTH_FACEBOOK_SECRET=(str, ""),
    SOCIAL_AUTH_FACEBOOK_SCOPE=(list, []),
    SOCIAL_AUTH_GITLAB_KEY=(str, ""),
    SOCIAL_AUTH_GITLAB_SECRET=(str, ""),
    SOCIAL_AUTH_GITLAB_SCOPE=(list, ["read_user"]),
    SOCIAL_AUTH_GITEA_KEY=(str, ""),
    SOCIAL_AUTH_GITEA_SECRET=(str, ""),
    SOCIAL_AUTH_GITEA_SCOPE=(list, []),
    SOCIAL_AUTH_GITEA_API_URL=(str, ""),
    SOCIAL_AUTH_GITEE_KEY=(str, ""),
    SOCIAL_AUTH_GITEE_SECRET=(str, ""),
    SOCIAL_AUTH_GITEE_SCOPE=(list, ["user_info"]),
    SOCIAL_AUTH_LINKEDIN_OAUTH2_KEY=(str, ""),
    SOCIAL_AUTH_LINKEDIN_OAUTH2_SECRET=(str, ""),
    SOCIAL_AUTH_LINKEDIN_OAUTH2_SCOPE=(list, ["r_liteprofile"]),
    SOCIAL_AUTH_TWITTER_OAUTH2_KEY=(str, ""),
    SOCIAL_AUTH_TWITTER_OAUTH2_SECRET=(str, ""),
    SOCIAL_AUTH_HUGGINGFACE_KEY=(str, ""),
    SOCIAL_AUTH_HUGGINGFACE_SECRET=(str, ""),
    SOCIAL_AUTH_HUGGINGFACE_SCOPE=(list, ["openid", "profile"]),
    MAILGUN_API_KEY=(str, "PLACEHOLDER_MAILGUN_API_KEY"),
    MAILGUN_SENDER_DOMAIN=(str, "PLACEHOLDER_MAILGUN_SENDER_DOMAIN"),
    REDIS_URL=(str, ""),
    CLICKHOUSE_HOST=(str, "localhost"),
    CLICKHOUSE_PORT=(int, 8123),
    CLICKHOUSE_USER=(str, "default"),
    CLICKHOUSE_PASSWORD=(str, ""),
    CLICKHOUSE_DATABASE=(str, "default"),
    CLICKHOUSE_SECURE=(bool, False),
)

TESTING = "test" in sys.argv or "PYTEST_VERSION" in os.environ

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
LANGUAGE_CODE = env("LANGUAGE_CODE")
TIME_ZONE = env("TIME_ZONE")
USE_I18N = env("USE_I18N")
USE_TZ = env("USE_TZ")
AWS_S3_ACCESS_KEY_ID = env("AWS_S3_ACCESS_KEY_ID")
AWS_S3_SECRET_ACCESS_KEY = env("AWS_S3_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
AWS_LOCATION = env("AWS_LOCATION")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME")
AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL")
AWS_S3_ADDRESSING_STYLE = "virtual"
AWS_S3_SIGNATURE_VERSION = "s3"
REDIS_URL = env("REDIS_URL")

# ClickHouse Configuration
CLICKHOUSE_HOST = env("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = env("CLICKHOUSE_PORT")
CLICKHOUSE_USER = env("CLICKHOUSE_USER")
CLICKHOUSE_PASSWORD = env("CLICKHOUSE_PASSWORD")
CLICKHOUSE_DATABASE = env("CLICKHOUSE_DATABASE")
CLICKHOUSE_SECURE = env("CLICKHOUSE_SECURE")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.flatpages",
    "django.contrib.redirects",
    "django.contrib.admindocs",
    # third party app
    "django_extensions",
    "django_tasks",
    "django_tasks.backends.database",
    "social_django",
    "anymail",
    "turnstile",
    # app
    "homepage",
    "accounts",
    "points",
    "shop",
    "chdb",
    "messages.apps.SiteMessagesConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "common.middleware.CanonicalHostRedirectMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.cache.UpdateCacheMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.http.ConditionalGetMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.cache.FetchFromCacheMiddleware",
    "django.contrib.flatpages.middleware.FlatpageFallbackMiddleware",
    "django.contrib.redirects.middleware.RedirectFallbackMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

CSRF_TRUSTED_ORIGINS = [
    "https://open-share.cn",
    "https://www.open-share.cn",
]

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    ),
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

CACHES = build_cache_settings(DEBUG and not TESTING, REDIS_URL, TESTING)
CACHE_MIDDLEWARE_KEY_PREFIX = "middleware_cache_"
CACHE_MIDDLEWARE_SECONDS = 300

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SOCIAL_AUTH_JSONFIELD_ENABLED = True

AUTHENTICATION_BACKENDS = (
    "social_core.backends.github.GithubOAuth2",
    "social_core.backends.google.GoogleOAuth2",
    "social_core.backends.bitbucket.BitbucketOAuth2",
    "social_core.backends.docker.DockerOAuth2",
    "social_core.backends.facebook.FacebookOAuth2",
    "social_core.backends.gitlab.GitLabOAuth2",
    "social_core.backends.gitea.GiteaOAuth2",
    "accounts.backends.GiteeOAuth2",
    "social_core.backends.linkedin.LinkedinOAuth2",
    "social_core.backends.twitter.TwitterOAuth",
    "accounts.backends.HuggingFaceOAuth2",
    "social_core.backends.email.EmailAuth",
    "social_core.backends.username.UsernameAuth",
    "django.contrib.auth.backends.ModelBackend",
)

# custom user
AUTH_USER_MODEL = "accounts.User"
SOCIAL_AUTH_USER_MODEL = "accounts.User"

SOCIAL_AUTH_URL_NAMESPACE = "social"
SOCIAL_AUTH_ADMIN_USER_SEARCH_FIELDS = ["username", "first_name", "email"]
SOCIAL_AUTH_REDIRECT_IS_HTTPS = True


# email backend
SOCIAL_AUTH_EMAIL_FORM_URL = "/accounts/login"
SOCIAL_AUTH_EMAIL_FORM_HTML = "sign_in.html"
# username auth
SOCIAL_AUTH_USERNAME_FORM_URL = "/accounts/login"
SOCIAL_AUTH_USERNAME_FORM_HTML = "sign_in.html"

# Social Auth Backends Configuration
SOCIAL_AUTH_GITHUB_KEY = env("SOCIAL_AUTH_GITHUB_KEY")
SOCIAL_AUTH_GITHUB_SECRET = env("SOCIAL_AUTH_GITHUB_SECRET")
SOCIAL_AUTH_GITHUB_SCOPE = env("SOCIAL_AUTH_GITHUB_SCOPE")

SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = env("SOCIAL_AUTH_GOOGLE_OAUTH2_KEY")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = env("SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET")
SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE = env("SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE")

SOCIAL_AUTH_BITBUCKET_OAUTH2_KEY = env("SOCIAL_AUTH_BITBUCKET_OAUTH2_KEY")
SOCIAL_AUTH_BITBUCKET_OAUTH2_SECRET = env("SOCIAL_AUTH_BITBUCKET_OAUTH2_SECRET")
SOCIAL_AUTH_BITBUCKET_OAUTH2_SCOPE = env("SOCIAL_AUTH_BITBUCKET_OAUTH2_SCOPE")

SOCIAL_AUTH_DOCKER_KEY = env("SOCIAL_AUTH_DOCKER_KEY")
SOCIAL_AUTH_DOCKER_SECRET = env("SOCIAL_AUTH_DOCKER_SECRET")
SOCIAL_AUTH_DOCKER_SCOPE = env("SOCIAL_AUTH_DOCKER_SCOPE")

SOCIAL_AUTH_FACEBOOK_KEY = env("SOCIAL_AUTH_FACEBOOK_KEY")
SOCIAL_AUTH_FACEBOOK_SECRET = env("SOCIAL_AUTH_FACEBOOK_SECRET")
SOCIAL_AUTH_FACEBOOK_SCOPE = env("SOCIAL_AUTH_FACEBOOK_SCOPE")

SOCIAL_AUTH_GITLAB_KEY = env("SOCIAL_AUTH_GITLAB_KEY")
SOCIAL_AUTH_GITLAB_SECRET = env("SOCIAL_AUTH_GITLAB_SECRET")
SOCIAL_AUTH_GITLAB_SCOPE = env("SOCIAL_AUTH_GITLAB_SCOPE")

SOCIAL_AUTH_GITEA_KEY = env("SOCIAL_AUTH_GITEA_KEY")
SOCIAL_AUTH_GITEA_SECRET = env("SOCIAL_AUTH_GITEA_SECRET")
SOCIAL_AUTH_GITEA_SCOPE = env("SOCIAL_AUTH_GITEA_SCOPE")
SOCIAL_AUTH_GITEA_API_URL = env("SOCIAL_AUTH_GITEA_API_URL")

SOCIAL_AUTH_GITEE_KEY = env("SOCIAL_AUTH_GITEE_KEY")
SOCIAL_AUTH_GITEE_SECRET = env("SOCIAL_AUTH_GITEE_SECRET")
SOCIAL_AUTH_GITEE_SCOPE = env("SOCIAL_AUTH_GITEE_SCOPE")

SOCIAL_AUTH_LINKEDIN_OAUTH2_KEY = env("SOCIAL_AUTH_LINKEDIN_OAUTH2_KEY")
SOCIAL_AUTH_LINKEDIN_OAUTH2_SECRET = env("SOCIAL_AUTH_LINKEDIN_OAUTH2_SECRET")
SOCIAL_AUTH_LINKEDIN_OAUTH2_SCOPE = env("SOCIAL_AUTH_LINKEDIN_OAUTH2_SCOPE")

SOCIAL_AUTH_TWITTER_OAUTH2_KEY = env("SOCIAL_AUTH_TWITTER_OAUTH2_KEY")
SOCIAL_AUTH_TWITTER_OAUTH2_SECRET = env("SOCIAL_AUTH_TWITTER_OAUTH2_SECRET")

SOCIAL_AUTH_HUGGINGFACE_KEY = env("SOCIAL_AUTH_HUGGINGFACE_KEY")
SOCIAL_AUTH_HUGGINGFACE_SECRET = env("SOCIAL_AUTH_HUGGINGFACE_SECRET")
SOCIAL_AUTH_HUGGINGFACE_SCOPE = env("SOCIAL_AUTH_HUGGINGFACE_SCOPE")

# Social Auth Pipeline
# Custom pipeline to update user profile from social auth providers
SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.user.get_username",
    "social_core.pipeline.user.create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
    # Custom pipeline to update user profile from GitHub
    "accounts.pipeline.update_user_profile_from_github",
)


# GitHub OAuth extra arguments to show organization access prompt
# This will trigger the organization authorization screen where users can grant access to their orgs
SOCIAL_AUTH_GITHUB_AUTH_EXTRA_ARGUMENTS = {
    "allow_signup": "true",
}

# site
SITE_ID = 1


# Email Configuration
# For production: Set MAILGUN_API_KEY and MAILGUN_SENDER_DOMAIN in .env
# For local development: Email will be printed to console if Mailgun is not configured

MAILGUN_API_KEY = env("MAILGUN_API_KEY")
MAILGUN_SENDER_DOMAIN = env("MAILGUN_SENDER_DOMAIN")

EMAIL_BACKEND, _anymail = determine_email_backend(
    MAILGUN_API_KEY, MAILGUN_SENDER_DOMAIN
)
ANYMAIL = _anymail or {}

DEFAULT_FROM_EMAIL = "no-reply@openshare.cn"
SERVER_EMAIL = "server@openshare.cn"


# tasks
TASKS = {"default": {"BACKEND": "django_tasks.backends.database.DatabaseBackend"}}


# Logging Configuration
# Provides structured logging with different handlers for development and production
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name} {module}.{funcName}:{lineno} - {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "format": "[{levelname}] {name} - {message}",
            "style": "{",
        },
    },
    "filters": {
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "console_debug": {
            "level": "DEBUG",
            "filters": ["require_debug_true"],
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "app.log",
            "maxBytes": 1024 * 1024 * 10,  # 10MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "error_file": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "error.log",
            "maxBytes": 1024 * 1024 * 10,  # 10MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "points_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "points.log",
            "maxBytes": 1024 * 1024 * 10,  # 10MB
            "backupCount": 10,
            "formatter": "verbose",
        },
        "shop_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "shop.log",
            "maxBytes": 1024 * 1024 * 10,  # 10MB
            "backupCount": 10,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["error_file"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console_debug"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "points": {
            "handlers": ["console", "points_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "points.services": {
            "handlers": ["console", "points_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "shop": {
            "handlers": ["console", "shop_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "shop.services": {
            "handlers": ["console", "shop_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
}
if not TESTING:
    INTERNAL_IPS = [
        # ...
        "127.0.0.1",
        # ...
    ]
    INSTALLED_APPS = [
        *INSTALLED_APPS,
        "debug_toolbar",
    ]
    gzip_index = MIDDLEWARE.index("django.middleware.gzip.GZipMiddleware")
    MIDDLEWARE = [
        *MIDDLEWARE[: gzip_index + 1],
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        *MIDDLEWARE[gzip_index + 1 :],
    ]


# security config
if not DEBUG:
    # HTTPS enforcement
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HSTS
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Content Security
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = "DENY"

    # Session security
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"
    CSRF_COOKIE_SAMESITE = "Strict"
