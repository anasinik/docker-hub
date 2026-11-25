"""
Django settings for the dockerhub project.

Configuration is read from environment variables so the same code base can run
in two environments:

* test / local development (``UKS_TEST_DB=ON``, the default): SQLite database
  and local-memory cache, nothing else has to be running.
* production / docker compose (``UKS_TEST_DB=OFF``): PostgreSQL database and
  Redis cache, connection details come from the environment.
"""

import os
import sys
from pathlib import Path


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


BASE_DIR = Path(__file__).resolve().parent.parent


# Security

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-me-in-production",
)

DEBUG = env_bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

TRUSTED_PROXY_IPS = env_list("DJANGO_TRUSTED_PROXY_IPS")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "accounts",
    "core",
    "repositories",
    "analytics",
]

MIDDLEWARE = [
    "core.middleware.RequestLoggingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.PasswordChangeRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "dockerhub.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "dockerhub.wsgi.application"

# Registry

# Mock client by default, so runserver, tests and CI work without a registry.
# HttpRegistryClient talks to the registry container (docker-compose.yml).
REGISTRY_CLIENT_CLASS = os.environ.get(
    "REGISTRY_CLIENT_CLASS", "repositories.services.registry.mock.MockRegistryClient"
)
# http://registry:5000 when the app runs inside docker compose. 127.0.0.1, not
# localhost: on Windows localhost tries IPv6 first and every call waits ~2 s.
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://127.0.0.1:5000")
REGISTRY_TIMEOUT = float(os.environ.get("REGISTRY_TIMEOUT", "5"))

# Token authentication (/registry/token/). Service and issuer must match
# auth.token in docker/registry/config.yml; the registry verifies tokens with
# the certificate created next to the key by "manage.py generate_registry_keys".
REGISTRY_TOKEN_SERVICE = os.environ.get("REGISTRY_TOKEN_SERVICE", "dockerhub-registry")
REGISTRY_TOKEN_ISSUER = os.environ.get("REGISTRY_TOKEN_ISSUER", "dockerhub-token-issuer")
REGISTRY_TOKEN_PRIVATE_KEY_PATH = Path(
    os.environ.get("REGISTRY_TOKEN_PRIVATE_KEY_PATH") or BASE_DIR / "docker" / "registry" / "auth" / "token.key"
)
REGISTRY_TOKEN_TTL = int(os.environ.get("REGISTRY_TOKEN_TTL", "300"))
# Shared secret the registry sends to /registry/events/ (notifications).
# Empty disables the endpoint.
REGISTRY_EVENTS_TOKEN = os.environ.get("REGISTRY_EVENTS_TOKEN", "")

# Database and cache
# UKS_TEST_DB=ON  -> SQLite + local memory cache (tests, CI, local development)
# UKS_TEST_DB=OFF -> PostgreSQL + Redis (docker compose / production)

UKS_TEST_DB = os.environ.get("UKS_TEST_DB", "ON").strip().upper() == "ON"

if UKS_TEST_DB:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "dockerhub"),
            "USER": os.environ.get("POSTGRES_USER", "dockerhub"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "db"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        }
    }


# Elasticsearch (log analytics)
# The connection is lazy: nothing is sent until a command or view uses it,
# so tests and CI run without an Elasticsearch server.

ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
ELASTICSEARCH_USERNAME = os.environ.get("ELASTICSEARCH_USERNAME", "elastic")
ELASTICSEARCH_PASSWORD = os.environ.get("ELASTIC_PASSWORD", "")
ELASTICSEARCH_TIMEOUT = int(os.environ.get("ELASTICSEARCH_TIMEOUT", "10"))
ELASTICSEARCH_LOG_INDEX = os.environ.get("ELASTICSEARCH_LOG_INDEX", "dockerhub-logs")


# Authentication

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Super admin created by "manage.py setup_super_admin". The generated password
# is written to SUPER_ADMIN_PASSWORD_FILE and must be changed at first sign-in.
SUPER_ADMIN_USERNAME = os.environ.get("SUPER_ADMIN_USERNAME", "superadmin")
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "superadmin@example.com")
SUPER_ADMIN_PASSWORD_FILE = Path(
    os.environ.get("SUPER_ADMIN_PASSWORD_FILE") or BASE_DIR / "secrets" / "superadmin_password.txt"
)

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"


# Internationalization

LANGUAGE_CODE = "en-us"

TIME_ZONE = "Europe/Belgrade"

USE_I18N = True

USE_TZ = True


# Static and media files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Logging
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").strip().upper()
LOG_DIR = Path(os.environ.get("DJANGO_LOG_DIR") or BASE_DIR / "logs")
LOG_TO_FILE = env_bool("DJANGO_LOG_TO_FILE", default=True) and not TESTING

LOG_REQUESTS_SKIP_PREFIXES = ["/" + STATIC_URL.lstrip("/"), "/health/", "/favicon.ico"]

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

if TESTING:
    _root_handlers = ["null"]
elif LOG_TO_FILE:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _root_handlers = ["console", "file", "json_file"]
else:
    _root_handlers = ["console"]

# WatchedFileHandler, not RotatingFileHandler: several Gunicorn workers write
# to the same files, and RotatingFileHandler is not safe across processes.
# Appending is, and the file is reopened if it is rotated externally (logrotate).
_file_handler = {
    "class": "logging.handlers.WatchedFileHandler",
    "encoding": "utf-8",
    "delay": True,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "text": {"format": LOG_FORMAT},
        "json": {"()": "core.logging.JsonFormatter"},
    },
    "handlers": {
        "null": {"class": "logging.NullHandler"},
        "console": {"class": "logging.StreamHandler", "formatter": "text"},
        "file": {**_file_handler, "filename": LOG_DIR / "app.log", "formatter": "text"},
        "json_file": {**_file_handler, "filename": LOG_DIR / "app.json.log", "formatter": "json"},
    },
    "root": {"handlers": _root_handlers, "level": LOG_LEVEL},
    "loggers": {
        # Django's own messages go to the root handlers (no separate console
        # handler). Fixed at INFO so DJANGO_LOG_LEVEL=DEBUG does not log every SQL query.
        "django": {"handlers": [], "level": "INFO", "propagate": True},
        # 4xx/5xx are already logged by RequestLoggingMiddleware; keep only
        # errors here, they carry the traceback.
        "django.request": {"handlers": [], "level": "ERROR", "propagate": True},
        # runserver's access log duplicates RequestLoggingMiddleware.
        "django.server": {"handlers": ["null"], "propagate": False},
    },
}
