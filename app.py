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

DEFAULT_KEYWORDS = [
    "Ford Maverick",
    "RAM RHO",
    "Tacoma intercooler",
]

for key, default in {
    "discovered_urls": [],
    "raw_mentions": [],
    "dashboard_rows": [],
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


def fetch_url(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
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
    """
    Looser filter than before.
    """
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

    # was too strict before
    return matches >= 1


def discover_with_bing_rss(keyword: str, max_results: int = 15) -> list[dict]:
    """
    Uses Bing's RSS result format, which is easier to parse than scraping HTML SERPs.
    """
    query = f"{keyword} forum OR discussion OR community OR club OR blog"
    rss_url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}"

    results = []
    seen = set()

    resp = requests.get(rss_url, headers=HEADERS, timeout=20)
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

    # Try multiple selectors
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

        # Only apply relevance if we actually have a title or meaningful URL
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
    """
    Try Bing RSS first, then DDG fallback.
    """
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


def parse_html_links(base_url: str, html: str, max_links: int = 25) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    base_domain = clean_domain(base_url)

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith(("javascript:", "mailto:", "#")):
            continue

        full = urljoin(base_url, href)
        if clean_domain(full) != base_domain:
            continue
        if full in seen:
            continue

        text = clean_text(a.get_text(" ", strip=True)).lower()

        good = any(
            token in full.lower() or token in text
            for token in [
                "thread", "forum", "discussion", "topic", "post", "article",
                "blog", "review", "questions", "faq", "community"
            ]
        )

        # Also allow general internal links if we're not getting enough
        if good or len(links) < 8:
            seen.add(full)
            links.append(full)

        if len(links) >= max_links:
            break

    return links


def extract_page_title(soup: BeautifulSoup, fallback: str) -> str:
    if soup.title:
        return clean_text(soup.title.get_text(" ", strip=True))
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))
    return fallback


def extract_snippet(text: str, keyword: str, radius: int = 180) -> str:
    lower_text = text.lower()
    lower_kw = keyword.lower().strip()
    if lower_kw and lower_kw in lower_text:
        idx = lower_text.find(lower_kw)
        start = max(0, idx - radius)
        end = min(len(text), idx + len(keyword) + radius)
        return text[start:end].strip()
    return text[:400].strip()


def split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[\.\?\!])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def classify_sentence(sentence: str) -> dict:
    s = sentence.lower()

    pain = any(re.search(p, s) for p in PAIN_POINT_PATTERNS)
    buying = any(re.search(p, s) for p in BUYING_SIGNAL_PATTERNS)
    question = any(re.search(p, s) for p in QUESTION_PATTERNS) or s.endswith("?")

    return {
        "pain_point": pain,
        "buying_signal": buying,
        "question": question,
    }


def tokenize_topics(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9\+\-]{3,}", text.lower())
    return [w for w in words if w not in STOPWORDS and not w.isdigit()]


def top_topics_from_mentions(mentions: list[dict], n: int = 15) -> list[tuple[str, int]]:
    counter = Counter()
    for m in mentions:
        counter.update(tokenize_topics(m.get("title", "")))
        counter.update(tokenize_topics(m.get("snippet", "")))
    return counter.most_common(n)


def score_demand(mention_count: int, pain_count: int, buying_count: int, question_count: int) -> int:
    return int((mention_count * 1) + (pain_count * 3) + (buying_count * 4) + (question_count * 2))


def scrape_single_page(url: str, keyword: str) -> dict | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "img"]):
            tag.decompose()

        title = extract_page_title(soup, url)
        text = clean_text(soup.get_text(" ", strip=True))
        if not text:
            return None

        kw = keyword.lower().strip()
        mentions = text.lower().count(kw) if kw else 0
        snippet = extract_snippet(text, keyword)

        sentences = split_sentences(text)
        classified = [classify_sentence(s) for s in sentences]

        pain_count = sum(1 for c in classified if c["pain_point"])
        buying_count = sum(1 for c in classified if c["buying_signal"])
        question_count = sum(1 for c in classified if c["question"])

        demand_score = score_demand(mentions, pain_count, buying_count, question_count)

        return {
            "url": url,
            "title": title,
            "keyword": keyword,
            "domain": clean_domain(url),
            "mentions": mentions,
            "pain_points": pain_count,
            "buying_signals": buying_count,
            "questions": question_count,
            "demand_score": demand_score,
            "snippet": snippet,
            "status": "ok",
            "word_count": len(text.split()),
        }

    except Exception as e:
        return {
            "url": url,
            "title": url,
            "keyword": keyword,
            "domain": clean_domain(url),
            "mentions": 0,
            "pain_points": 0,
            "buying_signals": 0,
            "questions": 0,
            "demand_score": 0,
            "snippet": "",
            "status": f"error: {e}",
            "word_count": 0,
        }


def crawl_seed_url(seed_url: str, keyword: str, pages_per_site: int = 4, pause_seconds: float = 0.5) -> list[dict]:
    results = []

    try:
        seed_html = fetch_url(seed_url)
    except Exception as e:
        return [{
            "url": seed_url,
            "title": seed_url,
            "keyword": keyword,
            "domain": clean_domain(seed_url),
            "mentions": 0,
            "pain_points": 0,
            "buying_signals": 0,
            "questions": 0,
            "demand_score": 0,
            "snippet": "",
            "status": f"error: {e}",
            "word_count": 0,
        }]

    visited = set()
    queue = [seed_url] + parse_html_links(seed_url, seed_html, max_links=pages_per_site * 3)

    for url in queue:
        if len(results) >= pages_per_site:
            break
        if url in visited:
            continue

        visited.add(url)
        row = scrape_single_page(url, keyword)
        if row:
            results.append(row)

        time.sleep(pause_seconds)

    return results


def summarize_opportunities(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []

    insights = []

    high_buying = df[df["buying_signals"] > 0].sort_values("buying_signals", ascending=False)
    if not high_buying.empty:
        top = high_buying.iloc[0]
        insights.append(
            f"Strongest buying intent is on {top['domain']} around '{top['keyword']}' with {int(top['buying_signals'])} buying-signal hits."
        )

    high_pain = df[df["pain_points"] > 0].sort_values("pain_points", ascending=False)
    if not high_pain.empty:
        top = high_pain.iloc[0]
        insights.append(
            f"Biggest pain-point signal is on {top['domain']} where discussion around '{top['keyword']}' is showing {int(top['pain_points'])} friction indicators."
        )

    high_questions = df[df["questions"] > 0].sort_values("questions", ascending=False)
    if not high_questions.empty:
        top = high_questions.iloc[0]
        insights.append(
            f"The best content opportunity is likely FAQ or comparison content, with {int(top['questions'])} question-style signals on {top['domain']}."
        )

    best = df.sort_values("demand_score", ascending=False).head(3)
    if not best.empty:
        domains = ", ".join(best["domain"].dropna().astype(str).head(3).tolist())
        insights.append(f"Highest-priority domains to monitor next: {domains}.")

    return insights


st.title("Demand Finder")
st.write("Find where demand is showing up: questions, pain points, and buying signals.")

with st.sidebar:
    st.header("Settings")
    max_discovery = st.slider("Max discovered URLs per keyword", 5, 30, 12)
    pages_per_site = st.slider("Pages to scrape per site", 1, 10, 4)
    pause_seconds = st.slider("Pause between page requests", 0.0, 2.0, 0.5, 0.1)
    auto_discover = st.checkbox("Auto-discover URLs from keywords", value=True)
    show_debug = st.checkbox("Show debug panel", value=True)

col1, col2 = st.columns([1.2, 1])

with col1:
    keyword_text = st.text_area(
        "Keywords to track",
        value="\n".join(DEFAULT_KEYWORDS),
        height=160,
        help="One keyword or market phrase per line.",
    )

with col2:
    manual_url_text = st.text_area(
        "Optional URLs to include",
        value="",
        height=160,
        help="Add forums, sites, or communities you already know.",
    )

keywords = [k.strip() for k in keyword_text.splitlines() if k.strip()]
manual_urls = [normalize_url(u.strip()) for u in manual_url_text.splitlines() if u.strip()]

if st.button("Find Demand", use_container_width=True):
    st.session_state.discovered_urls = []
    st.session_state.raw_mentions = []
    st.session_state.dashboard_rows = []
    st.session_state.search_error = ""
    st.session_state.debug_messages = []

    all_targets = []

    with st.spinner("Finding relevant websites and discussion pages..."):
        try:
            for kw in keywords:
                if auto_discover:
                    discovered = discover_urls(kw, max_results=max_discovery)
                    for item in discovered:
                        item["keyword"] = kw
                    all_targets.extend(discovered)

            for url in manual_urls:
                if url:
                    all_targets.append(
                        {
                            "title": url,
                            "url": url,
                            "domain": clean_domain(url),
                            "source_type": "manual",
                            "keyword": "manual",
                        }
                    )

            deduped = []
            seen = set()
            for item in all_targets:
                key = (item["url"], item.get("keyword", ""))
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)

            st.session_state.discovered_urls = deduped
            log_debug(f"Total deduped discovered URLs: {len(deduped)}")

        except Exception as e:
            st.session_state.search_error = f"Discovery failed: {e}"

if st.session_state.search_error:
    st.error(st.session_state.search_error)

if show_debug and st.session_state.debug_messages:
    with st.expander("Debug"):
        for msg in st.session_state.debug_messages:
            st.write(f"- {msg}")

if st.session_state.discovered_urls:
    st.subheader("Discovered Targets")

    discovered_df = pd.DataFrame(st.session_state.discovered_urls)
    st.dataframe(
        discovered_df[["keyword", "domain", "title", "url", "source_type"]],
        use_container_width=True,
        hide_index=True,
    )

    options = [f"{item['keyword']} | {item['url']}" for item in st.session_state.discovered_urls]
    option_map = {f"{item['keyword']} | {item['url']}": item for item in st.session_state.discovered_urls}

    selected = st.multiselect(
        "Choose targets to scrape",
        options=options,
        default=options[: min(8, len(options))],
    )

    if st.button("Scrape and Analyze", use_container_width=True):
        raw_rows = []

        with st.spinner("Scraping pages and scoring demand..."):
            for key in selected:
                item = option_map[key]
                site_results = crawl_seed_url(
                    seed_url=item["url"],
                    keyword=item["keyword"],
                    pages_per_site=pages_per_site,
                    pause_seconds=pause_seconds,
                )
                raw_rows.extend(site_results)

        st.session_state.raw_mentions = raw_rows
        st.session_state.dashboard_rows = raw_rows
else:
    st.info("No URLs found yet. Run discovery or add manual URLs.")

if st.session_state.dashboard_rows:
    df = pd.DataFrame(st.session_state.dashboard_rows)
    ok_df = df[df["status"] == "ok"].copy()

    st.subheader("Demand Dashboard")

    if ok_df.empty:
        st.warning("Pages were scraped, but none returned readable content.")
    else:
        metric1, metric2, metric3, metric4 = st.columns(4)
        metric1.metric("Pages analyzed", len(ok_df))
        metric2.metric("Buying signals", int(ok_df["buying_signals"].sum()))
        metric3.metric("Pain points", int(ok_df["pain_points"].sum()))
        metric4.metric("Questions", int(ok_df["questions"].sum()))

        domain_rollup = (
            ok_df.groupby("domain", dropna=False)
            .agg(
                pages=("url", "count"),
                mentions=("mentions", "sum"),
                pain_points=("pain_points", "sum"),
                buying_signals=("buying_signals", "sum"),
                questions=("questions", "sum"),
                demand_score=("demand_score", "sum"),
            )
            .reset_index()
            .sort_values("demand_score", ascending=False)
        )

        keyword_rollup = (
            ok_df.groupby("keyword", dropna=False)
            .agg(
                pages=("url", "count"),
                mentions=("mentions", "sum"),
                pain_points=("pain_points", "sum"),
                buying_signals=("buying_signals", "sum"),
                questions=("questions", "sum"),
                demand_score=("demand_score", "sum"),
            )
            .reset_index()
            .sort_values("demand_score", ascending=False)
        )

        topic_df = pd.DataFrame(
            top_topics_from_mentions(st.session_state.raw_mentions, n=20),
            columns=["topic", "count"]
        )

        tab1, tab2, tab3, tab4 = st.tabs(["Opportunities", "Domains", "Keywords", "Raw Mentions"])

        with tab1:
            for insight in summarize_opportunities(ok_df):
                st.write(f"- {insight}")

            st.markdown("### Top topics")
            st.dataframe(topic_df, use_container_width=True, hide_index=True)

            st.markdown("### Highest-demand pages")
            top_pages = ok_df.sort_values("demand_score", ascending=False)[[
                "keyword", "domain", "title", "mentions",
                "pain_points", "buying_signals", "questions", "demand_score", "url"
            ]].head(20)
            st.dataframe(top_pages, use_container_width=True, hide_index=True)

        with tab2:
            st.dataframe(domain_rollup, use_container_width=True, hide_index=True)

        with tab3:
            st.dataframe(keyword_rollup, use_container_width=True, hide_index=True)

        with tab4:
            raw_view = ok_df[[
                "keyword", "domain", "title", "mentions",
                "pain_points", "buying_signals", "questions",
                "demand_score", "snippet", "url"
            ]].sort_values("demand_score", ascending=False)
            st.dataframe(raw_view, use_container_width=True, hide_index=True)

        csv = ok_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV",
            data=csv,
            file_name="demand_finder_results.csv",
            mime="text/csv",
        )