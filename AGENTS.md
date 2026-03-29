# Agents Guide

This file provides context for AI agents working in this repository.

## Project overview

This is a daily AI research digest system. A GitHub Action runs nightly to fetch arxiv papers and Twitter posts, uses Claude to rank/summarize them, and publishes a static website via GitHub Pages.

## Key concepts

- **Backend** (`src/`): Python scripts orchestrated by `src/main.py`. Each module is independent and returns dataclasses or simple data structures. The orchestrator calls them in sequence.
- **Frontend** (`docs/`): Vanilla HTML/CSS/JS static site. No build step, no framework. Data is loaded client-side from JSON files in `docs/data/`.
- **Data contract**: The backend writes JSON to `docs/data/YYYY-MM-DD/papers.json` and `tweets.json`. The frontend reads these. `docs/data/dates.json` is the index of available dates.

## Module responsibilities

| Module | What it does | External APIs |
|--------|-------------|---------------|
| `src/arxiv_scanner.py` | Fetches recent papers, filters by author list | arxiv Atom feed (via `arxiv` package) |
| `src/notion_client.py` | Reads project topics from a Notion page hierarchy | Notion API (via `notion-client`) |
| `src/twitter_scanner.py` | Fetches tweets from the user's following list | Twitter API v2 (via `tweepy`) |
| `src/claude_ranker.py` | Ranks papers by relevance, categorizes tweets | Anthropic API (via `anthropic`) |
| `src/data_writer.py` | Writes JSON files to `docs/data/` | None (filesystem only) |
| `src/main.py` | Orchestrates all modules in sequence | None (calls other modules) |

## Configuration

`config.yaml` at the repo root contains all user configuration: arxiv categories, author names, Twitter user ID, Notion page ID, Claude model selection.

API keys are passed via environment variables: `ANTHROPIC_API_KEY`, `TWITTER_BEARER_TOKEN`, `NOTION_API_KEY`.

## Conventions

- **Python**: uses `uv` for package management. Run with `uv run python -m src.main`.
- **Dataclasses**: each module defines its own dataclasses (`Paper`, `Tweet`, `ProjectTopic`, `TweetDigest`). These are the interfaces between modules.
- **Error handling**: each scanner gracefully degrades — if an API is unreachable or unconfigured, it prints a warning and returns empty results. The digest still generates with whatever data is available.
- **Frontend**: no build step. Edit HTML/CSS/JS directly. Data rendering is in `docs/js/app.js`.

## Common tasks

### Adding a new data source
1. Create a new module in `src/` that returns a dataclass
2. Add it to `src/main.py` orchestration
3. Update `src/data_writer.py` to include the new data in the JSON output
4. Update `docs/js/app.js` to render it

### Modifying the frontend
The frontend is self-contained in `docs/`. No build step — just edit and reload. Key files:
- `docs/index.html` — page structure
- `docs/css/common.css` — layout and theming (CSS variables for light/dark)
- `docs/js/app.js` — tab switching, date navigation, data fetching, DOM rendering

### Testing locally
```bash
uv sync
export ANTHROPIC_API_KEY=...
uv run python -m src.main
# Then open docs/index.html — it loads data from docs/data/
```

### Adding new arxiv categories or authors
Edit `config.yaml`. No code changes needed.

## Gotchas

- The `arxiv` package has a built-in 3-second rate limit between requests. Fetching 5 categories takes ~15 seconds.
- Twitter API v2 Basic tier ($100/mo) is needed for search_recent_tweets. Free tier is too limited.
- Notion integration must be explicitly shared with the target page in the Notion UI.
- arxiv posts new papers at 8pm ET Sun-Thu only. The GitHub Action cron is set accordingly.
- The frontend loads JSON via `fetch()`, so it needs to be served (not opened as `file://`). Use `python -m http.server` in `docs/` for local testing.
