"""Central place for env-driven configuration. Import from here, not os.environ directly."""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}. Copy .env.example to .env and fill it in.")
    return val


# LiveKit Cloud project (Settings -> Keys in the LiveKit Cloud dashboard).
LIVEKIT_URL = _require("LIVEKIT_URL")
LIVEKIT_API_KEY = _require("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = _require("LIVEKIT_API_SECRET")

# The LiveKit outbound SIP trunk id (starts with "ST_"), created once via
# scripts/create_sip_trunk.py and pointed at a Twilio Elastic SIP Trunk. This
# is what lets the agent dial out to a real phone number.
SIP_TRUNK_ID = _require("SIP_TRUNK_ID")

TARGET_NUMBER = os.getenv("TARGET_NUMBER", "+18054398008")

OPENAI_API_KEY = _require("OPENAI_API_KEY")
# Pipeline mode: separate STT / LLM / TTS models, never a realtime/speech-to-speech
# model (see ARCHITECTURE.md for why this is a hard requirement here, not a choice).
OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "whisper-1")
OPENAI_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")

AGENT_NAME = os.getenv("AGENT_NAME", "pgai-voicebot-agent")

PATIENT_NAME = os.getenv("PATIENT_NAME", "Asher Pranay Palle")
PATIENT_DOB = os.getenv("PATIENT_DOB", "1995-02-16")
