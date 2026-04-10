# RSS Feeds

Scrapes tech blogs that don't provide native RSS and generates RSS 2.0 feeds, automatically updated via GitHub Actions.

## Feeds

| Blog | RSS Feed |
|------|----------|
| [Claude Blog](https://claude.com/blog) | [feeds/claude-blog.xml](https://raw.githubusercontent.com/liuhaibin/rss-feeds/refs/heads/main/feeds/claude-blog.xml) |
| [Engineering at Anthropic](https://www.anthropic.com/engineering) | [feeds/anthropic-engineering.xml](https://raw.githubusercontent.com/liuhaibin/rss-feeds/refs/heads/main/feeds/anthropic-engineering.xml) |

Paste a feed URL into any RSS reader (Reeder, NetNewsWire, Feedly, etc.).

## How It Works

1. The scraper fetches `https://claude.com/blog` and parses article titles, URLs, and dates.
2. New articles are compared against `state/seen.json` to avoid duplicates.
3. For each new article, the scraper fetches its page to extract a description from the `og:description` meta tag.
4. `feeds/claude-blog.xml` is regenerated (newest-first) and both files are committed back to the repo.

## Project Structure

```
.
├── scraper/
│   ├── common.py                        # shared utilities (state, feed gen, HTTP helpers)
│   ├── claude_blog.py                   # scraper for claude.com/blog
│   └── anthropic_engineering.py         # scraper for anthropic.com/engineering
├── feeds/
│   ├── claude-blog.xml                  # generated RSS 2.0 feed
│   └── anthropic-engineering.xml        # generated RSS 2.0 feed
├── state/
│   ├── claude-blog.json                 # persists seen article URLs
│   └── anthropic-engineering.json       # persists seen article URLs
├── .github/
│   └── workflows/
│       └── update-feeds.yml             # scheduled GitHub Actions workflow
└── requirements.txt
```

## Running Locally

```bash
# Set up a virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run a specific feed (checks 1 listing page by default)
python scraper/claude_blog.py
python scraper/anthropic_engineering.py

# Seed with more history (checks first 5 pages)
MAX_PAGES=5 python scraper/claude_blog.py
```

## GitHub Actions

The workflow in `.github/workflows/update-feeds.yml` runs automatically every 6 hours. It uses a matrix strategy to process each feed config sequentially, committing only when new articles are found.

### First-time Setup

1. Push the repository to GitHub:
   ```bash
   git remote add origin https://github.com/liuhaibin/rss-feeds.git
   git add -A
   git commit -m "feat: initial Claude blog RSS feed"
   git push -u origin main
   ```

2. GitHub Actions is enabled by default on public repositories. For private repositories, go to **Settings → Actions → General** and set it to *Allow all actions*.

3. The workflow uses `GITHUB_TOKEN` (provided automatically) to push commits — no extra secrets are needed.

### Manual Trigger (Backfill / On-demand)

You can run the workflow at any time from the GitHub UI:

1. Open your repository on GitHub.
2. Click the **Actions** tab.
3. Select **Update RSS Feeds** from the left sidebar.
4. Click **Run workflow** (top-right of the workflow runs table).
5. Set **max_pages** to a higher number (e.g. `5`) for a full backfill, or leave it at `1` for a quick check.
6. Click the green **Run workflow** button.

### Scheduled Runs

The default cron schedule is every 6 hours (`0 */6 * * *`). To change the frequency, edit the `cron` value in `.github/workflows/update-feeds.yml`:

```yaml
on:
  schedule:
    - cron: '0 */6 * * *'   # every 6 hours — adjust as needed
```

Common examples:

| Interval | Cron expression |
|----------|----------------|
| Every hour | `0 * * * *` |
| Every 6 hours | `0 */6 * * *` |
| Daily at midnight UTC | `0 0 * * *` |
| Every Monday at 9 AM UTC | `0 9 * * 1` |
