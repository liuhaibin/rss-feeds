#!/usr/bin/env python3
"""RSS feed scraper for paulgraham.com/articles.html."""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import requests
from bs4 import BeautifulSoup
from common import HEADERS, load_state, save_state, generate_feed, MAX_PAGES

BASE_URL = "https://paulgraham.com"
LISTING_URL = "https://paulgraham.com/articles.html"

FEED_CONFIG = {
    "id": "paul-graham",
    "listing_url": LISTING_URL,
    "base_url": BASE_URL,
    "feed_title": "Paul Graham Essays",
    "feed_description": "Essays by Paul Graham.",
    "feed_language": "en",
    "output_file": "feeds/paul-graham.xml",
    "state_file": "state/paul-graham.json",
}

# Articles linked from nav/header that are not essays
_SKIP_HREFS = {"index.html", "rss.html", "arc.html", "bel.html", "lisp.html",
               "antispam.html", "kedrosky.html", "faq.html", "raq.html",
               "quo.html", "bio.html", "books.html"}


def fetch_listing() -> list[dict]:
    """Return all essays from the listing page as dicts with url and title."""
    resp = requests.get(LISTING_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "lxml")

    articles: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Only bare .html slugs (no path separators, no external links)
        if "/" in href or not href.endswith(".html"):
            continue
        if href in _SKIP_HREFS:
            continue
        title = a.get_text(strip=True)
        if not title or title.startswith("http"):
            continue
        url = f"{BASE_URL}/{href}"
        if url in seen:
            continue
        seen.add(url)
        articles.append({"url": url, "title": title})

    return articles


def fetch_article_details(url: str) -> tuple[str, str]:
    """Fetch an article page and return (date_str, description).

    Date is extracted from the first <font> tag whose text starts with a month
    name, e.g. 'March 2026'.  Description is the first substantive paragraph.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")

        date_str = ""
        for font in soup.find_all("font"):
            text = font.get_text(strip=True)
            # PG dates look like "March 2026" or "October 2023" at the start
            import re
            m = re.match(
                r'^(January|February|March|April|May|June|July|August|'
                r'September|October|November|December)\s+(\d{4})',
                text,
            )
            if m:
                date_str = m.group(0)
                break

        description = ""
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 80:
                description = text[:300]
                break

        return date_str, description
    except Exception as exc:
        print(f"  Warning: could not fetch details for {url}: {exc}", file=sys.stderr)
        return "", ""


def parse_date_pg(date_str: str) -> datetime:
    """Parse 'Month YYYY' -> UTC datetime (1st of that month)."""
    return datetime.strptime(date_str, "%B %Y").replace(tzinfo=timezone.utc)


def main() -> None:
    state_file = Path(FEED_CONFIG["state_file"])
    state = load_state(state_file)
    known_urls: set[str] = {a["url"] for a in state["articles"]}

    print(f"[{FEED_CONFIG['id']}] State has {len(known_urls)} known articles.")
    print(f"[{FEED_CONFIG['id']}] Fetching listing page...")

    all_articles = fetch_listing()
    print(f"[{FEED_CONFIG['id']}] Found {len(all_articles)} articles on listing page.")

    # In backfill mode (MAX_PAGES > 1) pick up more new articles; otherwise
    # only process articles not yet in state, up to MAX_PAGES * 20 at a time.
    max_new = MAX_PAGES * 20
    new_articles = [a for a in all_articles if a["url"] not in known_urls][:max_new]

    if not new_articles:
        print(f"[{FEED_CONFIG['id']}] No new articles found.")
    else:
        print(f"[{FEED_CONFIG['id']}] Found {len(new_articles)} new article(s). Fetching details...")
        for art in new_articles:
            print(f"  {art['title'][:70]}")
            date_str, description = fetch_article_details(art["url"])
            art["description"] = description
            if date_str:
                try:
                    art["date"] = parse_date_pg(date_str).isoformat()
                except ValueError:
                    art["date"] = datetime.now(timezone.utc).isoformat()
            else:
                art["date"] = datetime.now(timezone.utc).isoformat()
            time.sleep(0.5)

        state["articles"].extend(new_articles)
        save_state(state, state_file)
        print(f"[{FEED_CONFIG['id']}] State updated with {len(new_articles)} new article(s).")

    # Always regenerate feed from full state
    feed_articles = []
    for art in state["articles"]:
        dt = datetime.fromisoformat(art["date"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        feed_articles.append({
            "url": art["url"],
            "title": art["title"],
            "description": art.get("description", ""),
            "date": dt,
        })

    generate_feed(feed_articles, FEED_CONFIG)


if __name__ == "__main__":
    main()
