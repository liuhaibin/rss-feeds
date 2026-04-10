#!/usr/bin/env python3
"""RSS feed scraper for anthropic.com/engineering."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bs4 import BeautifulSoup
from common import run

FEED_CONFIG = {
    "id": "anthropic-engineering",
    "listing_url": "https://www.anthropic.com/engineering",
    "base_url": "https://www.anthropic.com",
    "feed_title": "Engineering at Anthropic",
    "feed_description": "Inside the team building reliable AI systems.",
    "feed_language": "en",
    "pagination_param": None,
    "output_file": "feeds/anthropic-engineering.xml",
    "state_file": "state/anthropic-engineering.json",
}


def parse_listing_page(soup: BeautifulSoup, base_url: str) -> list[dict]:
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
        # Featured/pinned articles sometimes lack a date in the listing;
        # get_article_date() in common.py will fetch the page as fallback.
        date_el = link_el.find("div", class_=lambda c: c and "__date" in (c or ""))
        date_str = date_el.get_text(strip=True) if date_el else ""

        if title:
            articles.append({"url": full_url, "title": title, "date_str": date_str})

    return articles


if __name__ == "__main__":
    run(FEED_CONFIG, parse_listing_page)
