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


def log_debug(message: str) -> None:
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


def score_link_candidate(base_url: str, full_url: str, anchor_text: str) -> int:
    score = 0
    url_lower = full_url.lower()
    text_lower = (anchor_text or "").lower()

    if clean_domain(full_url) != clean_domain(base_url):
        return -999

    if any(bad in url_lower for bad in BAD_LINK_HINTS):
        return -50

    if any(hint in url_lower for hint in THREAD_HINTS):
        score += 6

    if any(hint in text_lower for hint in ["thread", "discussion", "forum", "post", "topic", "review", "question"]):
        score += 4

    if re.search(r"/\d{4}/|\d{2,}", url_lower):
        score += 2

    if len(anchor_text or "") > 20:
        score += 1

    if url_lower.rstrip("/") == base_url.lower().rstrip("/"):
        score -= 3

    return score


def parse_html_links(base_url: str, html: str, max_links: int = 25) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith(("javascript:", "mailto:", "#")):
            continue

        full = urljoin(base_url, href)
        if full in seen:
            continue
        seen.add(full)

        text = clean_text(a.get_text(" ", strip=True))
        score = score_link_candidate(base_url, full, text)

        if score > 0:
            candidates.append((score, full))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [url for _, url in candidates[:max_links]]


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


def build_signal_rows(sentences: list[str], url: str, title: str, keyword: str, domain: str) -> list[dict]:
    rows = []

    for sentence in sentences:
        flags = classify_sentence(sentence)

        if flags["buying_signal"]:
            rows.append(
                {
                    "signal_type": "Buying Signal",
                    "keyword": keyword,
                    "domain": domain,
                    "title": title,
                    "text": sentence,
                    "url": url,
                }
            )

        if flags["pain_point"]:
            rows.append(
                {
                    "signal_type": "Pain Point",
                    "keyword": keyword,
                    "domain": domain,
                    "title": title,
                    "text": sentence,
                    "url": url,
                }
            )

        if flags["question"]:
            rows.append(
                {
                    "signal_type": "Question",
                    "keyword": keyword,
                    "domain": domain,
                    "title": title,
                    "text": sentence,
                    "url": url,
                }
            )

    return rows


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


def parse_xml_feed(xml_text: str) -> tuple[str, str]:
    root = ET.fromstring(xml_text)

    feed_title = ""
    texts = []

    channel_title = root.findtext(".//channel/title")
    if channel_title:
        feed_title = clean_text(channel_title)

    if not feed_title:
        atom_title = root.findtext(".//{http://www.w3.org/2005/Atom}title")
        if atom_title:
            feed_title = clean_text(atom_title)

    for item in root.findall(".//item"):
        t = clean_text(item.findtext("title", default=""))
        d = clean_text(item.findtext("description", default=""))
        if t or d:
            texts.append(f"{t} {d}".strip())

    atom_ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.findall(f".//{atom_ns}entry"):
        t = clean_text(entry.findtext(f"{atom_ns}title", default=""))
        summary = clean_text(entry.findtext(f"{atom_ns}summary", default=""))
        content = clean_text(entry.findtext(f"{atom_ns}content", default=""))
        if t or summary or content:
            texts.append(f"{t} {summary} {content}".strip())

    return feed_title, " ".join(texts).strip()


def scrape_single_page(url: str, keyword: str) -> dict:
    try:
        request_url = url

        if is_reddit_url(url) and "/comments/" in url and not url.rstrip("/").endswith(".rss"):
            request_url = reddit_rss_url(url)
            log_debug(f"Converted Reddit thread to RSS: {request_url}")

        resp = fetch_response(request_url)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "").lower()

        if "xml" in content_type or "rss" in content_type or "atom" in content_type:
            try:
                feed_title, text = parse_xml_feed(resp.text)
                title = feed_title or request_url
                word_count = len(text.split()) if text else 0

                if not text:
                    return {
                        "url": url,
                        "title": title,
                        "keyword": keyword,
                        "domain": clean_domain(url),
                        "mentions": 0,
                        "pain_points": 0,
                        "buying_signals": 0,
                        "questions": 0,
                        "demand_score": 0,
                        "snippet": "",
                        "status": "rss empty",
                        "word_count": 0,
                        "signal_rows": [],
                    }

                if word_count < 40:
                    return {
                        "url": url,
                        "title": title,
                        "keyword": keyword,
                        "domain": clean_domain(url),
                        "mentions": 0,
                        "pain_points": 0,
                        "buying_signals": 0,
                        "questions": 0,
                        "demand_score": 0,
                        "snippet": text[:250],
                        "status": "rss too little content",
                        "word_count": word_count,
                        "signal_rows": [],
                    }

                kw = keyword.lower().strip()
                mentions = text.lower().count(kw) if kw else 0
                snippet = extract_snippet(text, keyword)

                sentences = split_sentences(text)
                classified = [classify_sentence(s) for s in sentences]

                pain_count = sum(1 for c in classified if c["pain_point"])
                buying_count = sum(1 for c in classified if c["buying_signal"])
                question_count = sum(1 for c in classified if c["question"])

                demand_score = score_demand(mentions, pain_count, buying_count, question_count)
                signal_rows = build_signal_rows(sentences, url, title, keyword, clean_domain(url))

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
                    "word_count": word_count,
                    "signal_rows": signal_rows,
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
                    "status": f"rss parse error: {e}",
                    "word_count": 0,
                    "signal_rows": [],
                }

        if "text/html" not in content_type:
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
                "status": f"non-html content: {content_type or 'unknown'}",
                "word_count": 0,
                "signal_rows": [],
            }

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "noscript", "svg", "img"]):
            tag.decompose()

        title = extract_page_title(soup, url)
        text = clean_text(soup.get_text(" ", strip=True))
        word_count = len(text.split()) if text else 0
        lower_text = text.lower() if text else ""

        for signal in BLOCKED_PAGE_SIGNALS:
            if signal in lower_text:
                return {
                    "url": url,
                    "title": title,
                    "keyword": keyword,
                    "domain": clean_domain(url),
                    "mentions": 0,
                    "pain_points": 0,
                    "buying_signals": 0,
                    "questions": 0,
                    "demand_score": 0,
                    "snippet": text[:250] if text else "",
                    "status": f"blocked page: {signal}",
                    "word_count": word_count,
                    "signal_rows": [],
                }

        if not text:
            return {
                "url": url,
                "title": title,
                "keyword": keyword,
                "domain": clean_domain(url),
                "mentions": 0,
                "pain_points": 0,
                "buying_signals": 0,
                "questions": 0,
                "demand_score": 0,
                "snippet": "",
                "status": "empty page text",
                "word_count": 0,
                "signal_rows": [],
            }

        if word_count < 80:
            return {
                "url": url,
                "title": title,
                "keyword": keyword,
                "domain": clean_domain(url),
                "mentions": 0,
                "pain_points": 0,
                "buying_signals": 0,
                "questions": 0,
                "demand_score": 0,
                "snippet": text[:250],
                "status": "not enough readable text",
                "word_count": word_count,
                "signal_rows": [],
            }

        kw = keyword.lower().strip()
        mentions = text.lower().count(kw) if kw else 0
        snippet = extract_snippet(text, keyword)

        sentences = split_sentences(text)
        classified = [classify_sentence(s) for s in sentences]

        pain_count = sum(1 for c in classified if c["pain_point"])
        buying_count = sum(1 for c in classified if c["buying_signal"])
        question_count = sum(1 for c in classified if c["question"])

        demand_score = score_demand(mentions, pain_count, buying_count, question_count)
        signal_rows = build_signal_rows(sentences, url, title, keyword, clean_domain(url))

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
            "word_count": word_count,
            "signal_rows": signal_rows,
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
            "signal_rows": [],
        }


def crawl_seed_url(seed_url: str, keyword: str, pages_per_site: int = 4, pause_seconds: float = 0.5) -> list[dict]:
    results = []

    try:
        if is_reddit_url(seed_url) and "/comments/" in seed_url:
            first_row = scrape_single_page(seed_url, keyword)
            return [first_row]

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
            "signal_rows": [],
        }]

    visited = set()
    queue = [seed_url] + parse_html_links(seed_url, seed_html, max_links=pages_per_site * 4)

    for url in queue:
        if len(results) >= pages_per_site:
            break
        if url in visited:
            continue

        visited.add(url)
        row = scrape_single_page(url, keyword)
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


def flatten_signal_rows(rows: list[dict]) -> list[dict]:
    flattened = []
    for row in rows:
        signal_rows = row.get("signal_rows", [])
        if signal_rows:
            flattened.extend(signal_rows)
    return flattened


def display_signal_section(section_title: str, section_key: str, df: pd.DataFrame) -> None:
    st.markdown(f"### {section_title}")

    if df.empty:
        st.info(f"No {section_title.lower()} found.")
        return

    display_df = df.copy().reset_index(drop=True)
    display_df.insert(0, "row_id", display_df.index + 1)

    table_df = display_df[["row_id", "keyword", "domain", "title", "text", "url"]].copy()
    st.dataframe(table_df, use_container_width=True, hide_index=True)

    detail_options = {
        f"{row.row_id} | {row.keyword} | {row.domain} | {str(row.title)[:80]}": int(row.row_id)
        for row in table_df.itertuples(index=False)
    }

    selected_label = st.selectbox(
        f"View {section_title.lower()} detail",
        options=list(detail_options.keys()),
        key=f"{section_key}_detail_select",
    )

    selected_row_id = detail_options[selected_label]
    detail_row = display_df[display_df["row_id"] == selected_row_id].iloc[0]

    st.markdown("#### Detail")
    st.write(f"**Keyword:** {detail_row['keyword']}")
    st.write(f"**Domain:** {detail_row['domain']}")
    st.write(f"**Title:** {detail_row['title']}")
    st.write(f"**URL:** {detail_row['url']}")
    st.markdown("**Signal text:**")
    st.code(detail_row["text"], language=None)


st.title("Demand Finder")
st.write("Find where demand is showing up: questions, pain points, and buying signals.")

with st.sidebar:
    st.header("Settings")
    max_discovery = st.slider("Max discovered URLs per keyword", 5, 30, 12)
    pages_per_site = st.slider("Pages to scrape per site", 1, 10, 4)
    pause_seconds = st.slider("Pause between page requests", 0.0, 2.0, 0.5, 0.1)
    auto_discover = st.checkbox("Auto-discover URLs from keywords", value=True)
    show_debug = st.checkbox("Show debug panel", value=True)
    show_status_table = st.checkbox("Show scrape status table", value=True)

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
    st.session_state.signal_rows = []
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
        st.session_state.signal_rows = flatten_signal_rows(raw_rows)
else:
    st.info("No URLs found yet. Run discovery or add manual URLs.")

if st.session_state.dashboard_rows:
    df = pd.DataFrame(st.session_state.dashboard_rows)

    st.subheader("Demand Dashboard")

    if show_status_table:
        st.markdown("### Scrape Status")
        status_view = df[[
            "keyword", "domain", "title", "status", "word_count", "url"
        ]].sort_values(["status", "word_count"], ascending=[True, False])
        st.dataframe(status_view, use_container_width=True, hide_index=True)

    ok_df = df[df["status"] == "ok"].copy()

    if ok_df.empty:
        st.warning("No readable discussion pages were found. Check the Scrape Status table above.")
    else:
        signal_df = (
            pd.DataFrame(st.session_state.signal_rows)
            if st.session_state.signal_rows
            else pd.DataFrame(columns=["signal_type", "keyword", "domain", "title", "text", "url"])
        )

        buying_signal_df = signal_df[signal_df["signal_type"] == "Buying Signal"].copy() if not signal_df.empty else signal_df
        pain_point_df = signal_df[signal_df["signal_type"] == "Pain Point"].copy() if not signal_df.empty else signal_df
        question_df = signal_df[signal_df["signal_type"] == "Question"].copy() if not signal_df.empty else signal_df

        metric1, metric2, metric3, metric4 = st.columns(4)
        metric1.metric("Pages analyzed", len(ok_df))
        metric2.metric("Buying signals", len(buying_signal_df))
        metric3.metric("Pain points", len(pain_point_df))
        metric4.metric("Questions", len(question_df))

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

        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            ["Opportunities", "Signals", "Domains", "Keywords", "Raw Mentions"]
        )

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
            st.markdown("### Signal Explorer")

            s1, s2, s3 = st.columns(3)
            with s1:
                st.markdown(f"**Buying Signals:** {len(buying_signal_df)}")
            with s2:
                st.markdown(f"**Pain Points:** {len(pain_point_df)}")
            with s3:
                st.markdown(f"**Questions:** {len(question_df)}")

            signal_type_choice = st.radio(
                "Choose a signal type to inspect",
                options=["Buying Signals", "Pain Points", "Questions"],
                horizontal=True,
            )

            if signal_type_choice == "Buying Signals":
                display_signal_section("Buying Signals", "buying", buying_signal_df)
            elif signal_type_choice == "Pain Points":
                display_signal_section("Pain Points", "pain", pain_point_df)
            else:
                display_signal_section("Questions", "question", question_df)

        with tab3:
            st.dataframe(domain_rollup, use_container_width=True, hide_index=True)

        with tab4:
            st.dataframe(keyword_rollup, use_container_width=True, hide_index=True)

        with tab5:
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