"""Splitting an 8-K into its numbered items.

Item headings are the only reliable structure an 8-K has, and they appear in a
dozen capitalisations.

Two layouts have to work. In the common one each heading is followed by its own
narrative. In the other, and it is not rare, the filing lists every item heading
together at the top and then gives one combined narrative underneath:

    Item 1.01.  Entry into a Material Definitive Agreement.
    Item 1.02   Termination of a Material Definitive Agreement.
    Item 2.03.  Creation of a Direct Financial Obligation.

    On October 31, 2007 the Company entered into a secured business loan
    agreement replacing a credit facility with its subsidiary.

Splitting that naively gives item 1.02 a section containing nothing but its own
title, and hands the narrative to item 2.03. A run of headings with no text
between them is therefore treated as one block, and the narrative that follows
belongs to every item in the run.

Where a heading appears twice, once in a table of contents and once in the body,
the longest section wins. A contents entry is a line; the real section is
paragraphs.
"""
from __future__ import annotations

import re

# The whitespace between the word and the number has to allow newlines. Filings
# lay headings out across several lines, "Item\n1.02\n\nTermination\nof a Material
# Definitive\nAgreement", and a space-only class missed every one of them. The
# line anchor still holds, so a mid-sentence "described in this Item 1.02" is not
# mistaken for a heading.
HEADING = re.compile(r"^[ \t>*]*item\s*(\d{1,2}\.\d{2})\b", re.IGNORECASE | re.MULTILINE)

# A listing is a noun phrase: "Termination of a Material Definitive Agreement."
# A narrative carries a date almost without exception: "On October 31, 2007 the
# Company entered into...". Length alone was not enough to tell them apart,
# because a real section can be one short sentence.
TITLE_ONLY_CHARS = 140

# Same line only. A whitespace class that crosses newlines lets the trailing
# [^\n]* swallow the first line of the body, which made every section that began
# with a sentence look empty.
TITLE = re.compile(
    r"^[ \t>*]*item\s*\d{1,2}\.\d{2}[.\t ]*[^\n]*\n?", re.IGNORECASE
)


def _is_title_only(segment: str) -> bool:
    without_heading = TITLE.sub("", segment, count=1)
    remainder = re.sub(r"\s+", " ", without_heading).strip()
    if not remainder:
        return True
    return len(remainder) < TITLE_ONLY_CHARS and not any(c.isdigit() for c in remainder)


def item_sections(text: str) -> dict[str, str]:
    """Maps an item code such as "1.02" to the longest section carrying it."""
    matches = list(HEADING.finditer(text))
    if not matches:
        return {}

    segments: list[tuple[str, str]] = []
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        segments.append((match.group(1), text[match.start():end].strip()))

    # Walk runs of heading-only segments and give them the narrative that follows.
    resolved: list[tuple[str, str]] = []
    index = 0
    while index < len(segments):
        code, body = segments[index]
        if not _is_title_only(body):
            resolved.append((code, body))
            index += 1
            continue

        run = [index]
        while index + 1 < len(segments) and _is_title_only(segments[index + 1][1]):
            index += 1
            run.append(index)

        shared = segments[index + 1][1] if index + 1 < len(segments) else ""
        if shared:
            for position in run:
                resolved.append((segments[position][0], f"{segments[position][1]}\n{shared}"))
            resolved.append(segments[index + 1])
            index += 2
        else:
            for position in run:
                resolved.append(segments[position])
            index += 1

    sections: dict[str, str] = {}
    for code, body in resolved:
        if len(body) > len(sections.get(code, "")):
            sections[code] = body
    return sections
