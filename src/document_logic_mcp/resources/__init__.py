"""Technology terminology resource for canonical name resolution."""

import json
import re
from pathlib import Path
from typing import Optional

_TERMINOLOGY_PATH = Path(__file__).parent / "technology_terminology.json"
_TERMINOLOGY_DATA = None
_ALIAS_INDEX = None


def _load_terminology():
    """Load and index the technology terminology resource."""
    global _TERMINOLOGY_DATA, _ALIAS_INDEX
    if _TERMINOLOGY_DATA is not None:
        return

    path = _TERMINOLOGY_PATH
    with open(path) as f:
        _TERMINOLOGY_DATA = json.load(f)

    # Build alias → entry index (case-insensitive, stripped)
    _ALIAS_INDEX = {}
    for entry in _TERMINOLOGY_DATA["entries"]:
        canonical = entry["canonical_name"]
        # Index the canonical name itself
        _ALIAS_INDEX[canonical.lower().strip()] = entry
        # Index each alias
        for alias in entry["aliases"]:
            key = alias.lower().strip()
            if key in _ALIAS_INDEX:
                # Ambiguous — multiple canonicals claim this alias
                # Store None to signal ambiguity
                if _ALIAS_INDEX[key] is not None and _ALIAS_INDEX[key]["canonical_name"] != canonical:
                    _ALIAS_INDEX[key] = None
            else:
                _ALIAS_INDEX[key] = entry


# Regex to strip version suffixes: "PostgreSQL 15.3" → "PostgreSQL"
_VERSION_PATTERN = re.compile(r"\s*v?\d[\d.]*(-\w+)?\s*$", re.IGNORECASE)


def resolve_technology_name(raw_name: str) -> dict:
    """Resolve a raw technology string to its canonical name.

    Returns:
        {
            "canonical_name": str or None,
            "original": str,
            "version": str or None,
            "category": str or None,
            "matched": bool,
            "disambiguation_note": str or None
        }
    """
    _load_terminology()

    original = raw_name.strip()
    if not original:
        return {
            "canonical_name": None,
            "original": original,
            "version": None,
            "category": None,
            "matched": False,
            "disambiguation_note": None,
        }

    # Extract version if present
    version = None
    version_match = _VERSION_PATTERN.search(original)
    if version_match:
        version = version_match.group(0).strip()
        name_without_version = original[: version_match.start()].strip()
    else:
        name_without_version = original

    # Exact lookup (case-insensitive)
    key = name_without_version.lower()
    entry = _ALIAS_INDEX.get(key)

    if entry is None and key in _ALIAS_INDEX:
        # Ambiguous match — multiple canonicals
        return {
            "canonical_name": None,
            "original": original,
            "version": version,
            "category": None,
            "matched": False,
            "disambiguation_note": "Ambiguous — multiple possible canonical names. Provide more context.",
        }

    if entry is not None:
        return {
            "canonical_name": entry["canonical_name"],
            "original": original,
            "version": version,
            "category": entry["category"],
            "matched": True,
            "disambiguation_note": entry.get("disambiguation_note"),
        }

    # No exact match — try fuzzy matching
    canonical = _fuzzy_match(key)
    if canonical is not None:
        return {
            "canonical_name": canonical["canonical_name"],
            "original": original,
            "version": version,
            "category": canonical["category"],
            "matched": True,
            "disambiguation_note": canonical.get("disambiguation_note"),
        }

    # No match at all
    return {
        "canonical_name": None,
        "original": original,
        "version": version,
        "category": None,
        "matched": False,
        "disambiguation_note": None,
    }


def _fuzzy_match(key: str, threshold: float = 0.85) -> Optional[dict]:
    """Simple fuzzy matching using character-level similarity."""
    best_score = 0.0
    best_entry = None

    for alias_key, entry in _ALIAS_INDEX.items():
        if entry is None:
            continue
        score = _similarity(key, alias_key)
        if score > best_score and score >= threshold:
            best_score = score
            best_entry = entry

    return best_entry


def _similarity(a: str, b: str) -> float:
    """Compute normalized Levenshtein similarity between two strings."""
    if a == b:
        return 1.0
    len_a, len_b = len(a), len(b)
    if len_a == 0 or len_b == 0:
        return 0.0

    # Quick length check — if lengths differ too much, skip expensive computation
    max_len = max(len_a, len_b)
    if abs(len_a - len_b) / max_len > 0.3:
        return 0.0

    # Levenshtein distance (optimized single-row)
    prev = list(range(len_b + 1))
    for i in range(1, len_a + 1):
        curr = [i] + [0] * len_b
        for j in range(1, len_b + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr

    distance = prev[len_b]
    return 1.0 - distance / max_len


def get_all_entries() -> list:
    """Return all terminology entries."""
    _load_terminology()
    return _TERMINOLOGY_DATA["entries"]


def suggest_terminology_addition(
    canonical_name: str,
    aliases: list[str],
    category: str,
    disambiguation_note: str = None,
    source_engagement: str = None,
) -> dict:
    """Queue a terminology addition suggestion for human review.

    Returns a suggestion record that should be persisted for review.
    Does NOT modify the terminology file directly.
    """
    return {
        "action": "add_terminology",
        "status": "pending_review",
        "canonical_name": canonical_name,
        "aliases": aliases,
        "category": category,
        "disambiguation_note": disambiguation_note,
        "source_engagement": source_engagement,
    }
