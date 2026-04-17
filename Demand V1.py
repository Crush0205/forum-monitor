import streamlit as st
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, urlunparse
from bs4 import BeautifulSoup

DEFAULT_URLS = [
    "https://www.reddit.com/r/FordMaverickTruck/search/?q=intercooler",
    "https://www.reddit.com/r/FordMaverickTruck/new/",
    "https://www.reddit.com/r/FordMaverickTruckMods/new/",
    "https://www.mavericktruckclub.com/forum/",
    "https://www.maverickchat.com/forums/2022-ford-maverick-general-discussion-forum.8/",
]

DEFAULT_KEYWORDS = [
    "radiator",
    "intercooler",
    "transmission cooler",
    "oil cooler",
    "cooling",
    "overheating",
    "mishimoto",
    "recommend",
    "problem",
    "issue",
]

USER_AGENT = "web:forum-monitor:v1.0 (by /u/your_reddit_username)"


st.set_page_config(page_title="Forum Monitor", layout="wide")
st.title("Forum Monitor")
st.write("Add Reddit URLs, RSS feeds, or forum URLs, then scan for keyword matches.")


url_text = st.text_area(
    "URLs to check (one per line)",
    value="\n".join(DEFAULT_URLS),
    height=200,
)

keyword_text = st.text_area(
    "Keywords to look for (one per line)",
    value="\n".join(DEFAULT_KEYWORDS),
    height=180,
)


def label_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}"


def match_keyword(text: str, keywords: list[str]) -> str | None:
    text = (text or "").lower()
    for kw in keywords:
        kw = kw.strip().lower()
        if kw and kw in text:
            return kw
    return None


def is_reddit_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return "reddit.com" in netloc or "redd.it" in netloc


def to_reddit_rss_url(url: str) -> str:
    """
    Convert common Reddit URLs into RSS equivalents when possible.

    Examples:
    - /r/FordMaverickTruck/new/ -> /r/FordMaverickTruck/new/.rss
    - /r/FordMaverickTruck/search/?q=intercooler -> /r/FordMaverickTruck/search.rss?q=intercooler
    - /r/FordMaverickTruck/new.json?limit=50 -> /r/FordMaverickTruck/new/.rss
    """
    parsed = urlparse(url)
    netloc = parsed.netloc or "www.reddit.com"
    path = parsed.path or "/"
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = dict(query_pairs)

    if parsed.scheme not in ("http", "https"):
        return url

    if "reddit.com" not in netloc.lower():
        return url

    # Already RSS
    if path.endswith(".rss") or "/.rss" in path or "/rss" in path:
        return url

    clean_path = path.rstrip("/")

    # Search pages
    # /r/sub/search or /search
    if clean_path.endswith("/search"):
        rss_path = clean_path[:-7] + "/search.rss"

        # Helpful defaults for subreddit search if user pasted browser URL
        if "restrict_sr" not in query and "/r/" in clean_path:
            query["restrict_sr"] = "1"
        if "sort" not in query:
            query["sort"] = "new"

        return urlunparse(
            (
                "https",
                "www.reddit.com",
                rss_path,
                "",
                urlencode(query, doseq=True),
                "",
            )
        )

    # .json listing endpoints -> RSS listing
    if clean_path.endswith(".json"):
        clean_path = clean_path[:-5]

    # Common Reddit listing paths
    listing_endings = [
        "/new",
        "/hot",
        "/top",
        "/rising",
        "/controversial",
    ]

    for ending in listing_endings:
        if clean_path.endswith(ending):
            rss_path = clean_path + "/.rss"
            return urlunparse(
                (
                    "https",
                    "www.reddit.com",
                    rss_path,
                    "",
                    urlencode(query, doseq=True),
                    "",
                )
            )

    # Plain subreddit URL -> default to new feed
    parts = [p for p in clean_path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "r":
        subreddit = parts[1]
        rss_path = f"/r/{subreddit}/new/.rss"
        return urlunparse(
            (
                "https",
                "www.reddit.com",
                rss_path,
                "",
                urlencode(query, doseq=True),
                "",
            )
        )

    # Fallback to original
    return url


def fetch_url(url: str) -> tuple[str, str]:
    final_url = to_reddit_rss_url(url) if is_reddit_url(url) else url
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(final_url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text, final_url


def parse_rss(xml_text: str) -> list[dict]:
    items = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # RSS
    for item in root.findall(".//item"):
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        description = item.findtext("description", default="")
        items.append(
            {
                "title": title,
                "link": link,
                "body": description,
            }
        )

    # Atom fallback
    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", default="", namespaces=ns)
            content = entry.findtext("atom:content", default="", namespaces=ns)
            summary = entry.findtext("atom:summary", default="", namespaces=ns)

            link = ""
            for link_el in entry.findall("atom:link", ns):
                href = link_el.attrib.get("href", "")
                if href:
                    link = href
                    break

            items.append(
                {
                    "title": title,
                    "link": link,
                    "body": content or summary,
                }
            )

    return items


def parse_html(base_url: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen_links = set()

    for link in soup.find_all("a", href=True):
        title = link.get_text(" ", strip=True)
        href = link.get("href", "").strip()

        if not title or not href:
            continue

        full_link = urljoin(base_url, href)

        # Skip junk links
        bad_starts = ("javascript:", "mailto:", "#")
        if href.startswith(bad_starts):
            continue

        # Keep links on same site only
        if urlparse(full_link).netloc != urlparse(base_url).netloc:
            continue

        # Skip obvious navigation/account links
        lower_title = title.lower()
        if any(
            junk in lower_title
            for junk in [
                "log in",
                "register",
                "menu",
                "search",
                "home",
                "forums",
                "new posts",
                "members",
                "latest",
            ]
        ):
            continue

        if full_link in seen_links:
            continue

        seen_links.add(full_link)

        items.append(
            {
                "title": title,
                "link": full_link,
                "body": title,
            }
        )

    return items


def parse_content(url: str, content: str) -> list[dict]:
    lower_url = url.lower()
    if lower_url.endswith(".rss") or "/.rss" in lower_url or "/rss" in lower_url:
        return parse_rss(content)
    return parse_html(url, content)


if st.button("Scan URLs"):
    urls = [u.strip() for u in url_text.splitlines() if u.strip()]
    keywords = [k.strip() for k in keyword_text.splitlines() if k.strip()]

    results = []

    for original_url in urls:
        try:
            content, fetched_url = fetch_url(original_url)
            items = parse_content(fetched_url, content)

            for item in items:
                combined_text = f'{item.get("title", "")} {item.get("body", "")}'
                keyword = match_keyword(combined_text, keywords)

                if keyword:
                    results.append(
                        {
                            "source": label_from_url(original_url),
                            "fetched_url": fetched_url,
                            "keyword": keyword,
                            "title": item.get("title", "Match found"),
                            "link": item.get("link", ""),
                            "snippet": (item.get("body", "") or "")[:300],
                        }
                    )

        except Exception as e:
            st.error(f"Error checking {original_url}: {e}")

    if results:
        st.success(f"Found {len(results)} matches")

        for item in results:
            st.subheader(item["title"])
            st.write(f'**Source:** {item["source"]}')
            st.write(f'**Keyword:** {item["keyword"]}')
            if is_reddit_url(item["fetched_url"]) and item["fetched_url"] != item["source"]:
                st.caption(f'Fetched via: {item["fetched_url"]}')
            elif item["fetched_url"]:
                st.caption(f'Fetched via: {item["fetched_url"]}')
            if item["snippet"]:
                st.write(item["snippet"])
            if item["link"]:
                st.markdown(f'[Open Match]({item["link"]})')
            st.divider()
    else:
        st.info("No matches found.")