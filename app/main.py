from typing import Optional, List, Dict
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


async def fetch_html(url: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
        except httpx.HTTPError:
            # Retry with http:// if https fails
            if url.lower().startswith("https://"):
                fallback = "http://" + url[8:]
                r = await client.get(fallback)
                r.raise_for_status()
                return r.text
            raise


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
        html = await fetch_html(url)
        soup = BeautifulSoup(html, "lxml")
        page_title = (soup.title.string if soup.title else "").strip()

        if type == "html":
            return {"message": "Raw HTML", "pageTitle": page_title, "result": html}
        if type == "images":
            return {"message": "Images", "pageTitle": page_title, "result": extract_images(soup, url)}
        if type == "text":
            return {"message": "Text", "pageTitle": page_title, "result": extract_text(soup)}
        if type == "links":
            return {"message": "Links extracted successfully", "pageTitle": page_title, "result": extract_links(soup, url)}
        if type == "scripts":
            return {"message": "Scripts extracted successfully", "pageTitle": page_title, "result": extract_scripts(soup)}

        # Default to raw HTML
        return {"message": "Raw HTML", "pageTitle": page_title, "result": html}
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail={"message": "Error fetching the website", "error": str(e)})


@app.get("/demo")
async def demo():
    index_path = os.path.join(PUBLIC_DIR, "demo.html")
    if not os.path.exists(index_path):
        return HTMLResponse(content="<h1>Demo file not found</h1>", status_code=404)
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/")
async def root():
    index_path = os.path.join(PUBLIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse(content="<h1>Web Scraper API</h1>")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())
