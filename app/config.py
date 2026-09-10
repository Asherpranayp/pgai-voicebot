"""Central place for env-driven configuration. Import from here, not os.environ directly."""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}. Copy .env.example to .env and fill it in.")
    return val


TWILIO_ACCOUNT_SID = _require("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _require("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = _require("TWILIO_FROM_NUMBER")
TARGET_NUMBER = os.getenv("TARGET_NUMBER", "+18054398008")

OPENAI_API_KEY = _require("OPENAI_API_KEY")
OPENAI_REALTIME_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-12-17")
OPENAI_VOICE = os.getenv("OPENAI_VOICE", "alloy")

PUBLIC_BASE_URL = _require("PUBLIC_BASE_URL").rstrip("/")
PORT = int(os.getenv("PORT", "8000"))

PATIENT_NAME = os.getenv("PATIENT_NAME", "Asher Pranay Palle")
PATIENT_DOB = os.getenv("PATIENT_DOB", "1995-02-16")
