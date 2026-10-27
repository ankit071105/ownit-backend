# OwnIt

**Is your GitHub project yours, or the tutorial's?**

OwnIt reads a fresher's public GitHub repos, flags the ones that look like tutorial copies (Netflix clone, to-do app, untouched Create React App README, everything pushed in 2 commits…), and uses Groq to write a "make it yours" plan for each repo: 3 real features, a new name, description, topics, README opening and an interview pitch.

## Architecture

```
Next.js (Vercel)  ──►  FastAPI (Render)  ──►  GitHub REST API
                               │
                               └──────────►  Groq (only for the plan)
```

| Step | Where | What happens |
|---|---|---|
| 1 | `GET /api/scan/{username}` | Fetch up to 12 recent repos, then README + file tree + commits for each (parallel, max 4 at a time) |
| 2 | `scoring.py` | Pure-Python rules, no AI. Every repo starts at 100 |
| 3 | `POST /api/plan` | Sends that repo's evidence to Groq, gets back JSON |

### How the originality score works

| Signal | Points | How it's detected |
|---|---|---|
| Fork | −45 | GitHub `fork` flag |
| Named like a tutorial project | −30 | Name minus filler words (`clone`, `app`, `react`…) equals a known idea in `catalog.py` |
| Close to a tutorial idea | −12 | Known idea appears inside a longer name |
| Default starter README | −20 | **MinHash** similarity ≥ 0.35 with CRA / Vite / Next / Flutter / Angular / Vue README |
| No README | −15 | |
| Mostly starter files | −15 | ≥ 60% of files are the starter's own files |
| ≤ 3 commits | −15 | Commits by the owner |
| All commits in 1 day | −8 | |
| Credits a tutorial / course | −10 | Regex: tutorial, udemy, codewithharry… |
| 10+ days of commits | +10 | |
| README explains the why (120+ words) | +10 | Regex: problem, why I built, architecture… |
| 40+ files | +5 | |

70+ = reads as yours, 40–69 = partly yours, <40 = reads like a tutorial.

`backend/app/minhash.py` is written from scratch with comments, so you can explain it in interviews.

## Project structure

```
ownit/
├── render.yaml                  # Render blueprint for the backend
├── backend/
│   ├── app/
│   │   ├── main.py              # API routes, caching, CORS
│   │   ├── github_client.py     # GitHub REST calls
│   │   ├── scoring.py           # all scoring rules
│   │   ├── catalog.py           # tutorial names, starter READMEs + files  ← add more here
│   │   ├── minhash.py           # MinHash from scratch
│   │   ├── llm.py               # Groq call + prompt
│   │   ├── cache.py             # in-memory TTL cache
│   │   └── config.py            # env vars
│   ├── tests/test_scoring.py
│   └── requirements.txt
└── frontend/
    ├── app/page.tsx             # landing page
    ├── app/check/[username]/page.tsx   # results page
    ├── components/              # Fingerprint, SeparationStory, RepoRow, PlanPanel…
    └── lib/api.ts               # API client + types
```

## Run locally

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill GITHUB_TOKEN and GROQ_API_KEY
export $(cat .env | xargs)  # Windows: set them manually
uvicorn app.main:app --reload --port 8000
pytest                      # 5 tests

# frontend (new terminal)
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev                 # http://localhost:3000
```

## Deploy

### 1. Keys
- **GitHub token:** github.com → Settings → Developer settings → Personal access tokens → Fine-grained → **no permissions needed** (public data only). Without it you get only 60 requests/hour for everyone.
- **Groq key:** console.groq.com/keys

### 2. Backend on Render
1. Push this whole folder to a GitHub repo.
2. Render → New → **Blueprint** → pick the repo (it reads `render.yaml`).
3. Fill env vars: `GITHUB_TOKEN`, `GROQ_API_KEY`, `ALLOWED_ORIGINS` (your Vercel URL, e.g. `https://ownit.vercel.app`).
4. Open `https://<your-service>.onrender.com/api/health` → should show `"groq": true, "github_token": true`.

### 3. Frontend on Vercel
1. Vercel → Add New Project → same repo → **Root Directory: `frontend`**.
2. Env var: `NEXT_PUBLIC_API_URL=https://<your-service>.onrender.com` (no trailing slash).
3. Deploy. Then put the final Vercel URL in Render's `ALLOWED_ORIGINS` and redeploy the backend.

> Render's free plan sleeps after 15 min. The first scan after that takes ~40s; the UI already tells users this. Use a free cron (e.g. cron-job.org) hitting `/api/health` every 10 min if you want it awake.

### If Groq retires the model
Set `GROQ_MODEL` on Render to any model from console.groq.com/docs/models. Default is `openai/gpt-oss-120b`.

## Ideas for v2
- GitHub OAuth + one-click PR that adds the new README
- Store scans in Postgres to show "score went from 23 → 78"
- Compare against real tutorial repos (fetch the top 50 "netflix clone" repos and MinHash their code)
