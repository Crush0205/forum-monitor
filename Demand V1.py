def to_reddit_rss_url(url: str) -> tuple[str, str | None]:
    """
    Returns:
      (converted_url, warning_message)

    warning_message is set when the URL is a global Reddit search that should
    not be auto-converted to RSS.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = dict(query_pairs)

    if "reddit.com" not in netloc:
        return url, None

    if path.endswith(".rss") or "/.rss" in path or "/rss" in path:
        return url, None

    # Site-wide Reddit search: don't auto-convert
    if path == "/search":
        return url, "Global Reddit search feeds are unreliable. Use a subreddit search URL like /r/SUBREDDIT/search/?q=term instead."

    # Subreddit search: convert to RSS
    if path.endswith("/search"):
        rss_path = path[:-7] + "/search.rss"
        if "restrict_sr" not in query and "/r/" in path:
            query["restrict_sr"] = "1"
        if "sort" not in query:
            query["sort"] = "new"

        rss_url = urlunparse((
            "https",
            "www.reddit.com",
            rss_path,
            "",
            urlencode(query, doseq=True),
            "",
        ))
        return rss_url, None

    # Common listing pages
    for ending in ["/new", "/hot", "/top", "/rising", "/controversial"]:
        if path.endswith(ending):
            rss_url = urlunparse((
                "https",
                "www.reddit.com",
                path + "/.rss",
                "",
                urlencode(query, doseq=True),
                "",
            ))
            return rss_url, None

    # Plain subreddit URL
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "r":
        subreddit = parts[1]
        rss_url = f"https://www.reddit.com/r/{subreddit}/new/.rss"
        return rss_url, None

    return url, None