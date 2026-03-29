"""Fetch recent arxiv papers using RSS feeds (no rate limiting issues)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

RSS_URL = "https://rss.arxiv.org/rss/{category}"

# Namespaces used in arxiv RSS
DC_NS = "http://purl.org/dc/elements/1.1/"
ARXIV_NS = "http://arxiv.org/schemas/atom"


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


def _parse_arxiv_rss(xml_text: str) -> list[Paper]:
    """Parse arxiv RSS 2.0 feed into Paper objects.

    Item format:
      <title>Paper Title</title>
      <link>https://arxiv.org/abs/XXXX.XXXXX</link>
      <description>arXiv:XXXX.XXXXXvN Announce Type: new\nAbstract: ...</description>
      <dc:creator>Author One, Author Two</dc:creator>
      <category>cs.CL</category>
      <pubDate>Fri, 28 Mar 2026 00:00:00 -0400</pubDate>
      <arxiv:announce_type>new</arxiv:announce_type>
    """
    papers = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    for item in root.iter("item"):
        # Skip replacements — only show new and cross-listed papers
        announce_el = item.find(f"{{{ARXIV_NS}}}announce_type")
        announce_type = announce_el.text.strip() if announce_el is not None and announce_el.text else "new"
        if announce_type in ("replace", "replace-cross"):
            continue

        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        creator_el = item.find(f"{{{DC_NS}}}creator")
        pubdate_el = item.find("pubDate")

        if title_el is None or not title_el.text:
            continue

        title = title_el.text.strip()
        link = link_el.text.strip() if link_el is not None and link_el.text else ""

        # Extract arxiv ID from link: https://arxiv.org/abs/2503.12345
        arxiv_id = link.rstrip("/").split("/")[-1] if link else ""

        # Parse authors from dc:creator (comma-separated)
        authors = []
        if creator_el is not None and creator_el.text:
            # Handle HTML entities and tags
            creator_text = re.sub(r"<[^>]+>", "", creator_el.text)
            authors = [a.strip() for a in creator_text.split(",") if a.strip()]

        # Parse abstract from description
        abstract = ""
        if desc_el is not None and desc_el.text:
            desc = desc_el.text.strip()
            # Format: "arXiv:XXXX.XXXXXvN Announce Type: new\nAbstract: actual abstract"
            abstract_match = re.search(r"Abstract:\s*(.*)", desc, re.DOTALL)
            if abstract_match:
                abstract = abstract_match.group(1).strip()
                # Clean up HTML
                abstract = re.sub(r"<[^>]+>", "", abstract)
                abstract = abstract.replace("\n", " ").strip()

        # Parse date
        published = datetime.now(timezone.utc)
        if pubdate_el is not None and pubdate_el.text:
            try:
                published = parsedate_to_datetime(pubdate_el.text)
            except (ValueError, TypeError):
                pass

        # Parse categories
        categories = []
        for cat_el in item.findall("category"):
            if cat_el.text:
                categories.append(cat_el.text.strip())

        abs_url = link or f"https://arxiv.org/abs/{arxiv_id}"
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else ""

        papers.append(Paper(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            abstract=abstract,
            categories=categories,
            published=published,
            abs_url=abs_url,
            pdf_url=pdf_url,
        ))

    return papers


def fetch_recent_papers(
    categories: list[str],
    max_per_category: int = 100,
    hours_back: int = 48,
    target_date: datetime | None = None,
) -> list[Paper]:
    """Fetch recent papers via arxiv RSS feeds.

    RSS feeds return the latest daily batch — one HTTP request per category,
    no pagination, no rate limiting. On weekends the feeds are empty.
    """
    seen_ids: set[str] = set()
    papers: list[Paper] = []

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for category in categories:
            url = RSS_URL.format(category=category)
            try:
                resp = client.get(url, headers={"User-Agent": "hamish-reads/1.0"})
                resp.raise_for_status()
                category_papers = _parse_arxiv_rss(resp.text)

                for paper in category_papers:
                    if paper.arxiv_id and paper.arxiv_id not in seen_ids:
                        seen_ids.add(paper.arxiv_id)
                        papers.append(paper)

                print(f"  {category}: {len(category_papers)} papers ({len(category_papers) - len([p for p in category_papers if p.arxiv_id in seen_ids])} new)")
            except Exception as e:
                print(f"  {category}: failed ({e})")

    print(f"  Total: {len(papers)} unique papers")
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
