from app.catalog import STARTER_READMES
from app.minhash import MinHasher, jaccard, shingles
from app.scoring import RepoInput, match_tutorial_name, score_repo

DAYS = [f"2026-0{m}-1{d}T10:00:00Z" for m in range(1, 4) for d in range(0, 6)]  # 18 days


def test_minhash_close_to_jaccard():
    a = shingles("the quick brown fox jumps over the lazy dog again and again")
    b = shingles("the quick brown fox jumps over the lazy cat again and again")
    h = MinHasher(num_perm=256)
    est = MinHasher.similarity(h.signature(a), h.signature(b))
    assert abs(est - jaccard(a, b)) < 0.15


def test_name_matching():
    assert match_tutorial_name("netflix-clone-react") == ("Netflix clone", "exact")
    assert match_tutorial_name("TodoApp") == ("To-do app", "exact")
    assert match_tutorial_name("weather_app_js") == ("Weather app", "exact")
    assert match_tutorial_name("my-project", "A Netflix clone built with React")[1] == "exact"
    assert match_tutorial_name("netflix-recommender-engine")[1] == "partial"
    assert match_tutorial_name("careeros") is None
    assert match_tutorial_name("token-bucket-shaper") is None


def test_classic_tutorial_copy_scores_low():
    r = score_repo(RepoInput(
        name="netflix-clone",
        readme=STARTER_READMES["Create React App"],
        paths=["package.json", "README.md", ".gitignore", "public/index.html", "public/favicon.ico",
               "public/manifest.json", "src/App.css", "src/App.js", "src/index.css", "src/index.js",
               "src/Row.js", "src/Banner.js"],
        commit_dates=["2026-03-01T10:00:00Z"],
    ))
    assert r["verdict"] == "tutorial", r
    ids = {s["id"] for s in r["signals"]}
    assert {"tutorial-name", "starter-readme", "bulk-upload"} <= ids


def test_original_project_scores_high():
    readme = ("# Token-bucket shaper\nWhy I built this: our college lab network kept choking. " +
              "The problem was bursty traffic, so I designed a token bucket policer. " * 15)
    r = score_repo(RepoInput(
        name="token-bucket-shaper", description="Kernel-level traffic shaper", readme=readme,
        paths=[f"src/file{i}.c" for i in range(50)], commit_dates=DAYS,
        topics=["c", "networking"], has_license=True,
    ))
    assert r["verdict"] == "yours", r
    assert r["score"] == 100


def test_fork_penalised():
    r = score_repo(RepoInput(name="awesome-lib", is_fork=True, readme="x " * 200, commit_dates=DAYS))
    assert any(s["id"] == "fork" for s in r["signals"])
