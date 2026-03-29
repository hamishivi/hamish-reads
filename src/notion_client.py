"""Read project topics from the PhD Hub Notion page."""

from __future__ import annotations

import os
from dataclasses import dataclass

from notion_client import Client


@dataclass
class ProjectTopic:
    name: str
    description: str


def _extract_text_from_blocks(blocks: list[dict]) -> str:
    """Extract plain text from a list of Notion blocks."""
    parts: list[str] = []
    for block in blocks:
        block_type = block.get("type", "")
        content = block.get(block_type, {})

        # Handle rich_text blocks (paragraph, heading, bulleted_list_item, etc.)
        rich_text = content.get("rich_text", [])
        for rt in rich_text:
            text = rt.get("plain_text", "")
            if text:
                parts.append(text)

    return " ".join(parts)


def fetch_project_topics(
    page_id: str,
    api_key: str | None = None,
) -> list[ProjectTopic]:
    """Read the PhD Hub page and extract child page titles + content as project topics."""
    api_key = api_key or os.environ.get("NOTION_API_KEY", "")
    if not api_key:
        print("Warning: No NOTION_API_KEY set, skipping Notion integration")
        return []

    client = Client(auth=api_key)
    topics: list[ProjectTopic] = []

    try:
        # List child blocks of the PhD Hub page
        children = client.blocks.children.list(block_id=page_id)
        child_pages = [
            block for block in children["results"]
            if block["type"] == "child_page"
        ]

        for child in child_pages:
            page_title = child["child_page"]["title"]
            page_id_child = child["id"]

            # Read the content of each child page
            try:
                page_blocks = client.blocks.children.list(block_id=page_id_child)
                description = _extract_text_from_blocks(page_blocks["results"])
                # Truncate long descriptions to keep Claude prompts manageable
                if len(description) > 1000:
                    description = description[:1000] + "..."
            except Exception:
                description = ""

            topics.append(ProjectTopic(name=page_title, description=description))

    except Exception as e:
        print(f"Warning: Failed to read Notion PhD Hub page: {e}")
        return []

    return topics
