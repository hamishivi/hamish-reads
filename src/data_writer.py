"""Write daily digest data as JSON files for the static frontend."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .arxiv_scanner import Paper
from .claude_ranker import TweetDigest

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
) -> Path:
    """Write papers.json and tweets.json for a given date, and update dates.json."""
    day_dir = DATA_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    # Write papers.json
    papers_data = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "author_papers": [_paper_to_dict(p) for p in author_papers],
        "ranked_papers": [_paper_to_dict(p) for p in ranked_papers],
    }
    with open(day_dir / "papers.json", "w") as f:
        json.dump(papers_data, f, indent=2)

    # Write tweets.json
    tweets_data = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_threads": tweet_digest.paper_threads,
        "announcements": tweet_digest.announcements,
        "discussions": tweet_digest.discussions,
    }
    with open(day_dir / "tweets.json", "w") as f:
        json.dump(tweets_data, f, indent=2)

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
