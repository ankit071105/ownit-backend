"""OwnIt API — finds GitHub repos that read like tutorial copies and
helps turn them into projects that are clearly yours.

Run locally:  uvicorn app.main:app --reload --port 8000
Docs:         http://localhost:8000/docs
"""
import asyncio
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config
from .cache import TTLCache
from .github_client import GitHub, GitHubError
from .llm import LLMError, make_plan
from .scoring import RepoInput, score_repo

USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPONAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

scan_cache = TTLCache(config.CACHE_TTL_SECONDS)
repo_cache = TTLCache(config.CACHE_TTL_SECONDS, max_items=3000)
plan_cache = TTLCache(config.CACHE_TTL_SECONDS * 4)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=20)
    yield
    await app.state.http.aclose()


app = FastAPI(title="OwnIt API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",  # Vercel preview deployments
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _check_username(username: str) -> str:
    username = username.strip().lstrip("@")
    if not USERNAME.match(username):
        raise HTTPException(400, "That doesn't look like a GitHub username.")
    return username


@app.get("/")
@app.get("/api/health")
async def health():
    return {"ok": True, "groq": bool(config.GROQ_API_KEY), "github_token": bool(config.GITHUB_TOKEN)}


@app.get("/api/scan/{username}")
async def scan(username: str):
    username = _check_username(username)
    key = username.lower()
    if cached := scan_cache.get(key):
        return cached

    gh = GitHub(app.state.http)
    try:
        user, repos = await asyncio.gather(gh.user(username), gh.repos(username))
    except GitHubError as e:
        raise HTTPException(e.status, e.message)

    # Own, non-archived repos first; most recently pushed first. Forks are still scored.
    repos = [r for r in repos if not r.get("archived")]
    own = sorted([r for r in repos if not r.get("fork")], key=lambda r: r.get("pushed_at") or "", reverse=True)
    forks = [r for r in repos if r.get("fork")]
    picked = (own + forks)[: config.MAX_REPOS]

    sem = asyncio.Semaphore(4)  # be gentle with GitHub

    async def one(r: dict) -> dict:
        async with sem:
            try:
                bundle = await gh.repo_bundle(user["login"], r)
            except GitHubError as e:
                if e.status == 429:
                    raise
                bundle = {"readme": "", "paths": [], "commit_dates": [], "capped": False}
        result = score_repo(RepoInput(
            name=r["name"], description=r.get("description") or "", readme=bundle["readme"],
            paths=bundle["paths"], commit_dates=bundle["commit_dates"], commit_count_capped=bundle["capped"],
            is_fork=r.get("fork", False), topics=r.get("topics") or [], homepage=r.get("homepage") or "",
            has_license=bool(r.get("license")),
        ))
        public = {
            "name": r["name"], "url": r["html_url"], "description": r.get("description") or "",
            "language": r.get("language"), "stars": r.get("stargazers_count", 0),
            "pushed_at": r.get("pushed_at"), "fork": r.get("fork", False), **result,
        }
        # keep the heavy context (README, file list) server-side for the AI plan
        repo_cache.set(f"{key}/{r['name'].lower()}", {**public, "readme": bundle["readme"], "paths": bundle["paths"]})
        return public

    try:
        scored = await asyncio.gather(*(one(r) for r in picked))
    except GitHubError as e:
        raise HTTPException(e.status, e.message)

    scored.sort(key=lambda x: x["score"])  # weakest first — that's where help is needed
    counts = {v: sum(1 for s in scored if s["verdict"] == v) for v in ("yours", "partly", "tutorial")}
    avg = round(sum(s["score"] for s in scored) / len(scored)) if scored else 0

    data = {
        "user": {"login": user["login"], "name": user.get("name") or user["login"],
                 "avatar": user.get("avatar_url"), "url": user.get("html_url"),
                 "public_repos": user.get("public_repos", 0)},
        "summary": {"average": avg, "scanned": len(scored), **counts},
        "repos": scored,
    }
    scan_cache.set(key, data)
    return data


class PlanRequest(BaseModel):
    username: str = Field(max_length=39)
    repo: str = Field(max_length=100)


@app.post("/api/plan")
async def plan(req: PlanRequest):
    username = _check_username(req.username)
    if not REPONAME.match(req.repo):
        raise HTTPException(400, "Invalid repo name.")
    key = f"{username.lower()}/{req.repo.lower()}"

    if cached := plan_cache.get(key):
        return cached

    repo = repo_cache.get(key)
    if repo is None:
        await scan(username)  # cache expired (e.g. server restarted) — rescan once
        repo = repo_cache.get(key)
    if repo is None:
        raise HTTPException(404, "Scan this user first, then ask for a plan.")

    try:
        result = await make_plan(app.state.http, repo)
    except LLMError as e:
        raise HTTPException(503, str(e))
    except httpx.HTTPError:
        raise HTTPException(503, "Couldn't reach the AI service. Try again.")

    plan_cache.set(key, result)
    return result
