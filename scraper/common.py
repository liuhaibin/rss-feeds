"""Shared utilities for RSS feed scrapers.

Each per-feed script imports `run` from here and provides its own
FEED_CONFIG dict and `parse_listing_page(soup, base_url)` function.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

MAX_PAGES = int(os.environ.get("MAX_PAGES", "1"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {"articles": []}


def save_state(state: dict, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> datetime:
    """Parse various date formats -> UTC datetime.

    Supported:
      - 'Apr 10, 2026' / 'March 12, 2026'  (listing page text)
      - '2026-03-25T10:00' / '2026-03-25'   (ISO datetime attribute)
    """
    date_str = date_str.strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str!r}")


# ---------------------------------------------------------------------------
# Article detail fetchers
# ---------------------------------------------------------------------------

def get_description(url: str) -> str:
    """Fetch the article page and return its og:description or meta description."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for attrs in ({"property": "og:description"}, {"name": "description"}):
            meta = soup.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                return meta["content"].strip()
    except Exception as exc:
        print(f"  Warning: could not fetch description for {url}: {exc}", file=sys.stderr)
    return ""


def get_article_date(url: str) -> str:
    """Fetch the article page and extract a publish date when the listing omits it."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for attrs in (
            {"property": "article:published_time"},
            {"name": "publish_date"},
            {"name": "date"},
        ):
            meta = soup.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                return meta["content"].strip()
        # Fallback: scan visible text for a date pattern
        m = re.search(
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}\b',
            soup.get_text(),
        )
        if m:
            return m.group()
    except Exception as exc:
        print(f"  Warning: could not fetch date for {url}: {exc}", file=sys.stderr)
    return ""


# ---------------------------------------------------------------------------
# Feed generation
# ---------------------------------------------------------------------------

def generate_feed(articles: list[dict], cfg: dict) -> None:
    output_file = Path(cfg["output_file"])
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fg = FeedGenerator()
    fg.id(cfg["listing_url"])
    fg.title(cfg["feed_title"])
    fg.link(href=cfg["listing_url"], rel="alternate")
    fg.description(cfg["feed_description"])
    fg.language(cfg["feed_language"])
    fg.lastBuildDate(datetime.now(timezone.utc))

    # feedgen reverses entries when writing, so sort ascending to get newest-first output
    for art in sorted(articles, key=lambda a: a["date"]):
        fe = fg.add_entry()
        fe.id(art["url"])
        fe.title(art["title"])
        fe.link(href=art["url"])
        fe.published(art["date"])
        fe.updated(art["date"])
        fe.description(art["description"] or art["title"])

    fg.rss_file(str(output_file), pretty=True)
    print(f"Feed written to {output_file} ({len(articles)} entries)")


# ---------------------------------------------------------------------------
# Main scraper loop (called by each per-feed script)
# ---------------------------------------------------------------------------

def run(cfg: dict, parse_listing_page) -> None:
    """Scrape a blog, update state, and regenerate the RSS feed.

    Args:
        cfg: Feed configuration dict (see any per-feed script for the shape).
        parse_listing_page: Callable(soup, base_url) -> list[dict] specific to
            the blog's HTML structure. Each dict must have keys:
            url, title, date_str.
    """
    state_file = Path(cfg["state_file"])
    state = load_state(state_file)
    known_urls: set[str] = {a["url"] for a in state["articles"]}

    print(f"[{cfg['id']}] State has {len(known_urls)} known articles.")
    print(f"[{cfg['id']}] Scraping up to {MAX_PAGES} listing page(s)...")

    new_articles: list[dict] = []
    pagination_param = cfg.get("pagination_param")

    for page_num in range(1, MAX_PAGES + 1):
        if page_num == 1 or not pagination_param:
            page_url = cfg["listing_url"]
        else:
            page_url = f"{cfg['listing_url']}?{pagination_param}={page_num}"

        print(f"  Fetching: {page_url}")
        resp = requests.get(page_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        page_articles = parse_listing_page(soup, cfg["base_url"])
        print(f"  Found {len(page_articles)} articles on page {page_num}")

        found_new = False
        for art in page_articles:
            if art["url"] not in known_urls:
                found_new = True
                new_articles.append(art)
                known_urls.add(art["url"])

        if not found_new and page_num > 1:
            print("  All articles on this page already known -- stopping pagination.")
            break

        if page_num < MAX_PAGES and pagination_param:
            time.sleep(1)

    if not new_articles:
        print(f"[{cfg['id']}] No new articles found.")
    else:
        print(f"\n[{cfg['id']}] Found {len(new_articles)} new article(s). Fetching details...")
        for art in new_articles:
            print(f"  {art['title'][:70]}")
            art["description"] = get_description(art["url"])

            if not art["date_str"]:
                art["date_str"] = get_article_date(art["url"])

            try:
                art["date"] = parse_date(art["date_str"]).isoformat()
            except ValueError as exc:
                print(f"  Warning: {exc} -- using today's date", file=sys.stderr)
                art["date"] = datetime.now(timezone.utc).isoformat()

            time.sleep(0.5)

        state["articles"].extend(new_articles)
        save_state(state, state_file)
        print(f"\n[{cfg['id']}] State updated with {len(new_articles)} new article(s).")

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

    generate_feed(feed_articles, cfg)
