import os
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/".env")
WORKSPACE=(ROOT/"workspace").resolve()
DATA=ROOT/"data"
API_KEY=os.getenv("OPENAI_API_KEY","")
BASE_URL=os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1").rstrip("/")
MODEL=os.getenv("OPENAI_MODEL","gpt-4o-mini")
MAX_STEPS=int(os.getenv("MAX_STEPS","6"))
WORKSPACE.mkdir(parents=True,exist_ok=True)
DATA.mkdir(parents=True,exist_ok=True)
