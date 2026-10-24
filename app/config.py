"""All settings come from environment variables (set them on Render)."""
import os


def _list(value: str) -> list[str]:
    return [v.strip().rstrip("/") for v in value.split(",") if v.strip()]


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Groq's model list changes often. Override with GROQ_MODEL if this one is retired.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Comma-separated list, e.g. "https://ownit.vercel.app,http://localhost:3000"
ALLOWED_ORIGINS = _list(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000"))

# How many repos to scan per user (each repo costs ~3 GitHub API calls)
MAX_REPOS = int(os.getenv("MAX_REPOS", "12"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "1800"))
