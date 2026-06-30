"""Use OpenAI to rank papers by relevance and summarize tweets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .arxiv_scanner import Paper
from .notion_client import ProjectTopic
from .twitter_scanner import Tweet

# Pricing per million tokens.
MODEL_PRICING = {
    "gpt-5.5": {"input": 5.00, "output": 30.00},
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "output": 1.25},
}
DEFAULT_PRICING = MODEL_PRICING["gpt-5.4"]
DEFAULT_MODEL = "gpt-5.4"


@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 0
    estimated_cost_usd: float = 0.0

    def add(self, response: Any, model: str):
        response_usage = response.usage
        input_tokens = _usage_value(response_usage, "prompt_tokens", "input_tokens")
        output_tokens = _usage_value(response_usage, "completion_tokens", "output_tokens")

        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.api_calls += 1

        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
        self.estimated_cost_usd += (
            input_tokens * pricing["input"] / 1_000_000
            + output_tokens * pricing["output"] / 1_000_000
        )

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "api_calls": self.api_calls,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
        }


@dataclass
class TweetDigest:
    paper_announcements: list[dict] = field(default_factory=list)
    discussions: list[dict] = field(default_factory=list)
    announcements: list[dict] = field(default_factory=list)
    other: list[dict] = field(default_factory=list)


# Module-level usage tracker, reset each run.
usage = UsageStats()


def reset_usage():
    global usage
    usage = UsageStats()


def get_usage() -> UsageStats:
    return usage


def _usage_value(response_usage: Any, *names: str) -> int:
    for name in names:
        value = getattr(response_usage, name, None)
        if value is not None:
            return int(value)
    return 0


def _get_client() -> OpenAI | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Warning: OPENAI_API_KEY is not set; skipping OpenAI ranking/summarization.")
        return None
    return OpenAI(api_key=api_key)


def _create_completion(client: OpenAI, model: str, prompt: str):
    return client.chat.completions.create(
        model=model,
        max_completion_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )


def _response_text(response: Any) -> str:
    content = response.choices[0].message.content
    if isinstance(content, list):
        return "".join(part.text for part in content if getattr(part, "text", None))
    return content or ""


def _parse_json_response(text: str):
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def rank_papers(
    papers: list[Paper],
    project_topics: list[ProjectTopic],
    model: str = DEFAULT_MODEL,
    max_results: int = 20,
) -> list[Paper]:
    """Score papers by relevance to current project topics using OpenAI."""
    if not papers or not project_topics:
        return []

    client = _get_client()
    if not client:
        return []

    # Format project topics.
    topics_text = "\n".join(
        f"- **{t.name}**: {t.description[:500]}" for t in project_topics
    )

    # Process in batches of 30 to stay within context limits.
    batch_size = 30
    all_scored: list[tuple[str, float, str]] = []

    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]

        papers_text = "\n\n".join(
            f"[{p.arxiv_id}] {p.title}\nAuthors: {', '.join(p.authors[:5])}\nAbstract: {p.abstract[:400]}"
            for p in batch
        )

        prompt = f"""You are a research paper relevance ranker. Score each paper's relevance (0-10) to these current research projects, and give a one-sentence reason.

## Current Projects
{topics_text}

## Papers
{papers_text}

Return ONLY valid JSON - an array of objects:
[{{"arxiv_id": "...", "score": N, "reason": "..."}}]

Only include papers with score >= 3. Be selective."""

        response = _create_completion(client, model, prompt)
        usage.add(response, model)

        try:
            scored = _parse_json_response(_response_text(response))
            for item in scored:
                all_scored.append(
                    (item["arxiv_id"], float(item["score"]), item["reason"])
                )
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            print(f"Warning: Failed to parse OpenAI ranking response: {e}")
            continue

    # Map scores back to papers.
    score_map = {arxiv_id: (score, reason) for arxiv_id, score, reason in all_scored}
    for paper in papers:
        if paper.arxiv_id in score_map:
            paper.relevance_score, paper.relevance_reason = score_map[paper.arxiv_id]

    ranked = [p for p in papers if p.relevance_score >= 3.0]
    ranked.sort(key=lambda p: p.relevance_score, reverse=True)
    return ranked[:max_results]


def summarize_tweets(
    tweets: list[Tweet],
    model: str = DEFAULT_MODEL,
) -> TweetDigest:
    """Categorize and summarize tweets into paper threads, announcements, and discussions."""
    if not tweets:
        return TweetDigest()

    client = _get_client()
    if not client:
        return TweetDigest()

    tweets_text = "\n\n".join(
        f"[@{t.author_username}] ({t.url})\n{t.text[:400]}\nLikes: {t.likes}, RTs: {t.retweets}"
        for t in tweets
    )

    prompt = f"""Categorize and summarize these tweets into four categories:

1. **paper_announcements**: Tweets announcing new papers, models, or datasets. This includes authors sharing their own new work AND announcements of new model/dataset releases (e.g. "We release X", "Our new paper on X", "Introducing X dataset"). If it links to arxiv, huggingface, or a blog post announcing new work, it likely belongs here.
2. **discussions**: AI/ML-related discussions ONLY - opinions, debates, commentary on papers or methods, technical threads, hot takes, observations about AI/ML. NOT paper announcements.
3. **announcements**: AI/ML-specific product launches, company news, hiring, events, benchmark results, tool releases that aren't papers/models/datasets. ONLY AI/ML related - videogames, anime, pop culture, etc. go in other.
4. **other**: Anything NOT about AI/ML - politics, culture, humor, personal updates, videogames, anime, other fields.

For each entry, provide a 1-2 sentence summary and the original tweet URL.

## Tweets
{tweets_text}

Return ONLY valid JSON:
{{
  "paper_announcements": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}],
  "discussions": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}],
  "announcements": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}],
  "other": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}]
}}"""

    response = _create_completion(client, model, prompt)
    usage.add(response, model)

    try:
        result = _parse_json_response(_response_text(response))
        return TweetDigest(
            paper_announcements=result.get("paper_announcements", []),
            discussions=result.get("discussions", []),
            announcements=result.get("announcements", []),
            other=result.get("other", []),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Warning: Failed to parse OpenAI tweet summary: {e}")
        return TweetDigest()
