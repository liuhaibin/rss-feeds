#!/usr/bin/env python3
"""RSS feed scraper for openai.com/news/research/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bs4 import BeautifulSoup
from common import run

FEED_CONFIG = {
    "id": "openai-research",
    "listing_url": "https://openai.com/news/research/",
    "base_url": "https://openai.com",
    "feed_title": "OpenAI Research",
    "feed_description": "Research news and publications from OpenAI.",
    "feed_language": "en",
    "pagination_param": None,
    "output_file": "feeds/openai-research.xml",
    "state_file": "state/openai-research.json",
}


def parse_listing_page(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Parse article cards via aria-label which encodes: 'Title - Category - Date'."""
    articles: list[dict] = []
    seen_urls: set[str] = set()

    for link_el in soup.find_all(
        "a",
        attrs={"aria-label": True},
        href=lambda h: h and h.startswith("/index/"),
    ):
        href = link_el.get("href", "")
        full_url = base_url + href
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # aria-label format: "Title - Category - Mon DD, YYYY"
        parts = link_el["aria-label"].rsplit(" - ", maxsplit=2)
        title = parts[0].strip() if parts else link_el["aria-label"]
        date_str = parts[-1].strip() if len(parts) >= 3 else ""

        articles.append({"url": full_url, "title": title, "date_str": date_str})

    return articles


if __name__ == "__main__":
    run(FEED_CONFIG, parse_listing_page)
