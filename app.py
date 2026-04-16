import re
import time
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

# ----------------------------
# Config
# ----------------------------

st.set_page_config(page_title="Keyword URL Finder + Scraper", layout="wide")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

BLOCKED_DOMAINS = {
    "google.com",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "linkedin.com",
    "pinterest.com",
    "reddit.com",
    "amazon.com",
    "ebay.com",
}

# ----------------------------
# Helpers
# ----------------------------

def normalize_url(url: str) -> str:
    url = url.strip()
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
    host = clean_domain(url)
    if not host:
        return False

    for blocked in BLOCKED_DOMAINS:
        if host == blocked or host.endswith("." + blocked):
            return False
    return True


def looks_relevant(url: str, title: str, keyword: str) -> bool:
    blob = f"{url} {title}".lower()
    keyword = keyword.lower().strip()

    if keyword in blob:
        return True

    parts = [p for p in re.split(r"[\s\-_\/]+", keyword) if p]
    matches = sum(1 for p in parts if p in blob)

    return matches >= 1


def extract_real_url(href: str) -> str:
    """
    Handle DuckDuckGo result links.
    """
    if not href:
        return ""

    href = href.strip()

    # direct URL
    if href.startswith("http://") or href.startswith("https://"):
        return href

    return href


def search_duckduckgo(keyword: str, max_results: int = 15):
    query = f"{keyword} forum OR board OR discussion OR club OR blog OR community"
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}

    response = requests.get(url, params=params, headers=HEADERS, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    results = []
    seen = set()

    for result in soup.select(".result"):
        link_tag = result.select_one(".result__a")
        if not link_tag:
            continue

        href = link_tag.get("href", "").strip()
        title = link_tag.get_text(" ", strip=True)

        real_url = extract_real_url(href)
        real_url = normalize_url(real_url)

        if not real_url:
            continue
        if real_url in seen:
            continue
        if not domain_allowed(real_url):
            continue
        if not looks_relevant(real_url, title, keyword):
            continue

        seen.add(real_url)
        results.append(
            {
                "title": title or real_url,
                "url": real_url,
                "domain": clean_domain(real_url),
            }
        )

        if len(results) >= max_results:
            break

    return results


def get_page_text(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "img"]):
        tag.decompose()

    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text


def build_snippet(text: str, keyword: str, radius: int = 180) -> str:
    if not text:
        return ""

    lower_text = text.lower()
    lower_keyword = keyword.lower().strip()

    idx = lower_text.find(lower_keyword)
    if idx == -1:
        return text[:400].strip()

    start = max(0, idx - radius)
    end = min(len(text), idx + len(keyword) + radius)
    return text[start:end].strip()


def scrape_url(url: str, keyword: str):
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        page_title = soup.title.get_text(" ", strip=True) if soup.title else url

        for tag in soup(["script", "style", "noscript", "svg", "img"]):
            tag.decompose()

        text = soup.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)

        keyword_clean = keyword.lower().strip()
        mention_count = text.lower().count(keyword_clean) if keyword_clean else 0
        snippet = build_snippet(text, keyword)

        return {
            "url": url,
            "title": page_title,
            "mentions": mention_count,
            "snippet": snippet,
            "word_count": len(text.split()),
            "status": "ok",
        }

    except Exception as e:
        return {
            "url": url,
            "title": url,
            "mentions": 0,
            "snippet": "",
            "word_count": 0,
            "status": f"error: {e}",
        }


# ----------------------------
# Session State
# ----------------------------

if "discovered_urls" not in st.session_state:
    st.session_state.discovered_urls = []

if "scrape_results" not in st.session_state:
    st.session_state.scrape_results = []

if "search_error" not in st.session_state:
    st.session_state.search_error = ""

# ----------------------------
# UI
# ----------------------------

st.title("Keyword URL Finder + Scraper")
st.write("Enter a keyword, find matching URLs, then scrape selected pages to see mentions and snippets.")

keyword = st.text_input(
    "Keyword",
    placeholder="Ford Maverick, Ram RHO, Tacoma intercooler, ceramic coating, etc."
)

max_results = st.slider("Number of URLs to find", min_value=5, max_value=30, value=15)

col1, col2 = st.columns(2)

with col1:
    if st.button("Find Matching URLs", use_container_width=True):
        st.session_state.discovered_urls = []
        st.session_state.scrape_results = []
        st.session_state.search_error = ""

        if not keyword.strip():
            st.session_state.search_error = "Please enter a keyword first."
        else:
            with st.spinner("Searching for matching URLs..."):
                try:
                    results = search_duckduckgo(keyword, max_results=max_results)
                    st.session_state.discovered_urls = results

                    if not results:
                        st.session_state.search_error = (
                            "No matching URLs found. Try a broader keyword."
                        )
                except Exception as e:
                    st.session_state.search_error = f"Search failed: {e}"

with col2:
    if st.button("Clear Results", use_container_width=True):
        st.session_state.discovered_urls = []
        st.session_state.scrape_results = []
        st.session_state.search_error = ""

if st.session_state.search_error:
    st.warning(st.session_state.search_error)

# ----------------------------
# Show discovered URLs
# ----------------------------

if st.session_state.discovered_urls:
    st.subheader("Discovered URLs")

    options = [item["url"] for item in st.session_state.discovered_urls]
    labels = {
        item["url"]: f'{item["title"]} ({item["domain"]})'
        for item in st.session_state.discovered_urls
    }

    default_selection = options[:5] if len(options) >= 5 else options

    selected_urls = st.multiselect(
        "Choose URLs to scrape",
        options=options,
        default=default_selection,
        format_func=lambda x: labels.get(x, x),
        key="selected_urls",
    )

    with st.expander("See all found URLs"):
        for item in st.session_state.discovered_urls:
            st.write(f"- {item['title']}")
            st.write(item["url"])

    if st.button("Scrape Selected URLs", use_container_width=True):
        if not selected_urls:
            st.warning("Select at least one URL to scrape.")
        else:
            results = []
            progress = st.progress(0)

            with st.spinner("Scraping selected URLs..."):
                total = len(selected_urls)

                for i, url in enumerate(selected_urls, start=1):
                    results.append(scrape_url(url, keyword))
                    progress.progress(i / total)
                    time.sleep(1)

            st.session_state.scrape_results = results

# ----------------------------
# Show scrape results
# ----------------------------

if st.session_state.scrape_results:
    st.subheader("Scrape Results")

    sorted_results = sorted(
        st.session_state.scrape_results,
        key=lambda x: (x["status"] != "ok", -x["mentions"]),
    )

    for item in sorted_results:
        st.markdown(f"### {item['title']}")
        st.write(item["url"])
        st.write(f"**Status:** {item['status']}")
        st.write(f"**Mentions:** {item['mentions']}")
        st.write(f"**Word Count:** {item['word_count']}")

        if item["snippet"]:
            st.caption(item["snippet"])

        st.divider()