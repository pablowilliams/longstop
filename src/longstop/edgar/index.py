"""Quarterly EDGAR form indexes.

Each quarter's form.idx lists every filing the SEC disseminated that quarter,
around fifty megabytes and three hundred thousand rows. Only a hundred or so
rows per quarter are deal announcements, so the file is streamed, filtered and
discarded, and only the surviving rows are cached.

The file's own header is misaligned with its data rows, so nothing here trusts
a fixed column width. Rows are parsed right-anchored from the CIK, date and
path, which are unambiguous, and anything that fails to parse is counted and
reported rather than dropped in silence.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterator

from longstop.edgar.client import EdgarClient

INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"

# form type and company name, then three unambiguous fields: a CIK, an ISO
# date, and a path that always begins "edgar/".
ROW = re.compile(
    r"^(?P<form>\S(?:.*?\S)?)\s{2,}(?P<name>\S(?:.*?\S)?)\s+(?P<cik>\d{1,10})\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<path>edgar/\S+)\s*$"
)


@dataclass(frozen=True)
class IndexRow:
    form: str
    company: str
    cik: int
    filed: str
    path: str

    @property
    def accession(self) -> str:
        return Path(self.path).stem


def parse_row(line: str) -> IndexRow | None:
    match = ROW.match(line.rstrip("\n"))
    if not match:
        return None
    return IndexRow(
        form=match["form"].strip(),
        company=match["name"].strip(),
        cik=int(match["cik"]),
        filed=match["date"],
        path=match["path"],
    )


def parse_index(text: str, keep: Callable[[str], bool]) -> tuple[list[IndexRow], int, int]:
    """Returns kept rows, total data rows seen, and rows that would not parse."""
    rows: list[IndexRow] = []
    seen = 0
    unparsed = 0
    started = False
    for line in text.splitlines():
        if not started:
            # The ruler of dashes is the last line before the data.
            if line.startswith("----"):
                started = True
            continue
        if not line.strip():
            continue
        seen += 1
        row = parse_row(line)
        if row is None:
            unparsed += 1
            continue
        if keep(row.form):
            rows.append(row)
    return rows, seen, unparsed


def quarter_rows(
    client: EdgarClient,
    year: int,
    quarter: int,
    keep: Callable[[str], bool],
    cache_dir: Path,
) -> tuple[list[IndexRow], int, int] | None:
    """Fetch one quarter, filter it, and cache only the surviving rows."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    slim = cache_dir / f"{year}Q{quarter}.jsonl"
    if slim.exists():
        payload = [json.loads(line) for line in slim.read_text().splitlines() if line]
        meta = payload[0]
        rows = [IndexRow(**row) for row in payload[1:]]
        return rows, meta["seen"], meta["unparsed"]

    body = client.get(INDEX_URL.format(year=year, quarter=quarter), allow_404=True, store=False)
    if body is None:
        return None
    rows, seen, unparsed = parse_index(body.decode("latin-1"), keep)
    with slim.open("w") as fh:
        fh.write(json.dumps({"seen": seen, "unparsed": unparsed, "year": year, "quarter": quarter}) + "\n")
        for row in rows:
            fh.write(json.dumps(asdict(row)) + "\n")
    return rows, seen, unparsed


def iter_quarters(start_year: int, end_year: int) -> Iterator[tuple[int, int]]:
    for year in range(start_year, end_year + 1):
        for quarter in (1, 2, 3, 4):
            yield year, quarter
