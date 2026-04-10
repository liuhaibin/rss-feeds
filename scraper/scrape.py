#!/usr/bin/env python3
"""Config-driven blog scraper and RSS 2.0 feed generator.

Usage:
  python scraper/scrape.py --config configs/claude-blog.json
  python scraper/scrape.py --config configs/anthropic-engineering.json

Environment variables:
  MAX_PAGES  Number of listing pages to scrape (default: 1).
             Set to a higher value (e.g. 5) for the initial seed run.
"""

import argparse
import json
import os
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
    )
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
    """Parse 'Apr 10, 2026' or 'March 12, 2026' -> UTC datetime."""
    date_str = date_str.strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str!r}")


# ---------------------------------------------------------------------------
# Listing page parsers (one per scraper_type)
# ---------------------------------------------------------------------------

def parse_claude_blog(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse https://claude.com/blog listing page."""
    articles: list[dict] = []
    seen_urls: set[str] = set()

    def add(href: str, title: str, date_str: str) -> None:
        if not href.startswith("/blog/") or href.rstrip("/") == "/blog":
            return
        full_url = base_url + href
        if full_url not in seen_urls:
            seen_urls.add(full_url)
            articles.append({"url": full_url, "title": title, "date_str": date_str})

    # Hero / carousel section
    for card in soup.find_all("div", class_="card_blog_content"):
        date_el = card.find(
            "div", class_=lambda c: c and "u-text-style-caption" in c.split()
        )
        title_el = card.find(
            "div", class_=lambda c: c and "card_blog_title" in c.split()
        )
        link_el = (
            card.parent.find("a", class_=lambda c: c and "clickable_link" in c.split())
            if card.parent
            else None
        )
        if date_el and title_el and link_el:
            add(link_el.get("href", ""), title_el.get_text(strip=True), date_el.get_text(strip=True))

    # Main grid listing section
    for wrap in soup.find_all("div", class_="card_blog_list_wrap"):
        title_el = wrap.find(
            "h3", class_=lambda c: c and "card_blog_list_title" in c.split()
        )
        date_el = wrap.find("div", attrs={"fs-list-field": "date"})
        link_el = wrap.find("a", class_=lambda c: c and "clickable_link" in c.split())
        if title_el and date_el and link_el:
            add(link_el.get("href", ""), title_el.get_text(strip=True), date_el.get_text(strip=True))

    return articles


def parse_anthropic_engineering(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse https://www.anthropic.com/engineering listing page."""
    articles: list[dict] = []
    seen_urls: set[str] = set()

    for article in soup.find_all("article", class_=lambda c: c and "ArticleList" in (c or "")):
        link_el = article.find("a", class_=lambda c: c and "cardLink" in (c or ""))
        if not link_el:
            continue
        href = link_el.get("href", "")
        if not href.startswith("/engineering/"):
            continue
        full_url = base_url + href
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title_el = link_el.find(["h2", "h3"])
        title = title_el.get_text(strip=True) if title_el else ""

        # Date div has __date in its CSS module class name
        date_el = link_el.find("div", class_=lambda c: c and "__date" in (c or ""))
        date_str = date_el.get_text(strip=True) if date_el else ""

        if title:
            articles.append({"url": full_url, "title": title, "date_str": date_str})

    return articles


PARSERS = {
    "claude_blog": parse_claude_blog,
    "anthropic_engineering": parse_anthropic_engineering,
}


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_listing_page(url: str, scraper_type: str, base_url: str) -> list[dict]:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return PARSERS[scraper_type](soup, base_url)


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


def get_article_date(url: str) -> str:
    """Fetch article page and extract publish date when listing page omits it."""
    import re
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
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
    sorted_articles = sorted(articles, key=lambda a: a["date"])

    for art in sorted_articles:
        fe = fg.add_entry()
        fe.id(art["url"])
        fe.title(art["title"])
        fe.link(href=art["url"])
        fe.published(art["date"])
        fe.updated(art["date"])
        fe.description(art["description"] or art["title"])

    fg.rss_file(str(output_file), pretty=True)
    print(f"Feed written to {output_file} ({len(sorted_articles)} entries)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    arg_parser = argparse.ArgumentParser(description="Scrape a blog and update its RSS feed.")
    arg_parser.add_argument("--config", required=True, help="Path to feed config JSON file")
    args = arg_parser.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
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
        page_articles = scrape_listing_page(page_url, cfg["scraper_type"], cfg["base_url"])
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
        feed_articles.append(
            {
                "url": art["url"],
                "title": art["title"],
                "description": art.get("description", ""),
                "date": dt,
            }
        )

    generate_feed(feed_articles, cfg)


if __name__ == "__main__":
    main()
