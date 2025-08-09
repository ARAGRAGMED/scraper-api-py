# Web Scraper API (Python)

FastAPI port of the Node.js Scraper-Api. Endpoints:

- `GET /scrape?url=[URL]&type=[html|images|text|links|scripts]`
- `GET /demo`
- `GET /`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 3002
```

Open `http://127.0.0.1:3002/`.

## Deploy (Vercel)
- Create `api/index.py` at repo root that imports `app` from `app.main`
- Add `vercel.json` with rewrite to `api/index.py` and function limits
- Place `requirements.txt` at repo root
