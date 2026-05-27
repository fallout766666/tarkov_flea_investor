from dataclasses import dataclass
from typing import Protocol

import httpx

USER_AGENT = "tarkov-flea-investor/0.1 (https://github.com/fallout766666)"

EXCLUDED_FLAIRS = {
    "meme", "humor", "clip", "video", "highlight", "rage", "funny",
    "screenshot", "art", "fanart", "music", "cosplay",
}


@dataclass
class Article:
    url: str
    source: str
    title: str
    body: str
    published_at: int


class NewsSource(Protocol):
    name: str
    def fetch(self) -> list[Article]: ...


class RedditSource:
    name = "reddit"

    def __init__(self, subreddit: str = "EscapefromTarkov", limit: int = 25):
        self.subreddit = subreddit
        self.limit = limit

    def fetch(self) -> list[Article]:
        url = f"https://www.reddit.com/r/{self.subreddit}/new.json"
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            params={"limit": self.limit},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        out: list[Article] = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            if post.get("over_18"):
                continue
            flair = (post.get("link_flair_text") or "").strip().lower()
            if any(bad in flair for bad in EXCLUDED_FLAIRS):
                continue
            out.append(
                Article(
                    url="https://reddit.com" + post["permalink"],
                    source="reddit",
                    title=post.get("title", ""),
                    body=post.get("selftext", "") or "",
                    published_at=int(post.get("created_utc", 0)),
                )
            )
        return out
