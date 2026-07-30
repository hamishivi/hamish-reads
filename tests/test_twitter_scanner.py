import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import httpx

from src import twitter_scanner


class FakeResponse:
    def __init__(self, payload, *, json_error=None, http_error=None):
        self._payload = payload
        self._json_error = json_error
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error:
            raise self._http_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeHttpxClient:
    responses: ClassVar[list[FakeResponse]] = []
    calls: ClassVar[list[tuple[str, dict, dict, int]]] = []

    def __init__(self, timeout, headers):
        self.timeout = timeout
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def get(self, url, params):
        self.calls.append((url, params, self.headers, self.timeout))
        return self.responses.pop(0)


def xquik_tweet(
    tweet_id,
    *,
    created_at="2026-05-25T08:00:00Z",
    likes=10,
    retweets=3,
):
    return {
        "id": tweet_id,
        "text": "New AI paper thread",
        "author": {"username": "alice", "name": "Alice"},
        "createdAt": created_at,
        "likeCount": likes,
        "retweetCount": retweets,
        "url": f"https://x.com/alice/status/{tweet_id}",
        "entities": {
            "urls": [
                {
                    "expanded_url": "https://arxiv.org/abs/1234.56789",
                    "url": "https://t.co/example",
                }
            ]
        },
    }


class TwitterScannerTest(unittest.TestCase):
    def setUp(self):
        self._environment = patch.dict(os.environ, {}, clear=True)
        self._environment.start()
        FakeHttpxClient.responses = []
        FakeHttpxClient.calls = []
        twitter_scanner.reset_usage()

    def tearDown(self):
        twitter_scanner.reset_usage()
        self._environment.stop()

    def test_fetch_tweets_uses_documented_xquik_contract(self):
        os.environ["XQUIK_API_KEY"] = "xq_test"
        os.environ["XQUIK_BASE_URL"] = "https://example.test"
        FakeHttpxClient.responses = [
            FakeResponse(
                {
                    "tweets": [xquik_tweet("123")],
                    "has_next_page": False,
                    "next_cursor": "",
                }
            )
        ]

        with patch("src.twitter_scanner.httpx.Client", FakeHttpxClient):
            tweets = twitter_scanner.fetch_tweets(
                user_id="",
                max_pages=1,
                hours_back=24,
                target_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
            )

        usage = twitter_scanner.get_usage()
        self.assertEqual(len(tweets), 1)
        self.assertEqual(tweets[0].tweet_id, "123")
        self.assertEqual(tweets[0].author_username, "alice")
        self.assertEqual(tweets[0].likes, 10)
        self.assertEqual(tweets[0].retweets, 3)
        self.assertEqual(
            tweets[0].urls_in_tweet,
            ["https://arxiv.org/abs/1234.56789"],
        )
        self.assertEqual(usage.backend, "xquik")
        self.assertEqual(usage.api_calls, 1)
        self.assertEqual(usage.posts_read, 1)
        self.assertFalse(usage.cost_estimate_available)
        self.assertEqual(
            FakeHttpxClient.calls[0][0],
            "https://example.test/api/v1/x/timeline",
        )
        self.assertEqual(FakeHttpxClient.calls[0][1], {})
        self.assertEqual(FakeHttpxClient.calls[0][2]["x-api-key"], "xq_test")
        self.assertNotIn("authorization", FakeHttpxClient.calls[0][2])

    def test_xquik_paginates_empty_pages_and_filters_date_window(self):
        os.environ["XQUIK_API_KEY"] = "xq_test"
        FakeHttpxClient.responses = [
            FakeResponse(
                {
                    "tweets": [],
                    "has_next_page": True,
                    "next_cursor": "page-2",
                }
            ),
            FakeResponse(
                {
                    "tweets": [
                        xquik_tweet("in-window", likes=1, retweets=1),
                        xquik_tweet(
                            "out-of-window",
                            created_at="2026-05-24T23:59:59Z",
                            likes=100,
                            retweets=100,
                        ),
                    ],
                    "has_next_page": False,
                    "next_cursor": "",
                }
            ),
        ]

        with patch("src.twitter_scanner.httpx.Client", FakeHttpxClient):
            tweets = twitter_scanner.fetch_tweets(
                user_id="",
                max_pages=2,
                target_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
            )

        self.assertEqual([tweet.tweet_id for tweet in tweets], ["in-window"])
        self.assertEqual(
            [call[1] for call in FakeHttpxClient.calls],
            [{}, {"cursor": "page-2"}],
        )
        self.assertEqual(twitter_scanner.get_usage().api_calls, 2)
        self.assertEqual(twitter_scanner.get_usage().posts_read, 2)

    def test_empty_xquik_base_url_uses_public_default(self):
        os.environ["XQUIK_API_KEY"] = "xq_test"
        os.environ["XQUIK_BASE_URL"] = ""
        FakeHttpxClient.responses = [
            FakeResponse(
                {
                    "tweets": [],
                    "has_next_page": False,
                    "next_cursor": "",
                }
            )
        ]

        with patch("src.twitter_scanner.httpx.Client", FakeHttpxClient):
            twitter_scanner.fetch_tweets(user_id="", max_pages=1)

        self.assertEqual(
            FakeHttpxClient.calls[0][0],
            "https://xquik.com/api/v1/x/timeline",
        )

    def test_unsafe_xquik_base_url_uses_public_default(self):
        os.environ["XQUIK_API_KEY"] = "xq_test"
        os.environ["XQUIK_BASE_URL"] = "http://example.test"
        FakeHttpxClient.responses = [
            FakeResponse(
                {
                    "tweets": [],
                    "has_next_page": False,
                    "next_cursor": "",
                }
            )
        ]

        with patch("src.twitter_scanner.httpx.Client", FakeHttpxClient):
            twitter_scanner.fetch_tweets(user_id="", max_pages=1)

        self.assertEqual(
            FakeHttpxClient.calls[0][0],
            "https://xquik.com/api/v1/x/timeline",
        )

    def test_xquik_json_parse_failure_returns_empty_results(self):
        os.environ["XQUIK_API_KEY"] = "xq_test"
        FakeHttpxClient.responses = [
            FakeResponse({}, json_error=ValueError("invalid json"))
        ]

        with patch("src.twitter_scanner.httpx.Client", FakeHttpxClient):
            tweets = twitter_scanner.fetch_tweets(user_id="", max_pages=1)

        self.assertEqual(tweets, [])
        self.assertEqual(twitter_scanner.get_usage().api_calls, 0)

    def test_xquik_http_failure_returns_empty_results(self):
        os.environ["XQUIK_API_KEY"] = "xq_test"
        request = httpx.Request("GET", "https://xquik.com/api/v1/x/timeline")
        response = httpx.Response(502, request=request)
        FakeHttpxClient.responses = [
            FakeResponse(
                {},
                http_error=httpx.HTTPStatusError(
                    "upstream failure",
                    request=request,
                    response=response,
                ),
            )
        ]

        with patch("src.twitter_scanner.httpx.Client", FakeHttpxClient):
            tweets = twitter_scanner.fetch_tweets(user_id="", max_pages=1)

        self.assertEqual(tweets, [])
        self.assertEqual(twitter_scanner.get_usage().api_calls, 0)

    def test_xquik_rejects_an_unexpected_response_shape(self):
        os.environ["XQUIK_API_KEY"] = "xq_test"
        FakeHttpxClient.responses = [FakeResponse(["not", "an", "object"])]

        with patch("src.twitter_scanner.httpx.Client", FakeHttpxClient):
            tweets = twitter_scanner.fetch_tweets(user_id="", max_pages=1)

        self.assertEqual(tweets, [])
        self.assertEqual(twitter_scanner.get_usage().api_calls, 0)

    def test_partial_twitter_oauth_configuration_skips_request(self):
        complete_environment = {
            "TWITTER_API_KEY": "key",
            "TWITTER_API_SECRET": "secret",
            "TWITTER_ACCESS_TOKEN": "token",
            "TWITTER_ACCESS_TOKEN_SECRET": "token-secret",
        }

        for missing_name in twitter_scanner.TWITTER_OAUTH_ENV_NAMES:
            with self.subTest(missing_name=missing_name):
                os.environ.clear()
                os.environ.update(complete_environment)
                del os.environ[missing_name]
                with patch("src.twitter_scanner._get_client") as get_client:
                    tweets = twitter_scanner.fetch_tweets(
                        user_id="user",
                        max_pages=1,
                        backend="twitter-api-v2",
                    )

                self.assertEqual(tweets, [])
                get_client.assert_not_called()

    def test_complete_twitter_oauth_configuration_uses_existing_backend(self):
        os.environ.update(
            {
                "TWITTER_API_KEY": "key",
                "TWITTER_API_SECRET": "secret",
                "TWITTER_ACCESS_TOKEN": "token",
                "TWITTER_ACCESS_TOKEN_SECRET": "token-secret",
            }
        )
        client = SimpleNamespace()
        client.get_home_timeline = lambda **kwargs: SimpleNamespace(
            data=None,
            includes=None,
            meta=None,
        )

        with patch(
            "src.twitter_scanner._get_client", return_value=client
        ) as get_client:
            tweets = twitter_scanner.fetch_tweets(
                user_id="user",
                max_pages=1,
                backend="twitter-api-v2",
            )

        self.assertEqual(tweets, [])
        get_client.assert_called_once_with()
        self.assertEqual(twitter_scanner.get_usage().backend, "twitter-api-v2")
        self.assertEqual(twitter_scanner.get_usage().api_calls, 1)

    def test_explicit_xquik_backend_does_not_fall_back_without_key(self):
        os.environ.update(
            {
                "TWITTER_API_KEY": "key",
                "TWITTER_API_SECRET": "secret",
                "TWITTER_ACCESS_TOKEN": "token",
                "TWITTER_ACCESS_TOKEN_SECRET": "token-secret",
            }
        )

        with patch("src.twitter_scanner._get_client") as get_client:
            tweets = twitter_scanner.fetch_tweets(
                user_id="user",
                backend="xquik",
            )

        self.assertEqual(tweets, [])
        get_client.assert_not_called()

    def test_normalize_xquik_tweet_uses_safe_defaults(self):
        tweet = twitter_scanner._normalize_xquik_tweet(
            {
                "id": 456,
                "text": "Digest item",
                "createdAt": "invalid",
                "likeCount": "4",
                "retweetCount": True,
            }
        )

        self.assertIsNotNone(tweet)
        self.assertEqual(tweet.tweet_id, "456")
        self.assertEqual(tweet.author_username, "unknown")
        self.assertEqual(tweet.url, "https://x.com/unknown/status/456")
        self.assertEqual(tweet.likes, 0)
        self.assertEqual(tweet.retweets, 0)
        self.assertIsNone(tweet.created_at)


if __name__ == "__main__":
    unittest.main()
