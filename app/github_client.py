"""Talks to the GitHub REST API.

Without GITHUB_TOKEN you get 60 requests/hour (shared by every visitor!).
With a free token you get 5,000/hour — always set it on Render.
"""
import asyncio
import base64

import httpx

from . import config

API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
         "User-Agent": "ownit-app"}
    if config.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    return h


class GitHub:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def _get(self, path: str, params: dict | None = None, allow_404: bool = False):
        r = await self.client.get(f"{API}{path}", params=params, headers=_headers())
        if r.status_code == 404 and allow_404:
            return None
        if r.status_code == 404:
            raise GitHubError(404, "No GitHub user or repo with that name.")
        if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError(429, "GitHub rate limit reached. Try again in a few minutes.")
        if r.status_code == 409:  # empty repository
            return None
        if r.status_code >= 400:
            raise GitHubError(502, f"GitHub returned {r.status_code}.")
        return r.json()

    async def user(self, username: str) -> dict:
        return await self._get(f"/users/{username}")

    async def repos(self, username: str) -> list[dict]:
        data = await self._get(f"/users/{username}/repos",
                               {"per_page": 100, "sort": "pushed", "type": "owner"})
        return data or []

    async def readme(self, owner: str, repo: str) -> str:
        data = await self._get(f"/repos/{owner}/{repo}/readme", allow_404=True)
        if not data or "content" not in data:
            return ""
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
        except Exception:
            return ""

    async def paths(self, owner: str, repo: str, branch: str) -> list[str]:
        data = await self._get(f"/repos/{owner}/{repo}/git/trees/{branch}",
                               {"recursive": "1"}, allow_404=True)
        if not data:
            return []
        return [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"
                and "node_modules/" not in t["path"]]

    async def commit_dates(self, owner: str, repo: str, author: str) -> tuple[list[str], bool]:
        data = await self._get(f"/repos/{owner}/{repo}/commits",
                               {"per_page": 100, "author": author}, allow_404=True)
        if not data:
            return [], False
        dates = [c["commit"]["author"]["date"] for c in data if c.get("commit", {}).get("author")]
        return dates, len(data) >= 100

    async def repo_bundle(self, owner: str, repo: dict) -> dict:
        """Fetch everything we need for one repo, in parallel."""
        name, branch = repo["name"], repo.get("default_branch") or "main"
        readme, paths, (dates, capped) = await asyncio.gather(
            self.readme(owner, name),
            self.paths(owner, name, branch),
            self.commit_dates(owner, name, owner),
        )
        return {"readme": readme, "paths": paths, "commit_dates": dates, "capped": capped}
