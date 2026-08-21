"""Deterministic text helpers for the ambiguity detectors.

Span localization follows the annotation protocol (docs/13 §5): offsets are
half-open character positions into the question text (Python ``len``
semantics). All matching here is case-insensitive and pattern-based; there is
no learned model and no random element, so the same question and schema always
yield the same spans.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Common English words that end in ``s`` but are already singular; they must
# not be reduced (e.g. "status" must not become "statu").
_ALREADY_SINGULAR = frozenset(
    {
        "status", "gross", "class", "glass", "mass", "pass", "business",
        "address", "process", "access", "basis", "analysis", "campus",
        "bonus", "virus", "crisis", "means", "series", "species",
        "focus", "radius", "atlas", "alias",
    }
)

STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "to", "in", "on", "at", "for", "and", "or",
        "but", "is", "are", "was", "were", "be", "been", "being", "with",
        "by", "from", "we", "our", "us", "do", "does", "did", "how", "what",
        "which", "who", "whom", "show", "list", "give", "get", "total",
        "count", "number", "all", "any", "each", "per", "this", "that",
        "these", "those", "over", "under", "please", "can", "could", "as",
        "if", "then", "than", "so", "not", "no",
    }
)


@dataclass(frozen=True)
class Term:
    """One alphanumeric token of a text with its half-open character span."""

    text: str
    start: int
    end: int


def split_terms(text: str) -> list[Term]:
    """Split ``text`` into alphanumeric terms with half-open offsets.

    Non-alphanumeric characters are treated as separators, so ``"Q4 2024"``
    yields ``Q4`` and ``2024`` while ``"revenue, gross"`` yields ``revenue``
    and ``gross``.

    Parameters
    ----------
    text:
        The text to tokenize.

    Returns
    -------
    list[Term]:
        One term per alphanumeric run, in reading order.
    """
    return [
        Term(text=match.group(0), start=match.start(), end=match.end())
        for match in _WORD_RE.finditer(text)
    ]


def normalize_phrase(text: str) -> str:
    """Lowercase ``text`` and join its alphanumeric terms with single spaces.

    Used as the canonical key for schema names, synonyms, and trigger phrases:
    ``"net_revenue"`` and ``"Net Revenue"`` both normalize to ``"net revenue"``.

    Parameters
    ----------
    text:
        The phrase to normalize.

    Returns
    -------
    str:
        The normalized key; empty when ``text`` has no alphanumeric terms.
    """
    return " ".join(term.text.lower() for term in split_terms(text))


def find_phrase(text: str, phrase: str) -> tuple[int, int] | None:
    """Return the half-open span of the first token-contiguous occurrence.

    Matching is case-insensitive over alphanumeric terms; punctuation inside
    ``phrase`` is ignored, so ``find_phrase("Q4 revenue by region", "q4")``
    returns the span of ``"Q4"``.

    Parameters
    ----------
    text:
        The text to search.
    phrase:
        The phrase to locate; matched as a contiguous run of tokens.

    Returns
    -------
    tuple[int, int] | None:
        The ``(start, end)`` of the first occurrence, or None when absent.
    """
    phrase_terms = split_terms(phrase)
    if not phrase_terms:
        return None
    keys = tuple(term.text.lower() for term in phrase_terms)
    text_terms = split_terms(text)
    width = len(keys)
    if width > len(text_terms):
        return None
    for index in range(len(text_terms) - width + 1):
        if tuple(t.text.lower() for t in text_terms[index : index + width]) == keys:
            return (text_terms[index].start, text_terms[index + width - 1].end)
    return None


def find_substring(text: str, substring: str) -> tuple[int, int] | None:
    """Return the half-open span of the first case-insensitive substring.

    Unlike :func:`find_phrase`, this matches non-alphanumeric symbols (e.g.
    ``"$"``) directly.

    Parameters
    ----------
    text:
        The text to search.
    substring:
        The literal substring to locate.

    Returns
    -------
    tuple[int, int] | None:
        The ``(start, end)`` of the first occurrence, or None when absent.
    """
    index = text.lower().find(substring.lower())
    if index < 0:
        return None
    return (index, index + len(substring))


def significant_terms(text: str) -> list[Term]:
    """Return terms worth matching: non-stopwords, length >= 3, not pure digits.

    Parameters
    ----------
    text:
        The text to filter.

    Returns
    -------
    list[Term]:
        The significant terms in reading order.
    """
    significant: list[Term] = []
    for term in split_terms(text):
        key = term.text.lower()
        if len(key) < 3 or key in STOPWORDS or key.isdigit():
            continue
        significant.append(term)
    return significant


def singularize(word: str) -> str:
    """Reduce a common English plural to its singular form, if plausible.

    ``"regions"`` -> ``"region"``, ``"cities"`` -> ``"city"``, ``"sales"`` ->
    ``"sale"``. Words not ending in ``s`` (and double-``s`` words such as
    ``"gross"``) are returned unchanged.

    Parameters
    ----------
    word:
        The lowercase word to singularize.

    Returns
    -------
    str:
        The singular form.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word in _ALREADY_SINGULAR:
        return word
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


__all__ = [
    "STOPWORDS",
    "Term",
    "find_phrase",
    "find_substring",
    "normalize_phrase",
    "significant_terms",
    "singularize",
    "split_terms",
]
