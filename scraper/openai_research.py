#!/usr/bin/env python3
"""RSS feed for OpenAI Research.

Instead of scraping the HTML (which is JS-rendered and CDN-gated), this
scraper reads OpenAI's official RSS feed at openai.com/news/rss.xml and
filters for items categorised as "Research".
"""

import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bs4 import BeautifulSoup
from common import HEADERS, load_state, save_state, generate_feed, MAX_PAGES
import requests

FEED_CONFIG = {
    "id": "openai-research",
    "listing_url": "https://openai.com/news/research/",
    "base_url": "https://openai.com",
    "feed_title": "OpenAI Research",
    "feed_description": "Research news and publications from OpenAI.",
    "feed_language": "en",
    "output_file": "feeds/openai-research.xml",
    "state_file": "state/openai-research.json",
}

OFFICIAL_RSS_URL = "https://openai.com/news/rss.xml"
RESEARCH_CATEGORY = "Research"


def fetch_research_articles() -> list[dict]:
    """Fetch OpenAI's official RSS and return only Research-category items."""
    resp = requests.get(OFFICIAL_RSS_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    articles = []

    for item in root.findall(".//item"):
        cat_el = item.find("category")
        if cat_el is None or cat_el.text != RESEARCH_CATEGORY:
            continue

        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        desc_el = item.find("description")

        if title_el is None or link_el is None:
            continue

        title = title_el.text or ""
        url = link_el.text or ""
        description = desc_el.text or "" if desc_el is not None else ""

        if pub_el is not None and pub_el.text:
            try:
                dt = parsedate_to_datetime(pub_el.text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        articles.append({
            "url": url,
            "title": title,
            "description": description,
            "date": dt,
        })

    return articles


def main() -> None:
    state_file = Path(FEED_CONFIG["state_file"])
    state = load_state(state_file)
    known_urls: set[str] = {a["url"] for a in state["articles"]}

    print(f"[{FEED_CONFIG['id']}] State has {len(known_urls)} known articles.")
    print(f"[{FEED_CONFIG['id']}] Fetching official RSS feed...")

    all_articles = fetch_research_articles()
    print(f"  Found {len(all_articles)} Research articles in official RSS")

    new_articles = [a for a in all_articles if a["url"] not in known_urls]

    if not new_articles:
        print(f"[{FEED_CONFIG['id']}] No new articles found.")
    else:
        print(f"[{FEED_CONFIG['id']}] {len(new_articles)} new article(s):")
        for art in new_articles:
            print(f"  {art['title'][:70]}")
            state["articles"].append({
                "url": art["url"],
                "title": art["title"],
                "description": art["description"],
                "date": art["date"].isoformat(),
            })
        save_state(state, state_file)
        print(f"[{FEED_CONFIG['id']}] State updated.")

    # Regenerate feed from the full set of fetched articles (not just state)
    # so the feed always reflects the current upstream RSS content.
    generate_feed(all_articles, FEED_CONFIG)


if __name__ == "__main__":
    main()
