"""Fetch tweets from your following list, including their likes and retweets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import tweepy


@dataclass
class Tweet:
    tweet_id: str
    text: str
    author_username: str
    author_name: str
    created_at: datetime | None
    likes: int
    retweets: int
    url: str
    urls_in_tweet: list[str]


def _get_client(bearer_token: str | None = None) -> tweepy.Client:
    token = bearer_token or os.environ.get("TWITTER_BEARER_TOKEN", "")
    return tweepy.Client(bearer_token=token, wait_on_rate_limit=True)


def _extract_urls(tweet_data) -> list[str]:
    """Extract URLs from tweet entities."""
    urls = []
    entities = getattr(tweet_data, "entities", None) or {}
    for url_obj in entities.get("urls", []):
        expanded = url_obj.get("expanded_url", "")
        if expanded:
            urls.append(expanded)
    return urls


def _tweet_url(username: str, tweet_id: str) -> str:
    return f"https://x.com/{username}/status/{tweet_id}"


def fetch_tweets(
    user_id: str,
    min_engagement: int = 10,
    hours_back: int = 24,
    bearer_token: str | None = None,
) -> list[Tweet]:
    """Fetch recent tweets from accounts the user follows, plus their liked/retweeted content."""
    token = bearer_token or os.environ.get("TWITTER_BEARER_TOKEN", "")
    if not token:
        print("Warning: No TWITTER_BEARER_TOKEN set, skipping Twitter integration")
        return []

    client = _get_client(token)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    seen_ids: set[str] = set()
    tweets: list[Tweet] = []

    # Build a user map for looking up usernames
    user_map: dict[str, tuple[str, str]] = {}  # user_id -> (username, name)

    # Get accounts the user follows
    try:
        following_resp = client.get_users_following(
            id=user_id,
            max_results=200,
            user_fields=["username", "name"],
        )
        if not following_resp.data:
            print("Warning: No following data returned from Twitter API")
            return []

        for user in following_resp.data:
            user_map[str(user.id)] = (user.username, user.name)

    except tweepy.errors.TweepyException as e:
        print(f"Warning: Failed to fetch following list: {e}")
        return []

    # Fetch recent tweets from followed accounts
    # Twitter API v2 search supports "from:" operators
    following_usernames = [u for u, _ in user_map.values()]

    # Process in batches (search query has length limits)
    batch_size = 20
    for i in range(0, len(following_usernames), batch_size):
        batch = following_usernames[i : i + batch_size]
        query = " OR ".join(f"from:{u}" for u in batch)
        query += " -is:reply"  # exclude replies to reduce noise

        try:
            search_resp = client.search_recent_tweets(
                query=query,
                max_results=100,
                start_time=cutoff,
                tweet_fields=["public_metrics", "created_at", "entities", "author_id"],
                expansions=["author_id"],
                user_fields=["username", "name"],
            )

            # Build user map from expansions
            if search_resp.includes and "users" in search_resp.includes:
                for user in search_resp.includes["users"]:
                    user_map[str(user.id)] = (user.username, user.name)

            if not search_resp.data:
                continue

            for tweet_data in search_resp.data:
                tid = str(tweet_data.id)
                if tid in seen_ids:
                    continue

                metrics = tweet_data.public_metrics or {}
                likes = metrics.get("like_count", 0)
                retweets = metrics.get("retweet_count", 0)

                if likes + retweets < min_engagement:
                    continue

                seen_ids.add(tid)
                author_id = str(tweet_data.author_id)
                username, name = user_map.get(author_id, ("unknown", "Unknown"))

                tweets.append(
                    Tweet(
                        tweet_id=tid,
                        text=tweet_data.text,
                        author_username=username,
                        author_name=name,
                        created_at=tweet_data.created_at,
                        likes=likes,
                        retweets=retweets,
                        url=_tweet_url(username, tid),
                        urls_in_tweet=_extract_urls(tweet_data),
                    )
                )

        except tweepy.errors.TweepyException as e:
            print(f"Warning: Twitter search failed for batch: {e}")
            continue

    # Sort by engagement
    tweets.sort(key=lambda t: t.likes + t.retweets, reverse=True)
    return tweets
