import streamlit as st
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

DEFAULT_URLS = [
    "https://www.reddit.com/r/cars/new/.rss",
    "https://www.reddit.com/r/projectcar/new/.rss",
    "https://www.reddit.com/r/FordMaverickTruck/new/.rss",
]

DEFAULT_KEYWORDS = [
    "radiator",
    "intercooler",
    "transmission cooler",
    "oil cooler",
    "mishimoto",
]

st.set_page_config(page_title="Forum Monitor", layout="wide")
st.title("Forum Monitor")

st.write("Add RSS feed URLs and keywords, then click Scan URLs.")

url_text = st.text_area(
    "URLs to check (one per line)",
    value="\n".join(DEFAULT_URLS),
    height=160
)

keyword_text = st.text_area(
    "Keywords to look for (one per line)",
    value="\n".join(DEFAULT_KEYWORDS),
    height=160
)

def match_keyword(text, keywords):
    text = (text or "").lower()
    for kw in keywords:
        kw = kw.strip().lower()
        if kw and kw in text:
            return kw
    return None

def fetch_rss(url):
    headers = {
        "User-Agent": "web:forum-monitor:v1.0 (by /u/YOUR_REDDIT_USERNAME)"
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text

def label_from_url(url):
    parsed = urlparse(url)
    return parsed.netloc + parsed.path

def parse_rss(xml_text):
    root = ET.fromstring(xml_text)

    # RSS 2.0
    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        description = item.findtext("description", default="")
        items.append({
            "title": title,
            "link": link,
            "body": description
        })

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

            items.append({
                "title": title,
                "link": link,
                "body": content or summary
            })

    return items

if st.button("Scan URLs"):
    urls = [u.strip() for u in url_text.splitlines() if u.strip()]
    keywords = [k.strip() for k in keyword_text.splitlines() if k.strip()]

    results = []

    for url in urls:
        try:
            xml_text = fetch_rss(url)
            items = parse_rss(xml_text)

            for item in items:
                text = f'{item["title"]} {item["body"]}'
                keyword = match_keyword(text, keywords)

                if keyword:
                    results.append({
                        "source": label_from_url(url),
                        "keyword": keyword,
                        "title": item["title"] or "Match found",
                        "link": item["link"],
                        "snippet": (item["body"] or "")[:300]
                    })

        except Exception as e:
            st.error(f"Error checking {url}: {e}")

    if results:
        st.success(f"Found {len(results)} matches")
        for item in results:
            st.subheader(item["title"])
            st.write(f'**Source:** {item["source"]}')
            st.write(f'**Keyword:** {item["keyword"]}')
            if item["snippet"]:
                st.write(item["snippet"])
            st.markdown(f'[Open Match]({item["link"]})')
            st.divider()
    else:
        st.info("No matches found.")