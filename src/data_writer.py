"""Write daily digest data as JSON files for the static frontend."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .arxiv_scanner import Paper
from .claude_ranker import TweetDigest, UsageStats
from .news_scanner import PublicationFeed
from .twitter_scanner import TwitterUsageStats

DOCS_DIR = Path(__file__).parent.parent / "docs"
DATA_DIR = DOCS_DIR / "data"


def _paper_to_dict(paper: Paper) -> dict:
    return {
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "categories": paper.categories,
        "published": paper.published.isoformat() if paper.published else "",
        "abs_url": paper.abs_url,
        "pdf_url": paper.pdf_url,
        "is_author_match": paper.is_author_match,
        "relevance_score": paper.relevance_score,
        "relevance_reason": paper.relevance_reason,
    }


def write_daily_data(
    date_str: str,
    author_papers: list[Paper],
    ranked_papers: list[Paper],
    tweet_digest: TweetDigest,
    news_feeds: list[PublicationFeed] | None = None,
    claude_usage: UsageStats | None = None,
    twitter_usage: TwitterUsageStats | None = None,
) -> Path:
    """Write papers.json and tweets.json for a given date, and update dates.json."""
    day_dir = DATA_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    claude_cost = claude_usage.to_dict() if claude_usage else None
    twitter_cost = twitter_usage.to_dict() if twitter_usage else None
    total_cost = (claude_usage.estimated_cost_usd if claude_usage else 0) + (twitter_usage.estimated_cost_usd if twitter_usage else 0)
    cost_info = {
        "claude": claude_cost,
        "twitter": twitter_cost,
        "total_estimated_cost_usd": round(total_cost, 4),
    } if (claude_cost or twitter_cost) else None

    # Write papers.json
    papers_data = {
        "date": date_str,
        "generated_at": generated_at,
        "author_papers": [_paper_to_dict(p) for p in author_papers],
        "ranked_papers": [_paper_to_dict(p) for p in ranked_papers],
    }
    with open(day_dir / "papers.json", "w") as f:
        json.dump(papers_data, f, indent=2)

    # Write tweets.json
    tweets_data = {
        "date": date_str,
        "generated_at": generated_at,
        "paper_announcements": tweet_digest.paper_announcements,
        "announcements": tweet_digest.announcements,
        "discussions": tweet_digest.discussions,
    }
    with open(day_dir / "tweets.json", "w") as f:
        json.dump(tweets_data, f, indent=2)

    # Write news.json
    if news_feeds:
        news_data = {
            "date": date_str,
            "generated_at": generated_at,
            "publications": [
                {
                    "name": f.name,
                    "short_name": f.short_name,
                    "domain": f.domain,
                    "url": f.url,
                    "logo_url": f.logo_url,
                    "articles": [{"title": a.title, "url": a.url} for a in f.articles],
                }
                for f in news_feeds
            ],
        }
        with open(day_dir / "news.json", "w") as f:
            json.dump(news_data, f, indent=2)

    # Write cost.json
    if cost_info:
        with open(day_dir / "cost.json", "w") as f:
            json.dump({"date": date_str, **cost_info}, f, indent=2)

    # Update cumulative cost log
    _update_cost_log(date_str, cost_info)

    # Update dates.json (sorted descending)
    dates_file = DATA_DIR / "dates.json"
    if dates_file.exists():
        with open(dates_file) as f:
            dates = json.load(f)
    else:
        dates = []

    if date_str not in dates:
        dates.append(date_str)
        dates.sort(reverse=True)

    with open(dates_file, "w") as f:
        json.dump(dates, f, indent=2)

    return day_dir


def _update_cost_log(date_str: str, cost_info: dict | None):
    """Append to a cumulative cost log for easy tracking over time."""
    if not cost_info:
        return

    cost_log_file = DATA_DIR / "cost_log.json"
    if cost_log_file.exists():
        with open(cost_log_file) as f:
            log = json.load(f)
    else:
        log = {"days": [], "total_cost_usd": 0.0}

    # Avoid duplicate entries for same date
    existing_dates = {entry["date"] for entry in log["days"]}
    if date_str not in existing_dates:
        log["days"].append({"date": date_str, **cost_info})
        log["total_cost_usd"] = round(
            log["total_cost_usd"] + cost_info["total_estimated_cost_usd"], 4
        )

    with open(cost_log_file, "w") as f:
        json.dump(log, f, indent=2)
