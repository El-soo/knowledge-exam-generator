from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "local-workbench-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [x.strip() for x in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if x.strip()]

INSTALLED_APPS = [
    "django.contrib.contenttypes", "django.contrib.staticfiles",
    "rest_framework", "corsheaders",
    "common.apps.CommonConfig",
    "apps.courses", "apps.knowledge", "apps.questions", "apps.papers",
    "apps.system_settings", "apps.dashboard", "apps.ai_service", "apps.agents",
]
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "common.middleware.RequestIdMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = []
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3", "OPTIONS": {"timeout": 20}}}
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CORS_ALLOWED_ORIGINS = [x.strip() for x in os.getenv("CORS_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if x.strip()]
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": ["common.renderers.UnifiedJSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE + 1024 * 1024
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
CHROMA_PATH = Path(os.getenv("CHROMA_PATH", str(BASE_DIR / "data" / "chroma")))
_langgraph_checkpoint_path = Path(os.getenv("LANGGRAPH_CHECKPOINT_PATH", "data/agent_checkpoints.sqlite3"))
LANGGRAPH_CHECKPOINT_PATH = (
    _langgraph_checkpoint_path
    if _langgraph_checkpoint_path.is_absolute()
    else (BASE_DIR / _langgraph_checkpoint_path).resolve()
)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"standard": {"format": "{asctime} {levelname} {name} {message}", "style": "{"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
        "file": {"class": "logging.handlers.RotatingFileHandler", "filename": LOG_DIR / "app.log", "maxBytes": 5_000_000, "backupCount": 5, "formatter": "standard"},
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
}
