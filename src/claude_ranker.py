"""Use Claude to rank papers by relevance and summarize tweets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import anthropic

from .arxiv_scanner import Paper
from .notion_client import ProjectTopic
from .twitter_scanner import Tweet


@dataclass
class TweetDigest:
    paper_threads: list[dict]  # [{summary, tweet_url, author_name, author_username}]
    announcements: list[dict]
    discussions: list[dict]


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
        return TweetDigest(paper_threads=[], announcements=[], discussions=[])

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
                "content": f"""Categorize and summarize these AI/ML tweets. Group them into three categories:

1. **paper_threads**: Tweets discussing or sharing research papers
2. **announcements**: Product launches, model releases, company news
3. **discussions**: Notable debates, opinions, or threads about AI/ML topics

For each entry, provide a 1-2 sentence summary and the original tweet URL.

## Tweets
{tweets_text}

Return ONLY valid JSON:
{{
  "paper_threads": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}],
  "announcements": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}],
  "discussions": [{{"summary": "...", "tweet_url": "...", "author_name": "...", "author_username": "..."}}]
}}""",
            }
        ],
    )

    try:
        text = response.content[0].text
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        result = json.loads(text)
        return TweetDigest(
            paper_threads=result.get("paper_threads", []),
            announcements=result.get("announcements", []),
            discussions=result.get("discussions", []),
        )
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Failed to parse Claude tweet summary: {e}")
        return TweetDigest(paper_threads=[], announcements=[], discussions=[])
