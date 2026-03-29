"""Orchestrator — runs all scanners, ranks, summarizes, and writes daily data."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .arxiv_scanner import fetch_recent_papers, filter_by_authors
from .claude_ranker import TweetDigest, get_usage as get_claude_usage, rank_papers, reset_usage as reset_claude_usage, summarize_tweets
from .data_writer import write_daily_data
from .news_scanner import fetch_news
from .notion_client import fetch_project_topics
from .twitter_scanner import fetch_tweets, get_usage as get_twitter_usage, reset_usage as reset_twitter_usage


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Date to generate digest for (YYYY-MM-DD). Defaults to today.")
    args = parser.parse_args()

    config = load_config()

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        date_str = args.date
    else:
        target_date = datetime.now(timezone.utc)
        date_str = target_date.strftime("%Y-%m-%d")

    print(f"Generating digest for {date_str}")
    reset_claude_usage()
    reset_twitter_usage()

    # Calculate hours_back: for backfills, look at papers from that day
    # arxiv posts at 8pm ET (~00:00 UTC next day), so for a given date
    # we want papers from roughly that 24h window
    now = datetime.now(timezone.utc)
    hours_since_target = max(24, (now - target_date).total_seconds() / 3600)

    # 1. Fetch arxiv papers
    print("Fetching arxiv papers...")
    arxiv_cfg = config["arxiv"]
    all_papers = fetch_recent_papers(
        categories=arxiv_cfg["categories"],
        max_per_category=arxiv_cfg.get("max_papers_per_category", 100),
        hours_back=int(hours_since_target),
        target_date=target_date,
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
        max_pages=twitter_cfg.get("max_pages", 3),
        hours_back=int(hours_since_target),
        target_date=target_date,
    ) if user_id else []
    print(f"  Found {len(tweets)} tweets")

    # 5. Summarize tweets
    print("Summarizing tweets...")
    tweet_digest = summarize_tweets(tweets, model=model) if tweets else TweetDigest(
        paper_announcements=[], discussions=[], announcements=[], other=[]
    )
    print(f"  {len(tweet_digest.paper_announcements)} papers, {len(tweet_digest.discussions)} discussions, {len(tweet_digest.announcements)} announcements, {len(tweet_digest.other)} other")

    # 6. Fetch news headlines
    print("Fetching news headlines...")
    news_feeds = fetch_news()
    total_articles = sum(len(f.articles) for f in news_feeds)
    print(f"  {total_articles} articles from {len(news_feeds)} publications")

    # 7. Write data
    print("Writing data...")
    claude_usage = get_claude_usage()
    twitter_usage = get_twitter_usage()
    day_dir = write_daily_data(date_str, author_papers, ranked_papers, tweet_digest, news_feeds, claude_usage, twitter_usage)
    print(f"  Written to {day_dir}")

    # 8. Cost summary
    total_cost = claude_usage.estimated_cost_usd + twitter_usage.estimated_cost_usd
    print(f"\nCost summary:")
    print(f"  Claude: {claude_usage.api_calls} calls, {claude_usage.input_tokens:,} in / {claude_usage.output_tokens:,} out, ${claude_usage.estimated_cost_usd:.4f}")
    print(f"  Twitter: {twitter_usage.api_calls} calls, {twitter_usage.posts_read} posts read (${twitter_usage.posts_read * 0.005:.2f}), {twitter_usage.users_read} users read (${twitter_usage.users_read * 0.01:.2f}), total ${twitter_usage.estimated_cost_usd:.4f}")
    print(f"  Total: ${total_cost:.4f}")

    print("Done!")


if __name__ == "__main__":
    main()
