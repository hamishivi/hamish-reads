"""Fetch tweets from your following list, including their likes and retweets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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


@dataclass
class TwitterUsageStats:
    api_calls: int = 0
    tweets_read: int = 0
    # Credit costs per endpoint (configurable — check your X Developer Console)
    # Defaults based on pay-as-you-go tier: ~50 credits for bulk, ~25 for search
    credits_used: int = 0
    estimated_cost_usd: float = 0.0

    # Approximate $/credit — adjust based on your plan
    COST_PER_CREDIT: float = 0.0002  # ~$0.01 per 50-credit call

    def add_call(self, endpoint: str, items_returned: int = 0):
        self.api_calls += 1
        if endpoint == "get_users_following":
            credits = 50
        elif endpoint == "search_recent_tweets":
            credits = 25
        else:
            credits = 10
        self.credits_used += credits
        self.estimated_cost_usd = round(self.credits_used * self.COST_PER_CREDIT, 4)
        self.tweets_read += items_returned

    def to_dict(self) -> dict:
        return {
            "api_calls": self.api_calls,
            "tweets_read": self.tweets_read,
            "credits_used": self.credits_used,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


# Module-level usage tracker
usage = TwitterUsageStats()


def reset_usage():
    global usage
    usage = TwitterUsageStats()


def get_usage() -> TwitterUsageStats:
    return usage


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


def _build_query_batches(usernames: list[str], max_len: int, suffix: str) -> list[str]:
    """Build query strings that each fit within max_len characters.

    Each query looks like: (from:user1 OR from:user2 OR ...) -is:reply
    """
    batches = []
    current_parts: list[str] = []
    # Account for "(" prefix and suffix
    overhead = len("(") + len(suffix)

    for username in usernames:
        part = f"from:{username}"
        # Calculate what the query would be if we add this user
        if current_parts:
            candidate = "(" + " OR ".join(current_parts + [part]) + suffix
        else:
            candidate = "(" + part + suffix

        if len(candidate) > max_len and current_parts:
            # Flush current batch
            batches.append("(" + " OR ".join(current_parts) + suffix)
            current_parts = [part]
        else:
            current_parts.append(part)

    if current_parts:
        batches.append("(" + " OR ".join(current_parts) + suffix)

    return batches


def fetch_tweets(
    user_id: str,
    min_engagement: int = 10,
    hours_back: int = 24,
    bearer_token: str | None = None,
    target_date: datetime | None = None,
) -> list[Tweet]:
    """Fetch recent tweets from accounts the user follows, plus their liked/retweeted content."""
    token = bearer_token or os.environ.get("TWITTER_BEARER_TOKEN", "")
    if not token:
        print("Warning: No TWITTER_BEARER_TOKEN set, skipping Twitter integration")
        return []

    client = _get_client(token)

    now = datetime.now(timezone.utc)
    if target_date and target_date.date() < now.date():
        # Backfill: 24h window for that day
        start_time = target_date.replace(hour=0, minute=0, second=0)
        end_time = start_time + timedelta(hours=24)
    else:
        # end_time must be at least 10 seconds in the past per Twitter API
        end_time = now - timedelta(seconds=30)
        start_time = end_time - timedelta(hours=hours_back)
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
        usage.add_call("get_users_following", 0)

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

    # Build batches that fit within Twitter's 512 char query limit
    suffix = ") -is:reply"
    max_query_len = 512
    batches = _build_query_batches(following_usernames, max_query_len, suffix)

    for query in batches:

        try:
            search_resp = client.search_recent_tweets(
                query=query,
                max_results=100,
                start_time=start_time,
                end_time=end_time,
                tweet_fields=["public_metrics", "created_at", "entities", "author_id"],
                expansions=["author_id"],
                user_fields=["username", "name"],
            )
            items_returned = len(search_resp.data) if search_resp.data else 0
            usage.add_call("search_recent_tweets", items_returned)

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
            print(f"Warning: Twitter search failed for batch (query len={len(query)}): {e}")
            continue

    # Sort by engagement
    tweets.sort(key=lambda t: t.likes + t.retweets, reverse=True)
    return tweets
