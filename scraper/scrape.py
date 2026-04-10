#!/usr/bin/env python3
"""Scrape claude.com/blog and generate RSS 2.0 feed.

State is persisted in state/seen.json so only new articles are processed
on subsequent runs. The full feed is regenerated from state on every run.

Environment variables:
  MAX_PAGES  Number of listing pages to scrape (default: 1).
             Set to a higher value (e.g. 5) for the initial seed run.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

BASE_URL = "https://claude.com"
BLOG_URL = "https://claude.com/blog"
STATE_FILE = Path("state/seen.json")
FEED_FILE = Path("feeds/claude-blog.xml")
MAX_PAGES = int(os.environ.get("MAX_PAGES", "1"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"articles": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> datetime:
    """Parse 'Apr 10, 2026' or 'March 12, 2026' → UTC datetime."""
    date_str = date_str.strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str!r}")


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_listing_page(url: str) -> list[dict]:
    """Return list of {url, title, date_str} from a blog listing page."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    articles: list[dict] = []
    seen_urls: set[str] = set()

    def add(href: str, title: str, date_str: str) -> None:
        if not href.startswith("/blog/") or href.rstrip("/") == "/blog":
            return
        full_url = BASE_URL + href
        if full_url not in seen_urls:
            seen_urls.add(full_url)
            articles.append({"url": full_url, "title": title, "date_str": date_str})

    # --- Hero / carousel section -------------------------------------------
    # Structure: div.card_blog_content holds date + title; the anchor
    # (a.clickable_link) is a sibling inside the same parent wrapper.
    for card in soup.find_all("div", class_="card_blog_content"):
        date_el = card.find(
            "div", class_=lambda c: c and "u-text-style-caption" in c.split()
        )
        title_el = card.find(
            "div", class_=lambda c: c and "card_blog_title" in c.split()
        )
        link_el = card.parent.find(
            "a", class_=lambda c: c and "clickable_link" in c.split()
        ) if card.parent else None

        if date_el and title_el and link_el:
            add(
                link_el.get("href", ""),
                title_el.get_text(strip=True),
                date_el.get_text(strip=True),
            )

    # --- Main grid listing section ------------------------------------------
    # Structure: div.card_blog_list_wrap holds h3.card_blog_list_title,
    # div[fs-list-field="date"] (hidden), and a.clickable_link.
    for wrap in soup.find_all("div", class_="card_blog_list_wrap"):
        title_el = wrap.find(
            "h3", class_=lambda c: c and "card_blog_list_title" in c.split()
        )
        date_el = wrap.find("div", attrs={"fs-list-field": "date"})
        link_el = wrap.find(
            "a", class_=lambda c: c and "clickable_link" in c.split()
        )

        if title_el and date_el and link_el:
            add(
                link_el.get("href", ""),
                title_el.get_text(strip=True),
                date_el.get_text(strip=True),
            )

    return articles


def get_description(url: str) -> str:
    """Fetch the article page and return its meta description."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for attrs in ({"property": "og:description"}, {"name": "description"}):
            meta = soup.find("meta", attrs=attrs)
            if meta and meta.get("content"):
                return meta["content"].strip()
    except Exception as exc:
        print(f"  Warning: could not fetch description for {url}: {exc}", file=sys.stderr)
    return ""


# ---------------------------------------------------------------------------
# Feed generation
# ---------------------------------------------------------------------------

def generate_feed(articles: list[dict]) -> None:
    """Regenerate the full RSS feed from the article list (newest first)."""
    FEED_FILE.parent.mkdir(parents=True, exist_ok=True)

    fg = FeedGenerator()
    fg.id(BLOG_URL)
    fg.title("Claude Blog")
    fg.link(href=BLOG_URL, rel="alternate")
    fg.description("Product news and best practices for teams building with Claude.")
    fg.language("en")
    fg.lastBuildDate(datetime.now(timezone.utc))

    sorted_articles = sorted(articles, key=lambda a: a["date"])

    for art in sorted_articles:
        fe = fg.add_entry()
        fe.id(art["url"])
        fe.title(art["title"])
        fe.link(href=art["url"])
        fe.published(art["date"])
        fe.updated(art["date"])
        fe.description(art["description"] or art["title"])

    fg.rss_file(str(FEED_FILE), pretty=True)
    print(f"Feed written to {FEED_FILE} ({len(sorted_articles)} entries)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    state = load_state()
    known_urls: set[str] = {a["url"] for a in state["articles"]}

    print(f"State has {len(known_urls)} known articles.")
    print(f"Scraping up to {MAX_PAGES} listing page(s)...")

    new_articles: list[dict] = []

    for page_num in range(1, MAX_PAGES + 1):
        page_url = BLOG_URL if page_num == 1 else f"{BLOG_URL}?b7eea976_page={page_num}"
        print(f"  Fetching: {page_url}")
        page_articles = scrape_listing_page(page_url)
        print(f"  Found {len(page_articles)} articles on page {page_num}")

        found_new = False
        for art in page_articles:
            if art["url"] not in known_urls:
                found_new = True
                new_articles.append(art)
                known_urls.add(art["url"])

        # Stop paginating once a page contains only known articles
        if not found_new and page_num > 1:
            print("  All articles on this page already known — stopping pagination.")
            break

        if page_num < MAX_PAGES:
            time.sleep(1)

    if not new_articles:
        print("No new articles found.")
    else:
        print(f"\nFound {len(new_articles)} new article(s). Fetching descriptions...")
        for art in new_articles:
            print(f"  {art['title'][:70]}")
            art["description"] = get_description(art["url"])
            try:
                art["date"] = parse_date(art["date_str"]).isoformat()
            except ValueError as exc:
                print(f"  Warning: {exc}", file=sys.stderr)
                art["date"] = datetime.now(timezone.utc).isoformat()
            time.sleep(0.5)

        state["articles"].extend(new_articles)
        save_state(state)
        print(f"\nState updated with {len(new_articles)} new article(s).")

    # Always regenerate the feed so it reflects current state
    feed_articles = []
    for art in state["articles"]:
        dt = datetime.fromisoformat(art["date"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        feed_articles.append(
            {
                "url": art["url"],
                "title": art["title"],
                "description": art.get("description", ""),
                "date": dt,
            }
        )

    generate_feed(feed_articles)


if __name__ == "__main__":
    main()
