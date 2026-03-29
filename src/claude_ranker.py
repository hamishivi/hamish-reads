"""Use Claude to rank papers by relevance and summarize tweets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import anthropic

from .arxiv_scanner import Paper
from .notion_client import ProjectTopic
from .twitter_scanner import Tweet

# Pricing per million tokens (as of 2025)
MODEL_PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6-20250528": {"input": 15.00, "output": 75.00},
}
DEFAULT_PRICING = {"input": 3.00, "output": 15.00}  # fallback to sonnet pricing


@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 0
    estimated_cost_usd: float = 0.0

    def add(self, response, model: str):
        usage = response.usage
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.api_calls += 1

        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
        self.estimated_cost_usd += (
            usage.input_tokens * pricing["input"] / 1_000_000
            + usage.output_tokens * pricing["output"] / 1_000_000
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


# Module-level usage tracker, reset each run
usage = UsageStats()


def reset_usage():
    global usage
    usage = UsageStats()


def get_usage() -> UsageStats:
    return usage


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def rank_papers(
    papers: list[Paper],
    project_topics: list[ProjectTopic],
    model: str = "claude-sonnet-4-20250514",
    max_results: int = 20,
) -> list[Paper]:
    """Score papers by relevance to current project topics using Claude."""
    if not papers or not project_topics:
        return []

    client = _get_client()

    # Format project topics
    topics_text = "\n".join(
        f"- **{t.name}**: {t.description[:500]}" for t in project_topics
    )

    # Process in batches of 30 to stay within context limits
    batch_size = 30
    all_scored: list[tuple[str, float, str]] = []

    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]

        papers_text = "\n\n".join(
            f"[{p.arxiv_id}] {p.title}\nAuthors: {', '.join(p.authors[:5])}\nAbstract: {p.abstract[:400]}"
            for p in batch
        )

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"""You are a research paper relevance ranker. Score each paper's relevance (0-10) to these current research projects, and give a one-sentence reason.

## Current Projects
{topics_text}

## Papers
{papers_text}

Return ONLY valid JSON — an array of objects:
[{{"arxiv_id": "...", "score": N, "reason": "..."}}]

Only include papers with score >= 3. Be selective.""",
                }
            ],
        )

        usage.add(response, model)

        try:
            text = response.content[0].text
            # Handle potential markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            scored = json.loads(text)
            for item in scored:
                all_scored.append(
                    (item["arxiv_id"], float(item["score"]), item["reason"])
                )
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"Warning: Failed to parse Claude ranking response: {e}")
            continue

    # Map scores back to papers
    score_map = {arxiv_id: (score, reason) for arxiv_id, score, reason in all_scored}
    for paper in papers:
        if paper.arxiv_id in score_map:
            paper.relevance_score, paper.relevance_reason = score_map[paper.arxiv_id]

    ranked = [p for p in papers if p.relevance_score >= 3.0]
    ranked.sort(key=lambda p: p.relevance_score, reverse=True)
    return ranked[:max_results]


def summarize_tweets(
    tweets: list[Tweet],
    model: str = "claude-sonnet-4-20250514",
) -> TweetDigest:
    """Categorize and summarize tweets into paper threads, announcements, and discussions."""
    if not tweets:
        return TweetDigest()

    client = _get_client()

    tweets_text = "\n\n".join(
        f"[@{t.author_username}] ({t.url})\n{t.text[:400]}\nLikes: {t.likes}, RTs: {t.retweets}"
        for t in tweets
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""Categorize and summarize these tweets into four categories:

1. **paper_announcements**: Tweets announcing new papers, models, or datasets. This includes authors sharing their own new work AND announcements of new model/dataset releases (e.g. "We release X", "Our new paper on X", "Introducing X dataset"). If it links to arxiv, huggingface, or a blog post announcing new work, it likely belongs here.
2. **discussions**: AI/ML-related discussions ONLY — opinions, debates, commentary on papers or methods, technical threads, hot takes, observations about AI/ML. NOT paper announcements.
3. **announcements**: AI/ML product launches, company news, hiring, events, benchmark results, tool releases that aren't papers/models/datasets.
4. **other**: Interesting tweets that are NOT about AI/ML — politics, culture, humor, personal updates, other fields.

For each entry, provide a 1-2 sentence summary and the original tweet URL.

## Tweets
{tweets_text}

Return ONLY valid JSON:
{{
  "paper_announcements": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}],
  "discussions": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}],
  "announcements": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}],
  "other": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}]
}}""",
            }
        ],
    )

    usage.add(response, model)

    try:
        text = response.content[0].text
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        result = json.loads(text)
        return TweetDigest(
            paper_announcements=result.get("paper_announcements", []),
            discussions=result.get("discussions", []),
            announcements=result.get("announcements", []),
            other=result.get("other", []),
        )
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Failed to parse Claude tweet summary: {e}")
        return TweetDigest()
