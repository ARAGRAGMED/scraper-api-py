from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(os.path.dirname(BASE_DIR), "public")

# Proxy Configuration
PROXY_CONFIG = {
    "enabled": os.getenv("USE_PROXY", "false").lower() == "true",
    "proxy_url": os.getenv("PROXY_URL", ""),
    "proxy_type": os.getenv("PROXY_TYPE", "http"),  # http, https, socks5
    "proxy_auth": {
        "username": os.getenv("PROXY_USERNAME", ""),
        "password": os.getenv("PROXY_PASSWORD", "")
    },
    "timeout": int(os.getenv("PROXY_TIMEOUT", "30")),
    "fallback_proxies": [
        "https://cors-anywhere.herokuapp.com/",
        "https://api.allorigins.win/get?url=",
        "https://thingproxy.freeboard.io/fetch/"
    ]
}

app = FastAPI(title="Web Scraper API (Python)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve /public if needed
if os.path.isdir(PUBLIC_DIR):
    app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


async def make_proxy_request(url: str, use_fallback: bool = True) -> Dict[str, Any]:
    """Make a request through configured proxy or fallback proxies"""
    
    # If custom proxy is configured and enabled
    if PROXY_CONFIG["enabled"] and PROXY_CONFIG["proxy_url"]:
        try:
            proxies = {
                "http": f"{PROXY_CONFIG['proxy_type']}://{PROXY_CONFIG['proxy_url']}",
                "https": f"{PROXY_CONFIG['proxy_type']}://{PROXY_CONFIG['proxy_url']}"
            }
            
            # Add authentication if provided
            auth = None
            if PROXY_CONFIG["proxy_auth"]["username"] and PROXY_CONFIG["proxy_auth"]["password"]:
                auth = (PROXY_CONFIG["proxy_auth"]["username"], PROXY_CONFIG["proxy_auth"]["password"])
            
            async with httpx.AsyncClient(
                proxies=proxies, 
                auth=auth, 
                timeout=PROXY_CONFIG["timeout"]
            ) as client:
                response = await client.get(url)
                return {
                    "status": response.status_code,
                    "content": response.text if response.status_code == 200 else "Failed",
                    "proxy_used": f"Custom: {PROXY_CONFIG['proxy_url']}"
                }
        except Exception as e:
            if not use_fallback:
                return {"status": "Error", "content": str(e), "proxy_used": f"Custom: {PROXY_CONFIG['proxy_url']}"}
    
    # Try fallback proxies if custom proxy fails or is not configured
    if use_fallback:
        for i, fallback_proxy in enumerate(PROXY_CONFIG["fallback_proxies"]):
            try:
                if "allorigins" in fallback_proxy:
                    # Special handling for allorigins
                    proxy_url = f"{fallback_proxy}{httpx.URL(url)}"
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        response = await client.get(proxy_url)
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("contents"):
                                return {
                                    "status": 200,
                                    "content": data["contents"],
                                    "proxy_used": f"Fallback {i+1}: {fallback_proxy}"
                                }
                else:
                    # Standard proxy handling
                    proxy_url = f"{fallback_proxy}{url}"
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        response = await client.get(proxy_url)
                        return {
                            "status": response.status_code,
                            "content": response.text if response.status_code == 200 else "Failed",
                            "proxy_used": f"Fallback {i+1}: {fallback_proxy}"
                        }
            except Exception as e:
                continue
    
    return {"status": "Error", "content": "All proxy options failed", "proxy_used": "None"}


async def fetch_html(url: str) -> str:
    """Fetch HTML content using proxy system to avoid IP blocking"""
    
    # First try direct access
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
    except Exception:
        # If direct access fails, use proxy system
        proxy_result = await make_proxy_request(url)
        
        if proxy_result["status"] == 200:
            return proxy_result["content"]
        else:
            # Try fallback to http if https fails
            if url.lower().startswith("https://"):
                fallback_url = "http://" + url[8:]
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        r = await client.get(fallback_url)
                        r.raise_for_status()
                        return r.text
                except Exception:
                    pass
            
            # If all else fails, raise an error
            raise httpx.HTTPError(f"Failed to fetch URL: {url}. Proxy error: {proxy_result.get('content', 'Unknown error')}")


async def fetch_html_with_tracking(url: str) -> tuple[str, dict]:
    """Fetch HTML content with proxy usage tracking"""
    
    # First try direct access
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text, {"proxy_used": "Direct connection", "ip_used": "Direct access"}
    except Exception:
        # If direct access fails, use proxy system
        proxy_result = await make_proxy_request(url)
        
        if proxy_result["status"] == 200:
            return proxy_result["content"], {
                "proxy_used": proxy_result.get("proxy_used", "Unknown proxy"),
                "ip_used": "Proxy protected"
            }
        else:
            # Try fallback to http if https fails
            if url.lower().startswith("https://"):
                fallback_url = "http://" + url[8:]
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        r = await client.get(fallback_url)
                        r.raise_for_status()
                        return r.text, {"proxy_used": "HTTP fallback", "ip_used": "Direct access (HTTP)"}
                except Exception:
                    pass
            
            # If all else fails, raise an error
            raise httpx.HTTPError(f"Failed to fetch URL: {url}. Proxy error: {proxy_result.get('content', 'Unknown error')}")


def extract_images(soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
    images: List[Dict[str, str]] = []

    # <img src="...">
    for img in soup.find_all("img"):
        src = img.get("src")
        if src:
            images.append({"src": urljoin(base_url, src)})

    # CSS inline background images: style="background-image:url('...')"
    url_pattern = re.compile(r"url\(['\"]?([^'\"()]+)['\"]?\)")
    for element in soup.find_all(style=True):
        style_value = element.get("style", "")
        for match in url_pattern.findall(style_value):
            images.append({"src": urljoin(base_url, match)})

    # Deduplicate by src
    unique: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in images:
        src = item["src"]
        if src not in seen:
            seen.add(src)
            unique.append(item)
    return unique


def extract_text(soup: BeautifulSoup) -> str:
    # Remove script and style
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    # Cleanup similar to Node version
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"&[a-zA-Z0-9#]+;", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("\n", " ").replace("\t", " ").replace("\r", " ")
    return text


def extract_links(soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
    links: List[Dict[str, str]] = []
    for a in soup.find_all("a"):
        href = a.get("href")
        text = (a.get_text() or "").strip()
        if href:
            if href.startswith(("http://", "https://", "tel:", "mailto:")):
                absolute = href
            else:
                absolute = urljoin(base_url, href)
            links.append({"url": absolute, "text": text})
    # Deduplicate by url
    unique: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in links:
        url_value = item["url"]
        if url_value not in seen:
            seen.add(url_value)
            unique.append(item)
    return unique


def extract_scripts(soup: BeautifulSoup) -> str:
    scripts_content: List[str] = []
    for script in soup.find_all("script"):
        scripts_content.append(script.string or script.get_text() or "")
    return "\n".join(scripts_content)


@app.get("/scrape")
async def scrape(url: Optional[str] = None, type: Optional[str] = None):
    if not url:
        raise HTTPException(status_code=400, detail={"message": "Please provide a valid URL as a query parameter (e.g., ?url=https://example.com)"})
    if type and type not in {"html", "images", "text", "links", "scripts"}:
        raise HTTPException(status_code=400, detail={"message": "Invalid method. Please use one of the following: html, images, text, links, scripts"})

    # Ensure scheme
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    try:
        # Track proxy usage and response details
        proxy_info = {"proxy_used": "Direct connection", "ip_used": "Not tracked"}
        
        # Fetch HTML with proxy tracking
        html, proxy_info = await fetch_html_with_tracking(url)
        soup = BeautifulSoup(html, "lxml")
        page_title = (soup.title.string if soup.title else "").strip()

        # Base response with proxy info
        base_response = {
            "message": "Success",
            "pageTitle": page_title,
            "proxy_used": proxy_info["proxy_used"],
            "ip_used": proxy_info["ip_used"]
        }

        if type == "html":
            return {**base_response, "message": "Raw HTML", "result": html}
        if type == "images":
            return {**base_response, "message": "Images", "result": extract_images(soup, url)}
        if type == "text":
            return {**base_response, "message": "Text", "result": extract_text(soup)}
        if type == "links":
            return {**base_response, "message": "Links extracted successfully", "result": extract_links(soup, url)}
        if type == "scripts":
            return {**base_response, "message": "Scripts extracted successfully", "result": extract_scripts(soup)}

        # Default to raw HTML
        return {**base_response, "message": "Raw HTML", "result": html}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail={"message": "Error fetching the website", "error": str(e)})


@app.get("/demo")
async def demo():
    index_path = os.path.join(PUBLIC_DIR, "demo.html")
    if not os.path.exists(index_path):
        return HTMLResponse(content="<h1>Demo file not found</h1>", status_code=404)
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/proxy-config")
async def get_proxy_config():
    """Get current proxy configuration (without sensitive data)"""
    return {
        "enabled": PROXY_CONFIG["enabled"],
        "proxy_url": PROXY_CONFIG["proxy_url"] if PROXY_CONFIG["enabled"] else "Not configured",
        "proxy_type": PROXY_CONFIG["proxy_type"],
        "timeout": PROXY_CONFIG["timeout"],
        "has_auth": bool(PROXY_CONFIG["proxy_auth"]["username"] and PROXY_CONFIG["proxy_auth"]["password"]),
        "fallback_proxies_count": len(PROXY_CONFIG["fallback_proxies"]),
        "fallback_proxies": PROXY_CONFIG["fallback_proxies"],
        "instructions": "Set environment variables to configure proxy. See env.template for examples."
    }


@app.get("/")
async def root():
    index_path = os.path.join(PUBLIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse(content="<h1>Web Scraper API</h1>")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())
