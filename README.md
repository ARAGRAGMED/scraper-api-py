# Web Scraper API (Python)

FastAPI port of the Node.js Scraper-Api with **secure proxy system** to prevent IP blocking.

## Endpoints

- `GET /scrape?url=[URL]&type=[html|images|text|links|scripts]` - Scrape websites with proxy protection
- `GET /api/proxy-config` - Check current proxy configuration
- `GET /demo` - Demo interface
- `GET /` - Main interface

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 3002
```

Open `http://127.0.0.1:3002/`.

## Proxy Configuration

The API includes a **secure proxy system** that ensures your IP is never exposed when scraping websites:

### Environment Variables
Copy `env.template` to `.env` and configure:

```bash
# Enable proxy usage
USE_PROXY=true

# Custom proxy server (optional)
PROXY_URL=your-proxy-server.com:8080
PROXY_TYPE=http  # http, https, socks5
PROXY_USERNAME=your-username
PROXY_PASSWORD=your-password
PROXY_TIMEOUT=30
```

### How It Works
1. **Direct Access First**: Tries to access the target website directly
2. **Custom Proxy**: If direct access fails, uses your configured proxy
3. **Fallback Proxies**: If no custom proxy, automatically uses free proxy services
4. **IP Protection**: Your server IP is never exposed to target websites

### Fallback Proxy Services
- `cors-anywhere.herokuapp.com`
- `api.allorigins.win`
- `thingproxy.freeboard.io`

## Deploy (Vercel)
- Create `api/index.py` at repo root that imports `app` from `app.main`
- Add `vercel.json` with rewrite to `api/index.py` and function limits
- Place `requirements.txt` at repo root
