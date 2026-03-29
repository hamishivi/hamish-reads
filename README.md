# hamish-reads

A daily, automated research digest that surfaces arxiv papers, Twitter discussions, and news headlines relevant to your work — so you can stop doomscrolling and still stay current.

Runs as a GitHub Action on a cron schedule. Publishes a static website via GitHub Pages.

**Live site**: https://ivison.id.au/hamish-reads/

## How it works

Every weekday evening (after arxiv posts new papers at 8pm ET):

1. **Arxiv scanner** fetches new papers from cs.CL, cs.AI, cs.LG, cs.IR via RSS feeds
2. **Author filter** pulls out papers from ~140 researchers you follow
3. **Notion integration** reads current project descriptions from your PhD Hub page
4. **Claude** ranks remaining papers by relevance to your projects (scored 0-10 with a one-line reason)
5. **Twitter scanner** fetches your home timeline via OAuth 1.0a (reverse chronological)
6. **Claude** categorizes tweets into paper threads, announcements, and discussions
7. **News scanner** fetches headlines from 9 publications via RSS
8. **Data writer** outputs JSON files for the day with cost tracking
9. **GitHub Action** commits the data and GitHub Pages serves an updated static site

## Architecture

```
GitHub Action (8:30pm ET, Mon-Fri)
  → src/main.py [--date YYYY-MM-DD for backfills]
    → arxiv RSS feeds → filter by authors
    → Notion API → read project topics from PhD Hub child pages
    → Twitter API v2 (OAuth 1.0a) → home timeline, paginated
    → Claude API → rank papers + summarize tweets
    → News RSS feeds → headlines from 9 publications
    → Write JSON to docs/data/YYYY-MM-DD/
  → git commit + push
  → GitHub Pages serves docs/
```

### Data flow

The backend writes structured JSON. The frontend is a static HTML/CSS/JS page that loads these files client-side:

```
docs/data/
├── dates.json                    # list of available dates
├── cost_log.json                 # cumulative cost tracking
└── YYYY-MM-DD/
    ├── papers.json               # author-matched + relevance-ranked papers
    ├── tweets.json               # categorized tweet summaries
    ├── news.json                 # publication headlines
    └── cost.json                 # daily cost breakdown (Claude + Twitter)
```

### Frontend

Inspired by [fresh-finds](https://github.com/davidheineman/fresh-finds). Vanilla HTML + CSS + JS, no framework.

- **Papers tab**: papers from followed researchers + papers relevant to your projects
- **Tweets tab**: embedded tweets (via `twttr.widgets.createTweet`), categorized by Claude into paper threads, announcements, discussions. Dark/light mode support.
- **News tab**: 9 publications with logos and top 5 daily headlines (WSJ, NYTimes, New Yorker, SMH, ABC News, The Verge, Wired, Guardian AU, The Atlantic)
- **Date navigation**: URL hash (`#YYYY-MM-DD`), calendar picker, arrow buttons
- Light/dark mode via `prefers-color-scheme`, serif typography, max-width 720px

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/hamishivi/hamish-reads.git
cd hamish-reads
```

Edit `config.yaml`:
- Add arxiv author names you want to track
- Set your Twitter user ID
- Set your Notion PhD Hub page ID
- Adjust `max_pages` for Twitter cost control

### 2. API keys

**Anthropic** (1 secret):
- `ANTHROPIC_API_KEY`: for Claude-powered ranking and summarization

**Twitter/X** (4 secrets, OAuth 1.0a for home timeline access):
- `TWITTER_API_KEY`: consumer key
- `TWITTER_API_SECRET`: consumer secret
- `TWITTER_ACCESS_TOKEN`: your access token (starts with your user ID)
- `TWITTER_ACCESS_TOKEN_SECRET`: your access token secret

**Notion** (1 secret):
- `NOTION_API_KEY`: create an integration at https://www.notion.so/my-integrations and share your PhD Hub page with it

### 3. GitHub setup

1. Add all 6 secrets to the repo (Settings → Secrets → Actions)
2. Enable GitHub Pages: Settings → Pages → Source: `docs/` on `main` branch
3. The Action runs automatically Mon-Fri at 8:30pm ET, or trigger manually via `workflow_dispatch` (with optional date input for backfills)

### 4. Run locally

```bash
uv sync
export ANTHROPIC_API_KEY=...
export TWITTER_API_KEY=...
export TWITTER_API_SECRET=...
export TWITTER_ACCESS_TOKEN=...
export TWITTER_ACCESS_TOKEN_SECRET=...
export NOTION_API_KEY=...
uv run python -m src.main
# Or backfill a specific date:
uv run python -m src.main --date 2026-03-26
# Then serve locally:
cd docs && python -m http.server
```

## Project structure

```
src/
├── main.py              # orchestrator entry point (supports --date flag)
├── arxiv_scanner.py     # fetch papers via arxiv RSS feeds
├── twitter_scanner.py   # fetch home timeline via OAuth 1.0a
├── notion_client.py     # read PhD Hub child pages
├── claude_ranker.py     # rank papers + summarize tweets (with cost tracking)
├── news_scanner.py      # fetch headlines from 9 publications via RSS
└── data_writer.py       # write daily JSON + cost tracking

docs/                    # GitHub Pages static site
├── index.html
├── css/                 # common.css, typography.css
├── js/                  # app.js (tabs, date nav, tweet embeds, rendering)
└── data/                # generated daily JSON
```

## Cost

Daily cost tracking is built in — shown in the page footer and logged to `cost_log.json`.

- **Claude API**: ~$0.05-0.15/day (Sonnet, paper ranking + tweet summarization)
- **Twitter API**: ~$0.005/post read. At 10 pages (~700-1000 tweets): ~$3.50-5.00/day
- **Arxiv + News RSS**: free
- **Notion API**: free
- **Hosting**: free (GitHub Pages + GitHub Actions)

Adjust `twitter.max_pages` in `config.yaml` to control Twitter costs.
