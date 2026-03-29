"""Fetch tweets from your home timeline using OAuth 1.0a user auth."""

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
    posts_read: int = 0
    users_read: int = 0
    estimated_cost_usd: float = 0.0

    # X API pay-per-use pricing (as of March 2026)
    COST_PER_POST_READ: float = 0.005
    COST_PER_USER_READ: float = 0.01

    def add_call(self, posts_returned: int = 0, users_returned: int = 0):
        self.api_calls += 1
        self.posts_read += posts_returned
        self.users_read += users_returned
        self.estimated_cost_usd = round(
            self.posts_read * self.COST_PER_POST_READ
            + self.users_read * self.COST_PER_USER_READ,
            4,
        )

    def to_dict(self) -> dict:
        return {
            "api_calls": self.api_calls,
            "posts_read": self.posts_read,
            "users_read": self.users_read,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


# Module-level usage tracker
usage = TwitterUsageStats()


def reset_usage():
    global usage
    usage = TwitterUsageStats()


def get_usage() -> TwitterUsageStats:
    return usage


def _get_client() -> tweepy.Client:
    """Create a tweepy client with OAuth 1.0a user auth (needed for home timeline)."""
    return tweepy.Client(
        consumer_key=os.environ.get("TWITTER_API_KEY", ""),
        consumer_secret=os.environ.get("TWITTER_API_SECRET", ""),
        access_token=os.environ.get("TWITTER_ACCESS_TOKEN", ""),
        access_token_secret=os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", ""),
        wait_on_rate_limit=True,
    )


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
    max_pages: int = 3,
    hours_back: int = 24,
    target_date: datetime | None = None,
) -> list[Tweet]:
    """Fetch tweets from the user's home timeline (reverse chronological).

    Uses the home timeline endpoint which returns tweets from accounts
    you follow — like the "Following" tab on X. Much cheaper than
    search (no per-user cost, just post reads).

    Cost: ~$0.005 × posts_read. 3 pages × 100 = $1.50.
    """
    # Check for OAuth credentials
    if not os.environ.get("TWITTER_API_KEY"):
        print("Warning: No TWITTER_API_KEY set, skipping Twitter integration")
        return []

    client = _get_client()

    now = datetime.now(timezone.utc)
    if target_date and target_date.date() < now.date():
        start_time = target_date.replace(hour=0, minute=0, second=0)
        end_time = start_time + timedelta(hours=24)
    else:
        end_time = now - timedelta(seconds=30)
        start_time = end_time - timedelta(hours=hours_back)

    seen_ids: set[str] = set()
    tweets: list[Tweet] = []
    user_map: dict[str, tuple[str, str]] = {}
    pagination_token = None

    for page in range(max_pages):
        try:
            resp = client.get_home_timeline(
                max_results=100,
                start_time=start_time,
                end_time=end_time,
                tweet_fields=["public_metrics", "created_at", "entities", "author_id"],
                expansions=["author_id"],
                user_fields=["username", "name"],
                pagination_token=pagination_token,
            )

            posts_returned = len(resp.data) if resp.data else 0
            # Count users from expansions (only new ones)
            new_users = 0
            if resp.includes and "users" in resp.includes:
                for user in resp.includes["users"]:
                    uid = str(user.id)
                    if uid not in user_map:
                        user_map[uid] = (user.username, user.name)
                        new_users += 1

            usage.add_call(posts_returned=posts_returned, users_returned=new_users)
            print(f"  Page {page + 1}: {posts_returned} posts, {new_users} new users")

            if not resp.data:
                break

            for tweet_data in resp.data:
                tid = str(tweet_data.id)
                if tid in seen_ids:
                    continue

                metrics = tweet_data.public_metrics or {}
                likes = metrics.get("like_count", 0)
                retweets = metrics.get("retweet_count", 0)

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

            # Check for next page
            meta = resp.meta or {}
            pagination_token = meta.get("next_token")
            if not pagination_token:
                break

        except tweepy.errors.TweepyException as e:
            print(f"Warning: Home timeline fetch failed: {e}")
            break

    # Sort by engagement
    tweets.sort(key=lambda t: t.likes + t.retweets, reverse=True)
    return tweets
