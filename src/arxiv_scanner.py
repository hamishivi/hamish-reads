"""Fetch recent arxiv papers and filter by followed authors."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import arxiv


@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published: datetime
    abs_url: str
    pdf_url: str
    is_author_match: bool = False
    relevance_score: float = 0.0
    relevance_reason: str = ""


def fetch_recent_papers(
    categories: list[str],
    max_per_category: int = 100,
    hours_back: int = 48,
) -> list[Paper]:
    """Fetch papers published in the last `hours_back` hours across categories."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    seen_ids: set[str] = set()
    papers: list[Paper] = []

    for category in categories:
        search = arxiv.Search(
            query=f"cat:{category}",
            max_results=max_per_category,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        client = arxiv.Client(page_size=50, delay_seconds=3.0)
        for result in client.results(search):
            # Stop once we hit papers older than cutoff
            if result.published.replace(tzinfo=timezone.utc) < cutoff:
                break

            if result.entry_id in seen_ids:
                continue
            seen_ids.add(result.entry_id)

            papers.append(
                Paper(
                    arxiv_id=result.entry_id.split("/")[-1],
                    title=result.title.replace("\n", " ").strip(),
                    authors=[a.name for a in result.authors],
                    abstract=result.summary.replace("\n", " ").strip(),
                    categories=[c for c in result.categories],
                    published=result.published,
                    abs_url=result.entry_id,
                    pdf_url=result.pdf_url,
                )
            )

        # Be polite to the arxiv API between categories
        time.sleep(3)

    return papers


def filter_by_authors(
    papers: list[Paper],
    author_names: list[str],
) -> tuple[list[Paper], list[Paper]]:
    """Split papers into those by followed authors and the rest.

    Uses case-insensitive substring matching to handle name variations.
    """
    normalized_names = [name.lower().strip() for name in author_names]

    author_papers: list[Paper] = []
    other_papers: list[Paper] = []

    for paper in papers:
        matched = False
        for paper_author in paper.authors:
            paper_author_lower = paper_author.lower()
            for followed_name in normalized_names:
                if followed_name in paper_author_lower or paper_author_lower in followed_name:
                    matched = True
                    break
            if matched:
                break

        if matched:
            paper.is_author_match = True
            author_papers.append(paper)
        else:
            other_papers.append(paper)

    return author_papers, other_papers
