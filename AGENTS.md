# Agents Guide

This file provides context for AI agents working in this repository.

## Project overview

Daily AI research digest: fetches arxiv papers, Twitter home timeline, and news headlines. Uses Claude to rank papers and summarize tweets. Publishes a static website via GitHub Pages at https://ivison.id.au/hamish-reads/.

## Key concepts

- **Backend** (`src/`): Python scripts orchestrated by `src/main.py`. Each module is independent and returns dataclasses. The orchestrator calls them in sequence. Supports `--date YYYY-MM-DD` for backfills.
- **Frontend** (`docs/`): Vanilla HTML/CSS/JS static site. No build step, no framework. Data is loaded client-side from JSON files in `docs/data/`. URL hash (`#YYYY-MM-DD`) for date navigation.
- **Data contract**: The backend writes JSON to `docs/data/YYYY-MM-DD/{papers,tweets,news,cost}.json`. The frontend reads these. `docs/data/dates.json` is the index. `docs/data/cost_log.json` tracks cumulative costs.
- **Cost tracking**: Every Claude and Twitter API call is tracked. Daily cost written to `cost.json`, cumulative to `cost_log.json`, shown in the page footer.

## Module responsibilities

| Module | What it does | External APIs |
|--------|-------------|---------------|
| `src/arxiv_scanner.py` | Fetches papers via RSS feeds, filters by author list | arxiv RSS (via `httpx`) |
| `src/notion_client.py` | Reads PhD Hub page and its child pages for project topics | Notion API (via `notion-client`) |
| `src/twitter_scanner.py` | Fetches home timeline via OAuth 1.0a, paginated | Twitter API v2 (via `tweepy`, OAuth 1.0a) |
| `src/claude_ranker.py` | Ranks papers by relevance, categorizes/summarizes tweets. Tracks token usage and cost. | Anthropic API (via `anthropic`) |
| `src/news_scanner.py` | Fetches headlines from 9 publications via RSS | RSS feeds (via `httpx`) |
| `src/data_writer.py` | Writes daily JSON + cost tracking files | None (filesystem only) |
| `src/main.py` | Orchestrates all modules in sequence | None (calls other modules) |

## Configuration

`config.yaml` at the repo root: arxiv categories, ~140 author names, Twitter user ID, `max_pages` for Twitter cost control, Notion PhD Hub page ID, Claude model.

Environment variables (set as GitHub repo secrets):
- `ANTHROPIC_API_KEY`
- `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET` (OAuth 1.0a)
- `NOTION_API_KEY`

## Conventions

- **Python**: uses `uv` for package management. Run with `uv run python -m src.main`.
- **Dataclasses**: each module defines its own (`Paper`, `Tweet`, `ProjectTopic`, `TweetDigest`, `PublicationFeed`, `UsageStats`, `TwitterUsageStats`).
- **Error handling**: each scanner gracefully degrades — if an API is unreachable or unconfigured, it prints a warning and returns empty results. The digest still generates with whatever data is available.
- **Frontend**: no build step. Edit HTML/CSS/JS directly. Data rendering is in `docs/js/app.js`. Tweet embeds use `twttr.widgets.createTweet()` for dynamic rendering.

## Common tasks

### Adding a new data source
1. Create a new module in `src/` that returns a dataclass
2. Add it to `src/main.py` orchestration
3. Update `src/data_writer.py` to include the new data in the JSON output
4. Add a new tab in `docs/index.html` and rendering logic in `docs/js/app.js`

### Adding a new news publication
Edit the `PUBLICATIONS` list in `src/news_scanner.py`. Each entry needs: name, short_name, domain, url, and rss feed URL. No other changes needed.

### Modifying the frontend
The frontend is self-contained in `docs/`. No build step — just edit and reload. Key files:
- `docs/index.html` — page structure (3 tabs: Papers, Tweets, News)
- `docs/css/common.css` — layout and theming (CSS variables for light/dark)
- `docs/js/app.js` — tab switching, date navigation (#hash), tweet embeds, data fetching, DOM rendering

### Testing locally
```bash
uv sync
export ANTHROPIC_API_KEY=...
export TWITTER_API_KEY=...
export TWITTER_API_SECRET=...
export TWITTER_ACCESS_TOKEN=...
export TWITTER_ACCESS_TOKEN_SECRET=...
export NOTION_API_KEY=...
uv run python -m src.main
# Or backfill:
uv run python -m src.main --date 2026-03-26
# Serve locally (fetch() needs a server):
cd docs && python -m http.server
```

### Adding new arxiv categories or authors
Edit `config.yaml`. No code changes needed.

## Gotchas

- **Arxiv RSS**: feeds are empty on weekends (Saturday/Sunday). The cron only runs Mon-Fri. RSS returns the latest daily batch only — no historical access for backfills.
- **Twitter costs**: $0.005 per post read. At 10 pages (~1000 tweets) that's ~$5/day. Adjust `max_pages` in config.yaml to control.
- **Twitter auth**: uses OAuth 1.0a (4 credentials), NOT bearer token. Required for the home timeline endpoint.
- **Notion**: integration must be explicitly shared with the PhD Hub page in the Notion UI.
- **Tweet embeds**: use `twttr.widgets.createTweet(id, element)` for dynamic insertion. The blockquote approach doesn't work for dynamically added content.
- **Frontend serving**: loads JSON via `fetch()`, so it needs a server (not `file://`). Use `python -m http.server` in `docs/` for local testing.
- **Date in URL**: the hash (`#YYYY-MM-DD`) is used for deep linking and browser back/forward.
