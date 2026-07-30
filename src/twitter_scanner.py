"""Fetch tweets from a home timeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
import tweepy

XQUIK_DEFAULT_BASE_URL = "https://xquik.com"
XQUIK_TIMELINE_PATH = "/api/v1/x/timeline"
TWITTER_OAUTH_ENV_NAMES = (
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_TOKEN_SECRET",
)


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
    backend: str = "twitter-api-v2"
    api_calls: int = 0
    posts_read: int = 0
    users_read: int = 0
    estimated_cost_usd: float = 0.0
    cost_estimate_available: bool = True

    # X API pay-per-use pricing (as of March 2026)
    COST_PER_POST_READ: ClassVar[float] = 0.005
    COST_PER_USER_READ: ClassVar[float] = 0.01

    def add_call(
        self,
        posts_returned: int = 0,
        users_returned: int = 0,
        estimated_cost_usd: float | None = None,
    ) -> None:
        self.api_calls += 1
        self.posts_read += posts_returned
        self.users_read += users_returned
        if estimated_cost_usd is None:
            self.estimated_cost_usd = round(
                self.posts_read * self.COST_PER_POST_READ
                + self.users_read * self.COST_PER_USER_READ,
                4,
            )
            return

        self.estimated_cost_usd = round(
            self.estimated_cost_usd + estimated_cost_usd,
            4,
        )

    def to_dict(self) -> dict[str, str | int | float | bool]:
        return {
            "backend": self.backend,
            "api_calls": self.api_calls,
            "posts_read": self.posts_read,
            "users_read": self.users_read,
            "estimated_cost_usd": self.estimated_cost_usd,
            "cost_estimate_available": self.cost_estimate_available,
        }


# Module-level usage tracker
usage = TwitterUsageStats()


def reset_usage() -> None:
    global usage
    usage = TwitterUsageStats()


def get_usage() -> TwitterUsageStats:
    return usage


def _get_client() -> tweepy.Client:
    """Create a Tweepy client with OAuth 1.0a user authentication."""
    return tweepy.Client(
        consumer_key=os.environ.get("TWITTER_API_KEY", ""),
        consumer_secret=os.environ.get("TWITTER_API_SECRET", ""),
        access_token=os.environ.get("TWITTER_ACCESS_TOKEN", ""),
        access_token_secret=os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", ""),
        wait_on_rate_limit=True,
    )


def _missing_twitter_oauth_credentials() -> list[str]:
    return [name for name in TWITTER_OAUTH_ENV_NAMES if not os.environ.get(name)]


def _extract_urls(tweet_data: Any) -> list[str]:
    """Extract URLs from Twitter API tweet entities."""
    urls: list[str] = []
    entities = getattr(tweet_data, "entities", None) or {}
    for url_obj in entities.get("urls", []):
        expanded = url_obj.get("expanded_url", "")
        if expanded:
            urls.append(expanded)
    return urls


def _tweet_url(username: str, tweet_id: str) -> str:
    return f"https://x.com/{username}/status/{tweet_id}"


def _xquik_api_key() -> str:
    return os.environ.get("XQUIK_API_KEY", "").strip()


def _xquik_headers(api_key: str) -> dict[str, str]:
    return {
        "accept": "application/json",
        "x-api-key": api_key,
    }


def _xquik_base_url() -> str:
    """Return the configured Xquik base URL or the public default."""
    configured_url = os.environ.get("XQUIK_BASE_URL", "").strip()
    if not configured_url:
        return XQUIK_DEFAULT_BASE_URL

    parsed_url = urlsplit(configured_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.netloc
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path not in {"", "/"}
        or parsed_url.query
        or parsed_url.fragment
    ):
        print("Warning: Invalid XQUIK_BASE_URL; using the public endpoint")
        return XQUIK_DEFAULT_BASE_URL
    return configured_url.rstrip("/")


def _parse_created_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_xquik_urls(item: dict[str, Any]) -> list[str]:
    entities = item.get("entities")
    if not isinstance(entities, dict):
        return []

    raw_urls = entities.get("urls")
    if not isinstance(raw_urls, list):
        return []

    urls: list[str] = []
    for raw_url in raw_urls:
        if not isinstance(raw_url, dict):
            continue
        url = raw_url.get("expanded_url") or raw_url.get("url")
        if isinstance(url, str) and url:
            urls.append(url)
    return urls


def _xquik_metric(item: dict[str, Any], name: str) -> int:
    value = item.get(name, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _normalize_xquik_tweet(item: dict[str, Any]) -> Tweet | None:
    raw_tweet_id = item.get("id")
    if not isinstance(raw_tweet_id, (int, str)) or isinstance(raw_tweet_id, bool):
        return None

    tweet_id = str(raw_tweet_id)
    if not tweet_id:
        return None

    author = item.get("author")
    if isinstance(author, dict):
        raw_username = author.get("username")
        username = (
            raw_username.lstrip("@")
            if isinstance(raw_username, str) and raw_username
            else "unknown"
        )
        raw_name = author.get("name")
        name = raw_name if isinstance(raw_name, str) and raw_name else username
    else:
        username = "unknown"
        name = "Unknown"

    raw_text = item.get("text")
    raw_url = item.get("url")
    return Tweet(
        tweet_id=tweet_id,
        text=raw_text if isinstance(raw_text, str) else "",
        author_username=username,
        author_name=name,
        created_at=_parse_created_at(item.get("createdAt")),
        likes=_xquik_metric(item, "likeCount"),
        retweets=_xquik_metric(item, "retweetCount"),
        url=(
            raw_url
            if isinstance(raw_url, str) and raw_url
            else _tweet_url(username, tweet_id)
        ),
        urls_in_tweet=_extract_xquik_urls(item),
    )


def _date_window(
    hours_back: int,
    target_date: datetime | None,
    *,
    twitter_delay_seconds: int = 0,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if target_date and target_date.date() < now.date():
        start_time = target_date.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        else:
            start_time = start_time.astimezone(timezone.utc)
        return start_time, start_time + timedelta(hours=24)

    end_time = now - timedelta(seconds=twitter_delay_seconds)
    return end_time - timedelta(hours=hours_back), end_time


def _parse_xquik_page(
    payload: Any,
) -> tuple[list[dict[str, Any]], bool, str | None, int]:
    if not isinstance(payload, dict):
        raise TypeError("unexpected response shape")

    raw_tweets = payload.get("tweets")
    if not isinstance(raw_tweets, list):
        raise TypeError("timeline response has no tweets list")

    tweets = [item for item in raw_tweets if isinstance(item, dict)]
    has_next_page = payload.get("has_next_page") is True
    raw_cursor = payload.get("next_cursor")
    next_cursor = raw_cursor if isinstance(raw_cursor, str) and raw_cursor else None
    return tweets, has_next_page, next_cursor, len(raw_tweets)


def _fetch_tweets_with_xquik(
    max_pages: int,
    hours_back: int,
    target_date: datetime | None = None,
) -> list[Tweet]:
    """Fetch home-timeline tweets through Xquik's documented read endpoint."""
    api_key = _xquik_api_key()
    if not api_key:
        return []

    usage.backend = "xquik"
    usage.cost_estimate_available = False
    start_time, end_time = _date_window(hours_back, target_date)
    tweets: list[Tweet] = []
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None

    with httpx.Client(timeout=30, headers=_xquik_headers(api_key)) as client:
        for page in range(max_pages):
            params = {"cursor": cursor} if cursor else {}

            try:
                response = client.get(
                    f"{_xquik_base_url()}{XQUIK_TIMELINE_PATH}",
                    params=params,
                )
                response.raise_for_status()
                items, has_next_page, next_cursor, posts_returned = _parse_xquik_page(
                    response.json()
                )
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                print(f"Warning: Xquik timeline fetch failed: {exc}")
                break

            usage.add_call(
                posts_returned=posts_returned,
                estimated_cost_usd=0.0,
            )
            print(f"  Xquik page {page + 1}: {posts_returned} posts")

            for item in items:
                tweet = _normalize_xquik_tweet(item)
                if tweet is None or tweet.tweet_id in seen_ids:
                    continue
                if tweet.created_at and not (
                    start_time <= tweet.created_at <= end_time
                ):
                    continue
                seen_ids.add(tweet.tweet_id)
                tweets.append(tweet)

            if not has_next_page or next_cursor is None or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    tweets.sort(key=lambda tweet: tweet.likes + tweet.retweets, reverse=True)
    return tweets


def fetch_tweets(
    user_id: str,
    max_pages: int = 3,
    hours_back: int = 24,
    target_date: datetime | None = None,
    backend: str = "auto",
) -> list[Tweet]:
    """Fetch the user's home timeline in reverse chronological order.

    Auto mode uses Xquik when XQUIK_API_KEY is set. Otherwise, it uses the
    Twitter API v2 home-timeline endpoint with OAuth 1.0a.
    """
    selected_backend = backend.lower() if isinstance(backend, str) else "auto"
    if selected_backend not in {"auto", "xquik", "twitter-api-v2"}:
        print(f"Warning: Unknown Twitter backend {backend!r}, using auto")
        selected_backend = "auto"

    if selected_backend in {"auto", "xquik"} and _xquik_api_key():
        return _fetch_tweets_with_xquik(max_pages, hours_back, target_date)
    if selected_backend == "xquik":
        print("Warning: No XQUIK_API_KEY set, skipping Xquik integration")
        return []

    missing_credentials = _missing_twitter_oauth_credentials()
    if missing_credentials:
        missing = ", ".join(missing_credentials)
        print(f"Warning: Incomplete Twitter OAuth configuration; missing {missing}")
        return []

    usage.backend = "twitter-api-v2"
    client = _get_client()
    start_time, end_time = _date_window(
        hours_back,
        target_date,
        twitter_delay_seconds=30,
    )

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

            # Only count post reads. User data from expansions is included free.
            usage.add_call(posts_returned=posts_returned)
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

            meta = resp.meta or {}
            pagination_token = meta.get("next_token")
            if not pagination_token:
                break

        except tweepy.errors.TweepyException as exc:
            print(f"Warning: Home timeline fetch failed: {exc}")
            break

    tweets.sort(key=lambda tweet: tweet.likes + tweet.retweets, reverse=True)
    return tweets
