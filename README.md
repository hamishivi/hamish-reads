# AI Research Digest

A daily, automated research digest that surfaces arxiv papers and Twitter discussions relevant to your work — so you can stop doomscrolling and still stay current.

Runs as a GitHub Action on a cron schedule. Publishes a static website via GitHub Pages.

## How it works

Every weekday evening (after arxiv posts new papers at 8pm ET):

1. **Arxiv scanner** fetches new papers from cs.CL, cs.AI, cs.LG, cs.IR
2. **Author filter** pulls out papers from researchers you follow
3. **Notion integration** reads your current project descriptions from a Notion page
4. **Claude** ranks remaining papers by relevance to your projects (scored 0-10 with a one-line reason)
5. **Twitter scanner** fetches recent tweets from accounts you follow, filtered by engagement
6. **Claude** categorizes tweets into paper threads, announcements, and discussions
7. **Data writer** outputs JSON files for the day
8. **GitHub Action** commits the data and GitHub Pages serves an updated static site

## Architecture

```
GitHub Action (8:30pm ET, Mon-Fri)
  → src/main.py
    → arxiv API → filter by authors
    → Notion API → read project topics from PhD Hub page
    → Twitter API v2 → fetch from your following list
    → Claude API → rank papers + summarize tweets
    → Write JSON to docs/data/YYYY-MM-DD/
  → git commit + push
  → GitHub Pages serves docs/
```

### Data flow

The backend writes structured JSON. The frontend is a static HTML/CSS/JS page that loads these files client-side:

```
docs/data/
├── dates.json                    # list of available dates
└── 2026-03-29/
    ├── papers.json               # author-matched + relevance-ranked papers
    └── tweets.json               # categorized tweet summaries
```

### Frontend

Inspired by [fresh-finds](https://github.com/davidheineman/fresh-finds). Vanilla HTML + CSS + JS, no framework.

- **Papers tab**: papers from followed researchers + papers relevant to your projects
- **Tweets tab**: paper threads, announcements, discussions — each linking to the original tweet
- **Date navigation**: calendar picker + arrow buttons to browse previous days
- Light/dark mode via `prefers-color-scheme`, serif typography, max-width 720px

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/hamishivi/ai-research-digest.git
cd ai-research-digest
```

Edit `config.yaml`:
- Add arxiv author names you want to track
- Add your Twitter user ID
- Add your Notion PhD Hub page ID

### 2. API keys

You need three API keys:
- **Anthropic** (`ANTHROPIC_API_KEY`): for Claude-powered ranking and summarization
- **Twitter** (`TWITTER_BEARER_TOKEN`): Twitter API v2 bearer token (Basic tier, $100/mo)
- **Notion** (`NOTION_API_KEY`): create an integration at https://www.notion.so/my-integrations and share your PhD Hub page with it

### 3. GitHub setup

1. Add the three API keys as repository secrets
2. Enable GitHub Pages: Settings → Pages → Source: `docs/` on `main` branch
3. The Action runs automatically Mon-Fri at 8:30pm ET, or trigger manually via `workflow_dispatch`

### 4. Run locally

```bash
uv sync
export ANTHROPIC_API_KEY=...
export TWITTER_BEARER_TOKEN=...
export NOTION_API_KEY=...
uv run python -m src.main
# Open docs/index.html in your browser
```

## Project structure

```
src/
├── main.py              # orchestrator entry point
├── arxiv_scanner.py     # fetch + filter arxiv papers
├── twitter_scanner.py   # fetch tweets from following list
├── notion_client.py     # read PhD Hub project pages
├── claude_ranker.py     # rank papers + summarize tweets
└── data_writer.py       # write daily JSON files

docs/                    # GitHub Pages static site
├── index.html
├── css/                 # common.css, typography.css
├── js/                  # app.js (tabs, date nav, rendering)
└── data/                # generated daily JSON
```

## Cost

- **Claude API**: ~$0.05-0.15/day (Sonnet, ~100 paper abstracts + ~50 tweets)
- **Twitter API**: $100/mo (Basic tier) — the scanner is optional if you skip this
- **Hosting**: free (GitHub Pages + GitHub Actions)
