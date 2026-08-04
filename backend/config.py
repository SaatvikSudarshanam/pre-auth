"""Application configuration loaded from environment / .env.

Secrets live in .env (never committed). See .env.example at project root.
"""
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent           # /backend
PROJECT_ROOT = BASE_DIR.parent                       # project root

# Load project-root .env first, then a backend-local .env as override (if any).
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BASE_DIR / ".env", override=True)

APP_NAME = os.getenv("APP_NAME", "PreAuthIQ")

# Server / URLs
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8068"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
# Extra allowed CORS origins (comma-separated) beyond the built-in dev ones.
EXTRA_CORS_ORIGINS = [
    o.strip() for o in os.getenv("EXTRA_CORS_ORIGINS", "").split(",") if o.strip()
]

# Storage
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Database
DB_PATH = BASE_DIR / "app.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# Auth
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin@2026")

# LLM
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Google OAuth (customer sign-in). Secrets belong in .env only.
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
# Must exactly match an Authorized redirect URI in the Google Cloud console.
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:8068/rbac/oauth/google/callback"
)
GOOGLE_AUTH_URI = os.getenv("GOOGLE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth")
GOOGLE_TOKEN_URI = os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")
GOOGLE_USERINFO_URI = os.getenv(
    "GOOGLE_USERINFO_URI", "https://openidconnect.googleapis.com/v1/userinfo"
)

# Policy versions — bump when the text changes so re-consent is tracked.
PRIVACY_POLICY_VERSION = os.getenv("PRIVACY_POLICY_VERSION", "2026-07-12")
COOKIE_POLICY_VERSION = os.getenv("COOKIE_POLICY_VERSION", "2026-07-12")

# Twilio voice (admin decision notifications). Secrets stay in backend/.env only.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")  # E.164, your Twilio number
TWILIO_TEST_PHONE_NUMBER = os.getenv("TWILIO_TEST_PHONE_NUMBER", "+919014582844")  # Static test number for development
TWILIO_CALLBACK_URL = os.getenv("TWILIO_CALLBACK_URL", "")  # Base URL for TwiML callbacks (e.g. https://ngrok.io/api/twilio/twiml)

# Upload constraints
ALLOWED_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
