#!/usr/bin/env python3
"""RSS feed scraper for claude.com/blog."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bs4 import BeautifulSoup
from common import run

FEED_CONFIG = {
    "id": "claude-blog",
    "listing_url": "https://claude.com/blog",
    "base_url": "https://claude.com",
    "feed_title": "Claude Blog",
    "feed_description": "Product news and best practices for teams building with Claude.",
    "feed_language": "en",
    "pagination_param": "b7eea976_page",
    "output_file": "feeds/claude-blog.xml",
    "state_file": "state/claude-blog.json",
}


def parse_listing_page(soup: BeautifulSoup, base_url: str) -> list[dict]:
    articles: list[dict] = []
    seen_urls: set[str] = set()

    def add(href: str, title: str, date_str: str) -> None:
        if not href.startswith("/blog/") or href.rstrip("/") == "/blog":
            return
        full_url = base_url + href
        if full_url not in seen_urls:
            seen_urls.add(full_url)
            articles.append({"url": full_url, "title": title, "date_str": date_str})

    # Hero article
    for card in soup.find_all("div", class_="card_blog_content"):
        date_el = card.find("div", class_=lambda c: c and "u-text-style-caption" in c.split())
        title_el = card.find("div", class_=lambda c: c and "card_blog_title" in c.split())
        link_el = (
            card.parent.find("a", class_=lambda c: c and "clickable_link" in c.split())
            if card.parent else None
        )
        if date_el and title_el and link_el:
            add(link_el.get("href", ""), title_el.get_text(strip=True), date_el.get_text(strip=True))

    # Article grid
    for wrap in soup.find_all("div", class_="card_blog_list_wrap"):
        title_el = wrap.find("h3", class_=lambda c: c and "card_blog_list_title" in c.split())
        date_el = wrap.find("div", attrs={"fs-list-field": "date"})
        link_el = wrap.find("a", class_=lambda c: c and "clickable_link" in c.split())
        if title_el and date_el and link_el:
            add(link_el.get("href", ""), title_el.get_text(strip=True), date_el.get_text(strip=True))

    return articles


if __name__ == "__main__":
    run(FEED_CONFIG, parse_listing_page)
