import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

LLM_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.anthropic.com")
DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "deepseek-v4-flash")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8765"))
