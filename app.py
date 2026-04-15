import streamlit as st
import requests
from urllib.parse import urlparse

DEFAULT_URLS = [
    "https://www.reddit.com/r/cars/new.json?limit=20",
    "https://www.reddit.com/r/projectcar/new.json?limit=20",
    "https://www.reddit.com/r/Cartalk/new.json?limit=20",
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

st.write("Add Reddit JSON URLs and keywords, then click the button to scan for matches.")

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

def fetch_reddit_json(url):
    headers = {"User-Agent": "forum-monitor/0.1"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

def clean_reddit_link(permalink):
    if permalink.startswith("http"):
        return permalink
    return "https://www.reddit.com" + permalink

def label_from_url(url):
    parsed = urlparse(url)
    return parsed.netloc + parsed.path

if st.button("Scan URLs"):
    urls = [u.strip() for u in url_text.splitlines() if u.strip()]
    keywords = [k.strip() for k in keyword_text.splitlines() if k.strip()]

    results = []

    for url in urls:
        try:
            data = fetch_reddit_json(url)
            children = data.get("data", {}).get("children", [])

            for item in children:
                post = item.get("data", {})
                title = post.get("title", "")
                body = post.get("selftext", "") or post.get("body", "")
                text = f"{title} {body}"

                keyword = match_keyword(text, keywords)
                if keyword:
                    results.append({
                        "source": label_from_url(url),
                        "keyword": keyword,
                        "title": title if title else "Comment match",
                        "link": clean_reddit_link(post.get("permalink", "")),
                        "snippet": body[:300]
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