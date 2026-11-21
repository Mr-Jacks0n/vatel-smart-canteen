"""
Configuration Django pour Vatel Smart Canteen.
"""

from datetime import timedelta
from pathlib import Path

import dj_database_url
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    TIME_ZONE=(str, "Africa/Abidjan"),
    RESERVATION_CUTOFF_HOUR=(int, 18),
    LOW_BALANCE_THRESHOLD=(int, 2000),
    WALLET_MAX_BALANCE=(int, 100000),
    TOPUP_AMOUNTS=(list, ["1000", "2000", "5000", "10000", "20000"]),
    ANNUAL_PASS_PRICE=(int, 180000),
    SCHOOL_YEAR_LABEL=(str, "2026-2027"),
    SCHOOL_YEAR_START=(str, "2026-09-01"),
    SCHOOL_YEAR_END=(str, "2027-06-30"),
    PICKUP_PAYMENT_ENABLED=(bool, True),
    MAX_EXTRA_PORTIONS=(int, 1),
    DELIVERY_ENABLED=(bool, True),
    DELIVERY_FEE=(int, 500),
    DEFAULT_DEBIT_FREQUENCY=(str, "DAILY"),
    MAX_UNPAID_RESERVATIONS=(int, 2),
    BANK_TRANSFER_DETAILS=(
        str,
        "Banque Vatel Démo — IBAN CI00 0000 0000 0000 0000 0000 (fictif)",
    ),
    DEMO_PASSWORD=(str, ""),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

DEBUG = env("DEBUG")

if DEBUG:
    SECRET_KEY = env(
        "SECRET_KEY",
        default="django-insecure-local-dev-only-change-in-production",
    )
else:
    SECRET_KEY = env("SECRET_KEY")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "django_htmx",
    "core",
    "accounts",
    "menus",
    "wallet",
    "payments",
    "reservations",
    "parents",
    "canteen",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "axes.middleware.AxesMiddleware",
    "core.middleware.ContentSecurityPolicyMiddleware",
]

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

# Protection anti-force brute : blocage après 5 échecs (identifiant + IP) pendant 15 min
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_FORM_FIELD = "email"
AXES_RESET_ON_SUCCESS = True
AXES_VERBOSE = False

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = env("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "fr"
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "whitenoise.storage.CompressedStaticFilesStorage"
        ),
    },
}
WHITENOISE_MANIFEST_STRICT = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# En-têtes de sécurité HTTP
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Sécurité en production
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Configuration métier Vatel Smart Canteen
RESERVATION_CUTOFF_HOUR = env("RESERVATION_CUTOFF_HOUR")
LOW_BALANCE_THRESHOLD = env("LOW_BALANCE_THRESHOLD")
WALLET_MAX_BALANCE = env("WALLET_MAX_BALANCE")
TOPUP_AMOUNTS = [int(v) for v in env("TOPUP_AMOUNTS")]
ANNUAL_PASS_PRICE = env("ANNUAL_PASS_PRICE")
SCHOOL_YEAR_LABEL = env("SCHOOL_YEAR_LABEL")
SCHOOL_YEAR_START = env("SCHOOL_YEAR_START")
SCHOOL_YEAR_END = env("SCHOOL_YEAR_END")
PICKUP_PAYMENT_ENABLED = env("PICKUP_PAYMENT_ENABLED")
MAX_EXTRA_PORTIONS = env("MAX_EXTRA_PORTIONS")
DELIVERY_ENABLED = env("DELIVERY_ENABLED")
DELIVERY_FEE = env("DELIVERY_FEE")
DEFAULT_DEBIT_FREQUENCY = env("DEFAULT_DEBIT_FREQUENCY")
MAX_UNPAID_RESERVATIONS = env("MAX_UNPAID_RESERVATIONS")
BANK_TRANSFER_DETAILS = env("BANK_TRANSFER_DETAILS")
DEMO_PASSWORD = env("DEMO_PASSWORD")
