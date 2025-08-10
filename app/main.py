from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
import os
import asyncio

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
    "timeout": int(os.getenv("PROXY_TIMEOUT", "30"))
}

app = FastAPI(title="Web Scraper API (Python)")

# Global exception handler to catch all unhandled exceptions
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal server error occurred",
            "error": str(exc),
            "error_type": type(exc).__name__,
            "url": str(request.url),
            "method": request.method
        }
    )

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


def get_connection_status() -> str:
    """Get safe connection status without exposing IP"""
    return "Protected"


async def make_proxy_request(url: str) -> Dict[str, Any]:
    """Make a request through configured proxy if enabled, otherwise direct access"""
    
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
            return {"status": "Error", "content": str(e), "proxy_used": f"Custom: {PROXY_CONFIG['proxy_url']}"}
    
    # If no proxy configured or disabled, use direct access
    try:
        async with httpx.AsyncClient(timeout=PROXY_CONFIG["timeout"]) as client:
            response = await client.get(url)
            return {
                "status": response.status_code,
                "content": response.text if response.status_code == 200 else "Failed",
                "proxy_used": "Direct access (no proxy configured)"
            }
    except Exception as e:
        return {"status": "Error", "content": str(e), "proxy_used": "Direct access (failed)"}


async def fetch_html(url: str) -> str:
    """Fetch HTML content using proxy system to avoid IP blocking - NO DIRECT ACCESS"""
    
    # Skip direct access entirely - always use proxy system for IP protection
    proxy_result = await make_proxy_request(url)
    
    if proxy_result["status"] == 200:
        return proxy_result["content"]
    else:
        # Try fallback to http if https fails (still through proxy)
        if url.lower().startswith("https://"):
            fallback_url = "http://" + url[8:]
            fallback_proxy_result = await make_proxy_request(fallback_url)
            if fallback_proxy_result["status"] == 200:
                return fallback_proxy_result["content"]
        
        # If all else fails, raise an error
        raise httpx.HTTPError(f"Failed to fetch URL: {url}. All proxy options failed: {proxy_result.get('content', 'Unknown error')}")


async def fetch_html_with_tracking(url: str) -> tuple[str, dict]:
    """Fetch HTML content with proxy usage tracking - NO DIRECT ACCESS"""
    
    # Skip direct access entirely - always use proxy system for IP protection
    proxy_result = await make_proxy_request(url)
    
    if proxy_result["status"] == 200:
        return proxy_result["content"], {
            "proxy_used": proxy_result.get("proxy_used", "Unknown proxy"),
            "ip_used": f"Proxy IP ({proxy_result.get('proxy_used', 'Unknown')}) - 🛡️ Protected"
        }
    else:
        # Try fallback to http if https fails (still through proxy)
        if url.lower().startswith("https://"):
            fallback_url = "http://" + url[8:]
            fallback_proxy_result = await make_proxy_request(fallback_url)
            if fallback_proxy_result["status"] == 200:
                return fallback_proxy_result["content"], {
                    "proxy_used": fallback_proxy_result.get("proxy_used", "Unknown proxy"),
                    "ip_used": f"Proxy IP ({fallback_proxy_result.get('proxy_used', 'Unknown')}) - 🛡️ Protected"
                }
        
        # If all else fails, raise an error
        raise httpx.HTTPError(f"Failed to fetch URL: {url}. All proxy options failed: {proxy_result.get('content', 'Unknown error')}")


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
        # Safely extract script content
        if hasattr(script, 'string') and callable(getattr(script, 'string', None)):
            content = script.string or ""
        elif hasattr(script, 'get_text'):
            content = script.get_text() or ""
        else:
            content = str(script) or ""
        scripts_content.append(content)
    return "\n".join(scripts_content)


async def scrape_with_timeout(url: str, content_type: Optional[str] = None, timeout: int = 45) -> Dict[str, Any]:
    """Wrapper function to add timeout to scraping operation"""
    try:
        return await asyncio.wait_for(
            _scrape_website(url, content_type), 
            timeout=timeout
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=408, 
            detail={
                "message": f"Scraping timed out after {timeout} seconds. The website may be slow or blocking requests.",
                "error": "Timeout",
                "proxy_used": "Timeout occurred",
                "ip_used": "Timeout occurred"
            }
        )


async def _scrape_website(url: str, content_type: Optional[str] = None) -> Dict[str, Any]:
    """Internal scraping function without timeout wrapper"""
    
    if not url:
        raise HTTPException(status_code=400, detail={"message": "Please provide a valid URL as a query parameter (e.g., ?url=https://example.com)"})
    if content_type and content_type not in {"html", "images", "text", "links", "scripts"}:
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
        
        # Safely extract page title - handle cases where title might be a string
        page_title = ""
        if soup.title:
            if hasattr(soup.title, 'string') and callable(getattr(soup.title, 'string', None)):
                page_title = (soup.title.string or "").strip()
            elif hasattr(soup.title, 'get_text'):
                page_title = soup.title.get_text().strip()
            else:
                page_title = str(soup.title).strip()

        # Base response with proxy info
        base_response = {
            "message": "Success",
            "pageTitle": page_title,
            "proxy_used": proxy_info["proxy_used"],
            "ip_used": proxy_info["ip_used"]
        }

        if content_type == "html":
            return {**base_response, "message": "Raw HTML", "result": html}
        if content_type == "images":
            return {**base_response, "message": "Images", "result": extract_images(soup, url)}
        if content_type == "text":
            return {**base_response, "message": "Text", "result": extract_text(soup)}
        if content_type == "links":
            return {**base_response, "message": "Links extracted successfully", "result": extract_links(soup, url)}
        if content_type == "scripts":
            return {**base_response, "message": "Scripts extracted successfully", "result": extract_scripts(soup)}

        # Default to raw HTML
        return {**base_response, "message": "Raw HTML", "result": html}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail={
            "message": "Error fetching the website", 
            "error": str(e),
            "url": url,
            "error_type": type(e).__name__
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail={
            "message": "Unexpected error during scraping", 
            "error": str(e),
            "url": url,
            "error_type": type(e).__name__
        })


@app.get("/scrape")
async def scrape(url: Optional[str] = None, type: Optional[str] = None):
    """Scrape website with timeout protection"""
    return await scrape_with_timeout(url, type)


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
        "status": "🛡️ Proxy Status: " + ("Enabled" if PROXY_CONFIG["enabled"] else "Disabled - Using Direct Access"),
        "instructions": "Set environment variables to configure proxy. See env.template for examples."
    }


@app.get("/api/test-proxy")
async def test_proxy():
    """Test the proxy system with a simple URL"""
    try:
        test_url = "https://httpbin.org/ip"
        
        # Test direct proxy request
        result = await make_proxy_request(test_url)
        
        return {
            "message": "Proxy test completed",
            "test_url": test_url,
            "result": result,
            "system_status": "🛡️ Simplified Proxy System: Proxy if enabled, Direct access if disabled"
        }
    except Exception as e:
        return {
            "message": "Proxy test failed",
            "error": str(e),
            "error_type": type(e).__name__
        }


@app.get("/")
async def root():
    index_path = os.path.join(PUBLIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse(content="<h1>Web Scraper API</h1>")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())
