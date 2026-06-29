import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import httpx

# Load .env file from current working directory or fallback to system environment variables
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

# Configuration Settings
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
# SARVAM_API_KEY = ""
SARVAM_BASE_URL = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai/v1")
SARVAM_MODEL = os.getenv("SARVAM_MODEL", "sarvam-105b")


GROQ_API_KEY1 = os.getenv("GROQ_API_KEY1")
GROQ_API_KEY2 = os.getenv("GROQ_API_KEY2")
GROQ_API_KEY3 = os.getenv("GROQ_API_KEY3")
GROQ_API_KEY4 = os.getenv("GROQ_API_KEY4")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"



# Working directory
CWD = Path.cwd().resolve()

# Log folder configuration
LOG_DIR = Path.home() / ".bhavai" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "bhavai.log"



# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)

logger = logging.getLogger("BhavAI")
logger.info("BhavAI initialized. Activated CWD: %s", CWD)

def get_config_summary():
    """Returns a status summary of loaded settings (excluding API key secrets)."""
    return {
        "CWD": str(CWD),
        "API_URL": SARVAM_BASE_URL,
        "MODEL": SARVAM_MODEL,
        "LOG_FILE": str(LOG_FILE),
        "API_KEY_PRESENT": SARVAM_API_KEY is not None
    }
