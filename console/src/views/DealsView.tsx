import { useEffect, useState } from "react";
import { api, type DealPage } from "../api";
import { count } from "../format";

const LABELS = [
  "",
  "completed",
  "completed_shell",
  "terminated",
  "acquirer_side",
  "unresolved",
  "pending",
  "not_registrant",
];

const PAGE = 50;

export function DealsView() {
  const [page, setPage] = useState<DealPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    let live = true;
    api
      .deals({ label, q: query, limit: PAGE, offset })
      .then((result) => live && setPage(result))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [label, query, offset]);

  return (
    <div className="panel">
      <div className="controls">
        <input
          placeholder="Company or ticker"
          value={query}
          onChange={(event) => {
            setOffset(0);
            setQuery(event.target.value);
          }}
          style={{ minWidth: 230 }}
        />
        <select
          value={label}
          onChange={(event) => {
            setOffset(0);
            setLabel(event.target.value);
          }}
        >
          {LABELS.map((value) => (
            <option key={value || "all"} value={value}>
              {value ? value.replace(/_/g, " ") : "every label"}
            </option>
          ))}
        </select>
        <span className="muted">{page ? `${count(page.total)} episodes` : "…"}</span>
        <span style={{ flex: 1 }} />
        <button className="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          Previous
        </button>
        <button
          className="ghost"
          disabled={!page || offset + PAGE >= page.total}
          onClick={() => setOffset(offset + PAGE)}
        >
          Next
        </button>
      </div>

      {error && <p className="err">{error}</p>}

      <table>
        <thead>
          <tr>
            <th>Target</th>
            <th>Announced</th>
            <th>Label</th>
            <th>Resolved</th>
            <th className="num">Days</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {page?.rows.map((row) => (
            <tr key={`${row.cik}-${row.announced}`}>
              <td>
                {row.company}
                {row.tickers.length > 0 && <span className="muted mono"> {row.tickers[0]}</span>}
                {row.shell && <span className="tag" style={{ marginLeft: 6 }}>shell</span>}
              </td>
              <td className="mono">{row.announced}</td>
              <td><span className={`tag ${row.label}`}>{row.label.replace(/_/g, " ")}</span></td>
              <td className="mono">{row.resolved_on ?? "-"}</td>
              <td className="num">{row.days_to_resolution ?? ""}</td>
              <td className="muted mono" style={{ fontSize: 11 }}>{row.evidence.join(" ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {page && page.rows.length === 0 && <p className="muted">Nothing matches that filter.</p>}
    </div>
  );
}
