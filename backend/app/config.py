import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

WORKSPACE = (ROOT / "workspace").resolve()
DATA = ROOT / "data"

PROVIDER = os.getenv("AI_PROVIDER", "openrouter").strip().lower()
if PROVIDER not in {"openrouter", "openai", "custom"}:
    raise ValueError("AI_PROVIDER must be openrouter, openai, or custom")

if PROVIDER == "openrouter":
    API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
else:
    API_KEY = os.getenv("OPENAI_API_KEY", "")
    BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

MAX_STEPS = max(1, min(int(os.getenv("MAX_STEPS", "6")), 20))
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Automaton")
AUTO_IMPROVE_ENABLED = os.getenv("AUTO_IMPROVE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
WORKSPACE.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)
