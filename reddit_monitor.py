import os
import re
import time
import sqlite3
import requests

# =========================
# CONFIG (EDIT THIS FIRST)
# =========================

SUBREDDITS = ["cars", "projectcar", "Cartalk"]

KEYWORDS = [
    "radiator",
    "intercooler",
    "transmission cooler",
    "oil cooler",
    "mishimoto",
"Car",
"nissan z",
"overheating",
]

CHECK_INTERVAL = 30  # seconds (15 min)

# =========================
# DATABASE (DO NOT TOUCH)
# =========================

DB = "seen.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

def seen(post_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen WHERE id=?", (post_id,))
    r = c.fetchone()
    conn.close()
    return r is not None

def mark_seen(post_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO seen (id) VALUES (?)", (post_id,))
    conn.commit()
    conn.close()

# =========================
# FETCH REDDIT POSTS
# =========================

def fetch_posts(sub):
    url = f"https://www.reddit.com/r/{sub}/new.json?limit=20"
    headers = {"User-Agent": "keyword-monitor/0.1"}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()["data"]["children"]

# =========================
# KEYWORD MATCHING
# =========================

def match(text):
    text = (text or "").lower()
    for kw in KEYWORDS:
        if kw.lower() in text:
            return kw
    return None

# =========================
# MAIN LOGIC
# =========================

def run():
    for sub in SUBREDDITS:
        try:
            posts = fetch_posts(sub)

            for p in posts:
                data = p["data"]
                post_id = data["id"]

                if seen(post_id):
                    continue

                text = data.get("title", "") + " " + data.get("selftext", "")
                keyword = match(text)

                if keyword:
                    link = "https://reddit.com" + data["permalink"]

                    print("\n========================")
                    print(f"Keyword Found: {keyword}")
                    print(f"Subreddit: r/{sub}")
                    print(f"Title: {data.get('title')}")
                    print(f"Link: {link}")
                    print("========================\n")

                mark_seen(post_id)

        except Exception as e:
            print(f"Error in r/{sub}: {e}")

# =========================
# LOOP
# =========================

def main():
    init_db()

    while True:
        print("Checking Reddit...")
        run()
        print(f"Sleeping {CHECK_INTERVAL} seconds...\n")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()