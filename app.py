import re
import time
from urllib.parse import urljoin, urlparse, quote_plus

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup


st.set_page_config(page_title="Keyword Forum Monitor", layout="wide")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 12
MAX_SEARCH_RESULTS = 20
DEFAULT_EXCLUDE_DOMAINS = [
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "tiktok.com",
    "amazon.com",
]
DEFAULT_INCLUDE_HINTS = [
    "forum",
    "community",
    "discussion",
    "thread",
    "board",
    "club",
    "owners",
]


# -----------------------------
# Helpers
# -----------------------------
def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def looks_relevant(url: str, title: str, snippet: str, keywords: list[str], include_hints: list[str]) -> bool:
    haystack = f"{url} {title} {snippet}".lower()
    keyword_hit = any(k.lower() in haystack for k in keywords if k.strip())
    hint_hit = any(h.lower() in haystack for h in include_hints if h.strip())
    return keyword_hit and hint_hit


def search_duckduckgo(query: str, max_results: int = 10) -> list[dict]:
    """
    Uses the DuckDuckGo HTML endpoint. This is a pragmatic option for a lightweight app,
    but search result markup can change, so keep this parser simple.
    """
    session = get_session()
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    results = []

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        return [{"title": "Search error", "url": "", "snippet": str(e)}]

    soup = BeautifulSoup(resp.text, "html.parser")
    seen = set()

    for block in soup.select(".result"):
        link = block.select_one(".result__title a")
        snippet = block.select_one(".result__snippet")
        if not link:
            continue

        href = link.get("href", "").strip()
        title = clean_text(link.get_text(" ", strip=True))
        desc = clean_text(snippet.get_text(" ", strip=True) if snippet else "")

        if not href or href in seen:
            continue
        seen.add(href)

        results.append({
            "title": title,
            "url": href,
            "snippet": desc,
        })

        if len(results) >= max_results:
            break

    return results


def discover_candidate_urls(keyword_phrase: str, max_results: int = 20) -> list[dict]:
    keywords = [k for k in re.split(r"\s+", keyword_phrase.strip()) if k]
    search_queries = [
        f'{keyword_phrase} forum',
        f'{keyword_phrase} discussion',
        f'{keyword_phrase} community',
        f'{keyword_phrase} site:reddit.com',
    ]

    merged = []
    seen_urls = set()

    for query in search_queries:
        for item in search_duckduckgo(query, max_results=max_results):
            url = item.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            item["matched_query"] = query
            item["relevant"] = looks_relevant(
                url=url,
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                keywords=keywords,
                include_hints=DEFAULT_INCLUDE_HINTS,
            )
            merged.append(item)

    return merged[:max_results]


def fetch_page(url: str) -> dict:
    session = get_session()
    url = normalize_url(url)

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            return {"url": url, "ok": False, "error": f"Skipped non-HTML content: {content_type}"}

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
        text = clean_text(soup.get_text(" ", strip=True))
        links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            absolute = urljoin(resp.url, href)
            anchor = clean_text(a.get_text(" ", strip=True))
            if absolute.startswith("http"):
                links.append({"anchor": anchor, "url": absolute})

        return {
            "url": resp.url,
            "ok": True,
            "title": title,
            "text": text,
            "links": links,
        }
    except requests.RequestException as e:
        return {"url": url, "ok": False, "error": str(e)}


def extract_keyword_mentions(text: str, keywords: list[str], window: int = 180) -> list[str]:
    matches = []
    lowered = text.lower()

    for keyword in keywords:
        k = keyword.lower().strip()
        if not k:
            continue
        for m in re.finditer(re.escape(k), lowered):
            start = max(0, m.start() - window)
            end = min(len(text), m.end() + window)
            snippet = clean_text(text[start:end])
            if snippet and snippet not in matches:
                matches.append(snippet)
            if len(matches) >= 25:
                return matches
    return matches


def score_page(page: dict, keyword_phrase: str) -> dict:
    keywords = [k for k in re.split(r"\s+", keyword_phrase.strip()) if k]
    title = page.get("title", "")
    text = page.get("text", "")
    combined = f"{title} {text}".lower()

    keyword_hits = sum(combined.count(k.lower()) for k in keywords if k)
    title_boost = sum(3 for k in keywords if k.lower() in title.lower())
    forum_boost = 2 if any(h in combined for h in DEFAULT_INCLUDE_HINTS) else 0
    score = keyword_hits + title_boost + forum_boost

    mentions = extract_keyword_mentions(text, keywords)

    return {
        "url": page.get("url", ""),
        "title": title,
        "score": score,
        "mention_count": len(mentions),
        "mentions": mentions,
    }


def scrape_and_analyze(urls: list[str], keyword_phrase: str, delay_seconds: float = 0.6) -> tuple[list[dict], list[dict]]:
    page_results = []
    score_results = []

    for url in urls:
        page = fetch_page(url)
        page_results.append(page)

        if page.get("ok"):
            scored = score_page(page, keyword_phrase)
            score_results.append(scored)

        time.sleep(delay_seconds)

    score_results.sort(key=lambda x: (x["score"], x["mention_count"]), reverse=True)
    return page_results, score_results


def filter_discovered_urls(items: list[dict], excluded_domains: list[str]) -> list[dict]:
    filtered = []
    for item in items:
        url = item.get("url", "")
        domain = domain_of(url)
        if any(excl in domain for excl in excluded_domains):
            continue
        filtered.append(item)
    return filtered


# -----------------------------
# UI
# -----------------------------
st.title("Keyword-Based Website Discovery + Scraper")
st.caption(
    "Enter a keyword or topic, discover relevant forum/community URLs, then scrape and inspect pages that mention it."
)

if "discovered_urls" not in st.session_state:
    st.session_state.discovered_urls = []
if "selected_urls" not in st.session_state:
    st.session_state.selected_urls = []
if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = []
if "page_results" not in st.session_state:
    st.session_state.page_results = []

with st.sidebar:
    st.header("Settings")
    max_discovery = st.number_input("Max discovered URLs", min_value=5, max_value=50, value=15, step=1)
    crawl_delay = st.number_input("Delay between page requests (seconds)", min_value=0.0, max_value=5.0, value=0.6, step=0.1)
    excluded_input = st.text_area(
        "Exclude domains (one per line)",
        value="\n".join(DEFAULT_EXCLUDE_DOMAINS),
        help="Useful for skipping social sites or stores when you only want forums, communities, and discussion pages.",
    )
    excluded_domains = [x.strip().lower() for x in excluded_input.splitlines() if x.strip()]

keyword_phrase = st.text_input(
    "Keyword or topic",
    placeholder="Ford Maverick, RAM RHO, Tacoma intercooler, etc.",
    key="keyword_phrase",
)

col1, col2 = st.columns([1, 1])

with col1:
    discover_clicked = st.button("Find matching URLs", use_container_width=True)
with col2:
    scrape_clicked = st.button("Scrape selected URLs", use_container_width=True)


if discover_clicked:
    if not keyword_phrase.strip():
        st.warning("Enter a keyword or topic first.")