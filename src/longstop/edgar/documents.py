"""Fetching and reading the documents inside a filing.

Outcome labelling needs no documents at all, which is what makes the universe
cheap. Confirming a label does need them, and the economics are favourable:
breaks are rare, so reading every one of them costs a few hundred requests
rather than tens of thousands.

Text extraction is deliberately plain. Filings are HTML of every vintage from
2001 to now, including inline XBRL with tags wrapped around individual numbers,
and anything clever here would fail differently on each decade.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

from longstop.edgar.client import EdgarClient

ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}"
INDEX_JSON = ARCHIVE + "/index.json"
DOCUMENT = ARCHIVE + "/{filename}"

BLOCK_TAGS = {
    "p", "div", "br", "tr", "table", "li", "ul", "ol", "h1", "h2", "h3",
    "h4", "h5", "h6", "td", "th", "section", "article",
}
SKIP_TAGS = {"script", "style", "head", "title"}


@dataclass(frozen=True)
class DocumentRef:
    name: str
    kind: str          # EDGAR's document type, for example "8-K" or "EX-2.1"
    size: int


def no_dash(accession: str) -> str:
    return accession.replace("-", "")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def to_text(raw: str) -> str:
    """HTML or plain text in, readable text out.

    Non-breaking spaces become ordinary ones. Filings use them heavily inside
    numbers and around currency symbols, and leaving them in place breaks every
    pattern that follows.
    """
    if "<" in raw:
        parser = _Text()
        parser.feed(raw)
        text = "".join(parser.parts)
    else:
        text = raw
    text = unescape(text).replace("\xa0", " ").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def filing_documents(client: EdgarClient, cik: int, accession: str) -> list[DocumentRef]:
    url = INDEX_JSON.format(cik=cik, accession=no_dash(accession))
    body = client.get(url, allow_404=True)
    if body is None:
        return []
    items = json.loads(body).get("directory", {}).get("item", [])
    refs = []
    for item in items:
        name = item.get("name", "")
        if name.lower().endswith((".htm", ".html", ".txt")):
            try:
                size = int(item.get("size") or 0)
            except ValueError:
                size = 0
            refs.append(DocumentRef(name=name, kind=item.get("type", "") or "", size=size))
    return refs


def document_text(client: EdgarClient, cik: int, accession: str, filename: str) -> str | None:
    url = DOCUMENT.format(cik=cik, accession=no_dash(accession), filename=filename)
    body = client.get(url, allow_404=True)
    if body is None:
        return None
    return to_text(body.decode("utf-8", errors="replace"))
