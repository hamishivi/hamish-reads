"""Fetch today's headlines from news publication RSS feeds."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

# Publications and their RSS feeds
PUBLICATIONS = [
    {
        "name": "The Wall Street Journal",
        "short_name": "WSJ",
        "domain": "wsj.com",
        "url": "https://www.wsj.com",
        "rss": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    },
    {
        "name": "The New York Times",
        "short_name": "NYTimes",
        "domain": "nytimes.com",
        "url": "https://www.nytimes.com",
        "rss": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    },
    {
        "name": "The New Yorker",
        "short_name": "New Yorker",
        "domain": "newyorker.com",
        "url": "https://www.newyorker.com",
        "rss": "https://www.newyorker.com/feed/everything",
    },
    {
        "name": "Sydney Morning Herald",
        "short_name": "SMH",
        "domain": "smh.com.au",
        "url": "https://www.smh.com.au",
        "rss": "https://www.smh.com.au/rss/feed.xml",
    },
    {
        "name": "ABC News",
        "short_name": "ABC",
        "domain": "abc.net.au",
        "url": "https://www.abc.net.au/news",
        "rss": "https://www.abc.net.au/news/feed/2942460/rss.xml",
    },
    {
        "name": "The Verge",
        "short_name": "Verge",
        "domain": "theverge.com",
        "url": "https://www.theverge.com",
        "rss": "https://www.theverge.com/rss/index.xml",
    },
    {
        "name": "Wired",
        "short_name": "Wired",
        "domain": "wired.com",
        "url": "https://www.wired.com",
        "rss": "https://www.wired.com/feed/rss",
    },
    {
        "name": "The Guardian Australia",
        "short_name": "Guardian AU",
        "domain": "theguardian.com",
        "url": "https://www.theguardian.com/au",
        "rss": "https://www.theguardian.com/au/rss",
    },
    {
        "name": "The Atlantic",
        "short_name": "Atlantic",
        "domain": "theatlantic.com",
        "url": "https://www.theatlantic.com",
        "rss": "https://www.theatlantic.com/feed/all/",
    },
]


@dataclass
class Article:
    title: str
    url: str
    published: str


@dataclass
class PublicationFeed:
    name: str
    short_name: str
    domain: str
    url: str
    logo_url: str
    articles: list[Article] = field(default_factory=list)


def _parse_rss(xml_text: str, max_articles: int = 5) -> list[Article]:
    """Parse RSS/Atom XML and extract articles."""
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # RSS 2.0 format
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        if title_el is not None and title_el.text:
            articles.append(Article(
                title=title_el.text.strip(),
                url=link_el.text.strip() if link_el is not None and link_el.text else "",
                published=pub_el.text.strip() if pub_el is not None and pub_el.text else "",
            ))
        if len(articles) >= max_articles:
            return articles

    # Atom format (e.g., The Verge)
    if not articles:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            pub_el = entry.find("atom:published", ns) or entry.find("atom:updated", ns)
            if title_el is not None and title_el.text:
                link_href = link_el.get("href", "") if link_el is not None else ""
                articles.append(Article(
                    title=title_el.text.strip(),
                    url=link_href,
                    published=pub_el.text.strip() if pub_el is not None and pub_el.text else "",
                ))
            if len(articles) >= max_articles:
                return articles

    return articles


def fetch_news(max_articles_per_pub: int = 5) -> list[PublicationFeed]:
    """Fetch headlines from all configured publications."""
    feeds: list[PublicationFeed] = []

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for pub in PUBLICATIONS:
            logo_url = f"https://www.google.com/s2/favicons?domain={pub['domain']}&sz=64"
            feed = PublicationFeed(
                name=pub["name"],
                short_name=pub["short_name"],
                domain=pub["domain"],
                url=pub["url"],
                logo_url=logo_url,
            )

            try:
                resp = client.get(pub["rss"], headers={"User-Agent": "hamish-reads/1.0"})
                resp.raise_for_status()
                feed.articles = _parse_rss(resp.text, max_articles=max_articles_per_pub)
                print(f"  {pub['short_name']}: {len(feed.articles)} articles")
            except Exception as e:
                print(f"  {pub['short_name']}: failed ({e})")

            feeds.append(feed)

    return feeds
