from flea.llm.base import LLMClient
from flea.news.sources import Article

EVENT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["events"],
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "event_type",
                    "affected_items",
                    "direction",
                    "confidence",
                    "time_horizon",
                    "summary",
                ],
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": [
                            "nerf",
                            "buff",
                            "wipe",
                            "event",
                            "spawn_change",
                            "patch",
                            "other",
                        ],
                    },
                    "affected_items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "unclear"],
                    },
                    "confidence": {"type": "number"},
                    "time_horizon": {
                        "type": "string",
                        "enum": ["immediate", "short", "medium", "long"],
                    },
                    "summary": {"type": "string"},
                },
            },
        }
    },
}


SYSTEM_PROMPT = """You analyze Escape from Tarkov news for market-moving signals.

Given an article, extract events that could affect flea-market prices. Most
community posts (memes, gameplay clips, complaints, questions) are NOT
price-relevant — for those, return {"events": []}.

Extract events for: patch notes, hotfix announcements, wipe news, in-game
events (Halloween, Christmas, etc.), spawn rate changes, balance changes
(nerfs/buffs to weapons or ammo), barter/quest changes, BSG official
statements, datamined upcoming changes.

Field guidance:
- affected_items: use in-game item names as written, e.g. "LEDX", "M61",
  "Salewa", "GPU". Prefer the short in-game name over the full name.
- direction: predicted effect on flea PRICE. A nerf usually means lower
  price (less demand); a buff usually means higher price; a spawn
  reduction usually means higher price.
- confidence: 0.0-1.0 — your certainty the event is real AND will move
  prices meaningfully.
- time_horizon: immediate (now), short (days), medium (weeks), long
  (rest of wipe / multi-month).
- summary: one sentence describing the event neutrally.
"""


class Extractor:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def extract(self, article: Article) -> list[dict]:
        user = f"Source: {article.source}\nTitle: {article.title}\n\nBody:\n{article.body or '(no body)'}"
        result = self.llm.extract_structured(SYSTEM_PROMPT, user, EVENT_SCHEMA)
        return result.get("events", [])
