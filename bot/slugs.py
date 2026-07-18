"""Tiny standalone helper with no project imports, so both bot.models and
bot.domain (which import each other) can use it without a circular import."""
from __future__ import annotations

import re


def slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return slug
