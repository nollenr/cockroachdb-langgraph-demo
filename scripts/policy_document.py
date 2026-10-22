"""Parse and validate the authoritative Markdown return-policy document."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


SECTION_RE = re.compile(
    r"^##\s+(.+?)\s+\((RET-[A-Z]+-\d{3})\)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class PolicySection:
    heading: str
    clause_key: str
    text: str
    chunk_index: int


@dataclass(frozen=True)
class PolicyDocument:
    title: str
    policy_key: str
    policy_version: str
    content_sha256: str
    sections: tuple[PolicySection, ...]


def _header_value(markdown: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}:\s+`([^`]+)`\s*$", markdown, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing Markdown header field: {label}")
    return match.group(1)


def normalize_text(value: str) -> str:
    """Normalize insignificant Markdown whitespace for source verification."""
    return " ".join(value.split())


def parse_policy_document(path: Path) -> PolicyDocument:
    raw_bytes = path.read_bytes()
    markdown = raw_bytes.decode("utf-8")

    title_match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
    if not title_match:
        raise ValueError("Policy document is missing its level-one title")

    matches = list(SECTION_RE.finditer(markdown))
    if not matches:
        raise ValueError("Policy document contains no identified level-two sections")

    sections: list[PolicySection] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[body_start:body_end].strip()
        if not body:
            raise ValueError(f"Policy section {match.group(2)} has no text")
        sections.append(
            PolicySection(
                heading=match.group(1),
                clause_key=match.group(2),
                text=normalize_text(body),
                chunk_index=index,
            )
        )

    clause_keys = [section.clause_key for section in sections]
    if len(clause_keys) != len(set(clause_keys)):
        raise ValueError("Policy document contains duplicate clause identifiers")

    return PolicyDocument(
        title=title_match.group(1),
        policy_key=_header_value(markdown, "Policy key"),
        policy_version=_header_value(markdown, "Version"),
        content_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        sections=tuple(sections),
    )
