"""Orchestrator — runs all scanners, ranks, summarizes, and writes daily data."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .arxiv_scanner import fetch_recent_papers, filter_by_authors
from .claude_ranker import TweetDigest, rank_papers, summarize_tweets
from .data_writer import write_daily_data
from .notion_client import fetch_project_topics
from .twitter_scanner import fetch_tweets


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Generating digest for {today}")

    # 1. Fetch arxiv papers
    print("Fetching arxiv papers...")
    arxiv_cfg = config["arxiv"]
    all_papers = fetch_recent_papers(
        categories=arxiv_cfg["categories"],
        max_per_category=arxiv_cfg.get("max_papers_per_category", 100),
    )
    print(f"  Found {len(all_papers)} papers")

    author_papers, other_papers = filter_by_authors(
        all_papers, arxiv_cfg.get("authors", [])
    )
    print(f"  {len(author_papers)} from followed authors, {len(other_papers)} remaining")

    # 2. Fetch Notion project topics
    print("Fetching Notion project topics...")
    notion_cfg = config.get("notion", {})
    page_id = notion_cfg.get("phd_hub_page_id", "")
    project_topics = fetch_project_topics(page_id) if page_id else []
    print(f"  Found {len(project_topics)} projects")

    # 3. Rank papers by project relevance
    print("Ranking papers by relevance...")
    claude_cfg = config.get("claude", {})
    model = claude_cfg.get("model", "claude-sonnet-4-20250514")
    ranked_papers = rank_papers(
        other_papers,
        project_topics,
        model=model,
        max_results=arxiv_cfg.get("max_ranked_papers", 20),
    )
    print(f"  {len(ranked_papers)} relevant papers")

    # 4. Fetch tweets
    print("Fetching tweets...")
    twitter_cfg = config.get("twitter", {})
    user_id = twitter_cfg.get("user_id", "")
    tweets = fetch_tweets(
        user_id=user_id,
        min_engagement=twitter_cfg.get("min_engagement", 10),
    ) if user_id else []
    print(f"  Found {len(tweets)} tweets")

    # 5. Summarize tweets
    print("Summarizing tweets...")
    tweet_digest = summarize_tweets(tweets, model=model) if tweets else TweetDigest(
        paper_threads=[], announcements=[], discussions=[]
    )
    thread_count = len(tweet_digest.paper_threads)
    announce_count = len(tweet_digest.announcements)
    discuss_count = len(tweet_digest.discussions)
    print(f"  {thread_count} paper threads, {announce_count} announcements, {discuss_count} discussions")

    # 6. Write data
    print("Writing data...")
    day_dir = write_daily_data(today, author_papers, ranked_papers, tweet_digest)
    print(f"  Written to {day_dir}")

    print("Done!")


if __name__ == "__main__":
    main()
