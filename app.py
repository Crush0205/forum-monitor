import re
import time
from collections import Counter
from urllib.parse import urljoin, urlparse, quote_plus
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Demand Finder", layout="wide")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

HEADERS = {"User-Agent": USER_AGENT}

BLOCKED_DOMAINS = {
    "google.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "pinterest.com",
    "amazon.com",
    "ebay.com",
    "wikipedia.org",
}

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "your",
    "about", "just", "they", "them", "what", "when", "where", "would",
    "there", "their", "into", "than", "then", "were", "been", "will",
    "make", "more", "some", "very", "also", "here", "over", "does",
    "need", "looking", "look", "help", "best", "good", "great", "much",
    "really", "like", "site", "page", "forum", "club", "community",
    "discussion", "thread", "post", "posts", "want", "which", "using",
    "used", "after", "before", "still", "getting", "got", "said", "says",
    "because", "into", "onto", "only", "same", "each", "many", "most",
    "other", "these", "those", "than", "could", "should", "being", "while",
    "ever", "even", "any", "our", "out", "all", "can", "you", "how", "why",
    "is", "are", "was", "were", "be", "to", "of", "in", "on", "a", "an",
}

PAIN_POINT_PATTERNS = [
    r"\bproblem\b", r"\bissue\b", r"\bissues\b", r"\bbroken\b", r"\bfail\b",
    r"\bfailing\b", r"\bfailure\b", r"\boverheat\b", r"\boverheating\b",
    r"\bleak\b", r"\bleaking\b", r"\bcrack\b", r"\bcracked\b", r"\bwon't\b",
    r"\bdoesn't\b", r"\bnot working\b", r"\bneed to fix\b", r"\bannoying\b",
    r"\bhate\b", r"\bfrustrat", r"\bstruggling\b", r"\bslow\b", r"\bweak\b",
    r"\bbad\b", r"\bunreliable\b", r"\bnoise\b", r"\bvibration\b",
    r"\bheat soak\b",
]

BUYING_SIGNAL_PATTERNS = [
    r"\bbest\b", r"\brecommend\b", r"\brecommendation\b", r"\bworth it\b",
    r"\bwhich one\b", r"\bwhat should i buy\b", r"\bthinking about buying\b",
    r"\bready to buy\b", r"\bcompare\b", r"\bcomparison\b", r"\bprice\b",
    r"\bcost\b", r"\bafford\b", r"\bdiscount\b", r"\bsale\b",
    r"\bwhere can i buy\b", r"\bwho makes\b", r"\blooking for\b",
]

QUESTION_PATTERNS = [
    r"\?$", r"\bhow do i\b", r"\bwhat is the best\b", r"\banyone know\b",
    r"\bhas anyone\b", r"\bshould i\b", r"\bworth\b",
]

THREAD_HINTS = [
    "/thread", "/threads", "/topic", "/topics", "/discussion", "/discussions",
    "/forum", "/forums", "/community", "/communities", "/post", "/posts",
    "/article", "/articles", "/review", "/reviews", "/question", "/questions",
    "/faq", "/board", "/boards", "/comments/"
]

BAD_LINK_HINTS = [
    "login", "sign-in", "signin", "register", "account", "privacy", "terms",
    "contact", "about", "cart", "checkout", "wishlist", "support", "help",
    "javascript:", "mailto:", "#"
]

BLOCKED_PAGE_SIGNALS = [
    "access denied",
    "forbidden",
    "enable javascript",
    "verify you are human",
    "captcha",
    "cloudflare",
    "bot check",
    "please enable cookies",
    "checking if the site connection is secure",
    "temporarily blocked",
]

DEFAULT_KEYWORDS = [
    "Ford Maverick",
    "RAM RHO",
    "Tacoma intercooler",
]

for key, default in {
    "discovered_urls": [],
    "raw_mentions": [],
    "dashboard_rows": [],
    "signal_rows": [],
    "search_error": "",
    "debug_messages": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def log_debug(message: str):
    st.session_state.debug_messages.append(message)


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def clean_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def domain_allowed(url: str) -> bool:
    domain = clean_domain(url)
    if not domain:
        return False
    for blocked in BLOCKED_DOMAINS:
        if domain == blocked or domain.endswith("." + blocked):
            return False
    return True


def is_reddit_url(url: str) -> bool:
    domain = clean_domain(url)
    return domain.endswith("reddit.com")


def reddit_rss_url(url: str) -> str:
    base = url.rstrip("/")
    if base.endswith(".rss"):
        return base
    return base + "/.rss"


def fetch_response(url: str):
    return requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)


def fetch_url(url: str) -> str:
    resp = fetch_response(url)
    resp.raise_for_status()
    return resp.text


def clean_text(text: str) -> str:
    text = BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_real_url(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith(("http://", "https://")):
        return href
    return href


def looks_relevant(url: str, title: str, keyword: str) -> bool:
    blob = f"{url} {title}".lower()
    keyword = keyword.lower().strip()

    if not keyword:
        return True

    if keyword in blob:
        return True

    parts = [p for p in re.split(r"[\s\-_\/]+", keyword) if len(p) >= 3]
    if not parts:
        return True

    matches = sum(1 for p in parts if p in blob)
    return matches >= 1


def discover_with_bing_rss(keyword: str, max_results: int = 15) -> list[dict]:
    query = f"{keyword} forum OR discussion OR community OR club OR blog"
    rss_url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}"

    results = []
    seen = set()

    resp = fetch_response(rss_url)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title", default=""))
        link = normalize_url(item.findtext("link", default=""))

        if not link or link in seen:
            continue
        if not domain_allowed(link):
            continue
        if not looks_relevant(link, title, keyword):
            continue

        seen.add(link)
        results.append(
            {
                "title": title or link,
                "url": link,
                "domain": clean_domain(link),
                "source_type": "bing_rss",
            }
        )

        if len(results) >= max_results:
            break

    return results


def discover_with_duckduckgo(keyword: str, max_results: int = 15) -> list[dict]:
    query = f"{keyword} forum OR board OR discussion OR club OR community OR blog"
    search_url = "https://html.duckduckgo.com/html/"

    results = []
    seen = set()

    resp = requests.get(search_url, params={"q": query}, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    candidates = soup.select(".result__a")
    if not candidates:
        candidates = soup.select("a[href]")

    for link_tag in candidates:
        href = (link_tag.get("href") or "").strip()
        title = clean_text(link_tag.get_text(" ", strip=True))
        url = normalize_url(extract_real_url(href))

        if not url or url in seen:
            continue
        if not url.startswith(("http://", "https://")):
            continue
        if not domain_allowed(url):
            continue
        if title or url:
            if not looks_relevant(url, title, keyword):
                continue

        seen.add(url)
        results.append(
            {
                "title": title or url,
                "url": url,
                "domain": clean_domain(url),
                "source_type": "duckduckgo_html",
            }
        )

        if len(results) >= max_results:
            break

    return results


def discover_urls(keyword: str, max_results: int = 15) -> list[dict]:
    results = []

    try:
        bing_results = discover_with_bing_rss(keyword, max_results=max_results)
        log_debug(f"Bing RSS returned {len(bing_results)} results for '{keyword}'.")
        results.extend(bing_results)
    except Exception as e:
        log_debug(f"Bing RSS failed for '{keyword}': {e}")

    if len(results) < max_results:
        try:
            ddg_results = discover_with_duckduckgo(keyword, max_results=max_results)
            log_debug(f"DuckDuckGo returned {len(ddg_results)} results for '{keyword}'.")
            results.extend(ddg_results)
        except Exception as e:
            log_debug(f"DuckDuckGo failed for '{keyword}': {e}")

    deduped = []
    seen = set()

    for item in results:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        deduped.append(item)

    return deduped[:max_results]


def score_link_candidate(base_url: str, full_url: str, anchor_text: str)