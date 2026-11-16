"""The notice, verbatim from docs/SPEC.md, and the one way to test for it."""

import re

NOTICE = (
    "UNVALIDATED SYNTHETIC RESEARCH PREVIEW. Household data, prices, transactions and document "
    "contents are invented. Securities appear under invented names by default; an optional mode "
    "uses real ticker identifiers with invented prices. Tax calculations, answer keys and workflow "
    "judgments have not been independently reviewed by qualified practitioners. This is not tax, "
    "investment or compliance advice and is unsuitable for filing, trading or client decisions. "
    "No performance claims are established."
)

NOTICE_HEADLINE = "UNVALIDATED SYNTHETIC RESEARCH PREVIEW."


def _normalize(text: str) -> str:
    # Markdown emphasis and line wrapping are presentation, not wording.
    return " ".join(re.sub(r"[*_>]", " ", text).split())


def contains_notice(text: str) -> bool:
    return _normalize(NOTICE) in _normalize(text)
