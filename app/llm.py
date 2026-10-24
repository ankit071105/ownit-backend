"""Groq LLM call — turns a repo's evidence into a "make it yours" plan.

Groq exposes an OpenAI-compatible endpoint, so a plain HTTP POST is enough.
No SDK needed — easier to understand and one less dependency.
"""
import json
import re

import httpx

from . import config

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = """You are a senior engineer who reviews fresher GitHub portfolios for Indian tech hiring.
You help a student turn a tutorial-style repo into a project that is clearly their own.
Be specific to THIS repo: its stack, files and current README. No generic advice.
Ideas must be buildable by one student in 1–2 weeks, and should solve a real problem
(ideally an Indian context: regional languages, UPI, low bandwidth, college life, local businesses).
Never suggest faking commits, stars or history. Reply with JSON only."""

SCHEMA_HINT = """Return exactly this JSON shape:
{
  "diagnosis": "2 sentences: why this repo currently reads like a tutorial (or why it doesn't)",
  "features": [
    {"title": "short feature name", "why": "the real problem it solves, 1 sentence",
     "how": "concrete build steps using their stack, 2-3 sentences", "effort": "2-3 days"}
  ],
  "new_name": "a better repo name in kebab-case",
  "description": "one-line GitHub description, under 120 characters",
  "topics": ["5 to 8 lowercase github topics"],
  "readme_intro": "the first section of a new README in markdown: a problem-first opening, what it does, and what the student built themselves (use placeholders like [your result] where facts are unknown)",
  "interview_pitch": "a 3-sentence answer to 'tell me about this project' the student can say once the features are built"
}
Give exactly 3 features."""


class LLMError(Exception):
    pass


def _build_user_prompt(repo: dict) -> str:
    signals = "\n".join(f"- {s['label']}: {s['detail']}" for s in repo.get("signals", [])) or "- none"
    files = "\n".join(repo.get("paths", [])[:80]) or "(no files listed)"
    readme = (repo.get("readme") or "(empty)")[:3000]
    return f"""Repo: {repo['name']}
Description: {repo.get('description') or '(none)'}
Main language: {repo.get('language') or 'unknown'}
Originality score: {repo.get('score')}/100 ({repo.get('verdict')})
Looks like tutorial type: {repo.get('tutorial_match') or 'none detected'}

Signals found:
{signals}

Files (first 80):
{files}

Current README (trimmed):
{readme}

{SCHEMA_HINT}"""


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise LLMError("The AI reply was not valid JSON.")
        return json.loads(match.group(0))


async def make_plan(client: httpx.AsyncClient, repo: dict) -> dict:
    if not config.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set on the server.")

    body = {
        "model": config.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _build_user_prompt(repo)},
        ],
        "temperature": 0.6,
        "max_completion_tokens": 2500,
        "response_format": {"type": "json_object"},
    }
    if config.GROQ_MODEL.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"  # faster replies, plenty for this task

    r = await client.post(GROQ_URL, json=body, timeout=60,
                          headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"})
    if r.status_code == 429:
        raise LLMError("The AI is busy right now (rate limit). Try again in a minute.")
    if r.status_code >= 400:
        raise LLMError(f"Groq returned {r.status_code}: {r.text[:200]}")

    content = r.json()["choices"][0]["message"]["content"]
    plan = _parse_json(content)
    plan["features"] = plan.get("features", [])[:3]
    plan["topics"] = [t.lower().replace(" ", "-") for t in plan.get("topics", [])][:8]
    return plan
