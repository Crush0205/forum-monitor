import streamlit as st
import requests
import xml.etree.ElementTree as ET
from urllib.parse import (
    urlparse,
    urljoin,
    parse_qsl,
    urlencode,
    urlunparse,
)
from bs4 import BeautifulSoup

DEFAULT_URLS = [
    "https://www.reddit.com/r/FordMaverickTruck/search/?q=intercooler",
    "https://www.reddit.com/r/FordMaverickTruck/new/",
    "https://www.reddit.com/r/FordMaverickTruckMods/new/",
    "https://www.mavericktruckclub.com/forum/",
    "https://www.maverickchat.com/forums/2022-ford-maverick-general-discussion-forum.8/",
]

DEFAULT_KEYWORDS = [
    "intercooler",
 
]

USER_AGENT = "web:forum-monitor:v1.0 (by /u/your_reddit_username)"


st.set_page_config(page_title="Forum Monitor", layout="wide")
st.title("Forum Monitor")
st.write(
    "Add Reddit URLs, RSS feeds, or forum URLs, then scan for keyword matches."
)


url_text = st.text_area(
    "URLs to check (one per line)",
    value="\n".join(DEFAULT_URLS),
    height=220,
)

keyword_text = st.text_area(
    "Keywords to look for (one per line)",
    value="\n".join(DEFAULT_KEYWORDS),
    height=180,
)


def label_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}"


def match_keyword(text: str, keywords: list[str]):
    text = (text or "").lower()
    for kw in keywords:
        kw = kw.strip().lower()
        if kw and kw in text:
            return kw
    return None


def is_reddit_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return "reddit.com" in netloc or "redd.it" in netloc


def convert_reddit_url(url: str):
    """
    Returns:
        converted_url, warning_message

    Behavior:
    - subreddit search URLs become search.rss
    - subreddit listing URLs become .rss
    - plain subreddit URLs become /new/.rss
    - site-wide /search URLs are NOT converted; warning returned instead
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = dict(query_pairs)

    if "reddit.com" not in netloc and "redd.it" not in netloc:
        return url, None

    if path.endswith(".rss") or "/.rss" in path or "/rss" in path:
        return url, None

    # Reject site-wide Reddit search
    if path == "/search":
        return (
            url,
            "Site-wide Reddit search URLs are not supported here. Use a subreddit search URL like https://www.reddit.com/r/SUBREDDIT/search/?q=term",
        )

    # Subreddit search -> search.rss
    if path.endswith("/search"):
        rss_path = path[:-7] + "/search.rss"

        if "restrict_sr" not in query and "/r/" in path:
            query["restrict_sr"] = "1"

        if "sort" not in query:
            query["sort"] = "new"

        rss_url = urlunparse(
            (
                "https",
                "www.reddit.com",
                rss_path,
                "",
                urlencode(query, doseq=True),
                "",
            )
        )
        return rss_url, None

    # Remove .json if user pasted a Reddit JSON URL
    if path.endswith(".json"):
        path = path[:-5]

    # Common listing pages
    listing_endings = ["/new", "/hot", "/top", "/rising", "/controversial"]
    for ending in listing_endings:
        if path.endswith(ending):
            rss_url = urlunparse(
                (
                    "https",
                    "www.reddit.com",
                    path + "/.rss",
                    "",
                    urlencode(query, doseq=True),
                    "",
                )
            )
            return rss_url, None

    # Plain subreddit URL -> default to /new/.rss
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "r":
        subreddit = parts[1]
        rss_url = urlunparse(
            (
                "https",
                "www.reddit.com",
                f"/r/{subreddit}/new/.rss",
                "",
                urlencode(query, doseq=True),
                "",
            )
        )
        return rss_url, None

    return url, None


def fetch_url(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


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

        if href.startswith(("javascript:", "mailto:", "#")):
            continue

        full_link = urljoin(base_url, href)

        # Keep on same domain only
        if urlparse(full_link).netloc != urlparse(base_url).netloc:
            continue

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
            fetch_url_to_use = original_url

            if is_reddit_url(original_url):
                fetch_url_to_use, warning = convert_reddit_url(original_url)
                if warning:
                    st.warning(f"{original_url}: {warning}")
                    continue

            content = fetch_url(fetch_url_to_use)
            items = parse_content(fetch_url_to_use, content)

            for item in items:
                combined_text = f'{item.get("title", "")} {item.get("body", "")}'
                keyword = match_keyword(combined_text, keywords)

                if keyword:
                    results.append(
                        {
                            "source": label_from_url(original_url),
                            "fetched_via": fetch_url_to_use,
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
            st.caption(f'Fetched via: {item["fetched_via"]}')
            if item["snippet"]:
                st.write(item["snippet"])
            if item["link"]:
                st.markdown(f'[Open Match]({item["link"]})')
            st.divider()
    else:
        st.info("No matches found.")