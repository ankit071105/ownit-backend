"""Originality scoring — pure functions, no network. Easy to unit test.

Every repo starts at 100. Each "signal" that looks like a tutorial copy
subtracts points, and a few good signs add some back. The final score is
clamped to 0–100 and turned into a verdict.

Every signal is explained to the user, so the score is never a black box.
"""
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime

from .catalog import STARTER_FILES, STARTER_READMES, TUTORIAL_PROJECTS
from .minhash import MinHasher, jaccard, shingles

_hasher = MinHasher()
_STARTER_SIGS = {name: _hasher.signature(shingles(text)) for name, text in STARTER_READMES.items()}

# Words that don't change what a project *is* ("netflix-clone-react-app" == "netflix")
FILLER = {
    "clone", "app", "application", "website", "site", "web", "webapp", "project", "react",
    "reactjs", "js", "javascript", "ts", "typescript", "html", "css", "html5", "css3", "using",
    "with", "in", "and", "simple", "basic", "my", "mini", "ui", "frontend", "backend", "page",
    "game", "flutter", "python", "py", "tailwind", "tailwindcss", "node", "nodejs", "vanilla",
    "nextjs", "next", "vue", "angular", "mern", "mean", "full", "stack", "fullstack", "django",
    "flask", "api", "redux", "firebase", "bootstrap", "the", "a", "of", "for", "main", "v2",
    "v1", "new", "final", "copy", "demo", "practice", "tutorial", "beginner", "dart", "java",
    "kotlin", "android", "ios", "mobile", "vite", "streamlit", "jquery", "php", "spring", "boot",
}

TUTORIAL_HINTS = re.compile(
    r"\b(tutorial|course|bootcamp|udemy|freecodecamp|follow(ed)? along|code ?along|"
    r"traversy|js mastery|javascript mastery|apna college|codewithharry|chai aur code)\b",
    re.I,
)
STORY_HINTS = re.compile(
    r"\b(why i built|problem|motivation|because|i built this|our (club|college|team)|"
    r"challenges?|what i learned|trade-?offs?|architecture|design decisions?)\b",
    re.I,
)


@dataclass
class Signal:
    id: str
    label: str
    impact: int  # negative = looks copied, positive = looks original
    detail: str


@dataclass
class RepoInput:
    name: str
    description: str = ""
    readme: str = ""
    paths: list[str] = field(default_factory=list)
    commit_dates: list[str] = field(default_factory=list)  # ISO timestamps
    commit_count_capped: bool = False  # True if repo has more commits than we fetched
    is_fork: bool = False
    topics: list[str] = field(default_factory=list)
    homepage: str = ""
    has_license: bool = False


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("_", " ").replace("-", " "))


def match_tutorial_name(name: str, description: str = "") -> tuple[str, str] | None:
    """Return (project_type, strength) where strength is 'exact' or 'partial'."""
    name_tokens = _tokens(re.sub(r"([a-z])([A-Z])", r"\1 \2", name))
    core = [t for t in name_tokens if t not in FILLER]
    core_text = " ".join(core)
    name_text = " ".join(name_tokens)
    desc_text = " ".join(_tokens(description))

    best: tuple[str, str] | None = None
    for project, keywords in TUTORIAL_PROJECTS.items():
        for kw in keywords:
            kw_core = " ".join(t for t in _tokens(kw) if t not in FILLER) or kw
            # "netflix-clone-react" -> core "netflix" == keyword  => exact
            # description "A Netflix clone built with React"      => exact
            if core_text == kw_core or re.search(rf"\b{re.escape(kw_core)} clone\b", desc_text):
                return project, "exact"
            # "netflix-recommender-engine" -> mentions it, but has more going on
            if best is None and re.search(rf"\b{re.escape(kw)}\b", name_text):
                best = (project, "partial")
    return best


def starter_readme_match(readme: str) -> tuple[str, float] | None:
    if not readme.strip():
        return None
    sig = _hasher.signature(shingles(readme))
    best_name, best_sim = None, 0.0
    for name, starter_sig in _STARTER_SIGS.items():
        sim = MinHasher.similarity(sig, starter_sig)
        if sim > best_sim:
            best_name, best_sim = name, sim
    return (best_name, best_sim) if best_name else None


def starter_files_match(paths: list[str]) -> tuple[str, float] | None:
    """Share of the repo's files that are just untouched starter files."""
    if not paths:
        return None
    path_set = set(paths)
    best = None
    for name, files in STARTER_FILES.items():
        overlap = len(path_set & files)
        if overlap < 5:
            continue
        share = overlap / len(path_set)
        if best is None or share > best[1]:
            best = (name, share)
    return best


def _commit_days(dates: list[str]) -> int:
    days = set()
    for d in dates:
        try:
            days.add(datetime.fromisoformat(d.replace("Z", "+00:00")).date())
        except ValueError:
            continue
    return len(days)


def verdict_for(score: int) -> str:
    if score >= 70:
        return "yours"
    if score >= 40:
        return "partly"
    return "tutorial"


def score_repo(repo: RepoInput) -> dict:
    signals: list[Signal] = []

    # 1. Fork — the code is literally someone else's
    if repo.is_fork:
        signals.append(Signal("fork", "This is a fork", -45,
                              "Forks show someone else's work first. Pin your own repos instead."))

    # 2. Name matches a famous tutorial project
    name_hit = match_tutorial_name(repo.name, repo.description)
    if name_hit:
        project, strength = name_hit
        if strength == "exact":
            signals.append(Signal("tutorial-name", f"Named like a classic {project}", -30,
                                  f"Recruiters see a '{project}' on most fresher profiles. The name alone says 'tutorial'."))
        else:
            signals.append(Signal("tutorial-topic", f"Close to a common {project}", -12,
                                  f"The idea overlaps with the usual '{project}'. Make the twist obvious in the name and README."))

    # 3. README
    readme = repo.readme or ""
    words = len(_tokens(readme))
    starter = starter_readme_match(readme)
    if not readme.strip():
        signals.append(Signal("no-readme", "No README", -15,
                              "Without a README nobody knows what problem this solves or what you did."))
    elif starter and starter[1] >= 0.35:
        signals.append(Signal("starter-readme", f"README is the default {starter[0]} text", -20,
                              f"About {round(starter[1] * 100)}% of the README matches the {starter[0]} template."))
    elif words < 40:
        signals.append(Signal("thin-readme", "README is only a few lines", -8,
                              f"Only {words} words. Explain the problem, your choices and how to run it."))

    if TUTORIAL_HINTS.search(readme) or TUTORIAL_HINTS.search(repo.description or ""):
        signals.append(Signal("credits-tutorial", "README credits a tutorial or course", -10,
                              "Crediting is honest and good — but then show what you added beyond it."))

    if readme and STORY_HINTS.search(readme) and words >= 120:
        signals.append(Signal("has-story", "README explains the why", +10,
                              "It talks about the problem or decisions — that reads as original work."))

    # 4. Files barely changed from a starter template
    files = starter_files_match(repo.paths)
    if files and files[1] >= 0.6:
        signals.append(Signal("starter-files", f"Mostly untouched {files[0]} files", -15,
                              f"{round(files[1] * 100)}% of files are the starter template's own files."))

    # 5. Commit history — was it built over time or dumped in one go?
    commits = len(repo.commit_dates)
    days = _commit_days(repo.commit_dates)
    if commits and commits <= 3 and not repo.commit_count_capped:
        signals.append(Signal("bulk-upload", f"Only {commits} commit{'s' if commits > 1 else ''}", -15,
                              "The whole project landed in one go, which is how copied code usually arrives."))
    elif commits and days <= 1 and not repo.commit_count_capped:
        signals.append(Signal("one-day", "Built in a single day", -8,
                              "All commits are from one day. Fine for a hackathon, weak as a showcase project."))
    elif days >= 10 or repo.commit_count_capped:
        signals.append(Signal("steady-history", f"Worked on across {days}+ days", +10,
                              "A long commit history shows real, iterative work."))

    # 6. Size — real projects usually grow beyond a handful of files
    code_files = [p for p in repo.paths if not p.startswith(".") and "/." not in p]
    if len(code_files) >= 40 and not repo.is_fork:
        signals.append(Signal("substantial", f"{len(code_files)} files of work", +5,
                              "The project is big enough to have your own decisions in it."))

    score = max(0, min(100, 100 + sum(s.impact for s in signals)))

    polish = [
        {"id": "description", "label": "Has a one-line description", "ok": bool(repo.description.strip())},
        {"id": "topics", "label": "Has topics/tags", "ok": bool(repo.topics)},
        {"id": "homepage", "label": "Has a live demo link", "ok": bool(repo.homepage.strip())},
        {"id": "license", "label": "Has a license", "ok": repo.has_license},
        {"id": "readme", "label": "README longer than 150 words", "ok": words >= 150},
    ]

    return {
        "score": score,
        "verdict": verdict_for(score),
        "signals": [asdict(s) for s in signals],
        "polish": polish,
        "tutorial_match": name_hit[0] if name_hit else None,
        "stats": {"commits": commits, "commit_days": days, "files": len(repo.paths), "readme_words": words},
    }
