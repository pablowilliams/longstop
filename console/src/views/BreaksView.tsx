import { Fragment, useEffect, useState } from "react";
import { api, type BreakRow } from "../api";
import { count, money } from "../format";

const STATUSES = ["", "confirmed", "unrelated", "unclear", "no_section", "no_document"];

export function BreaksView() {
  const [rows, setRows] = useState<BreakRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.breaks(status || undefined).then(setRows).catch((e: Error) => setError(e.message));
  }, [status]);

  if (error) return <p className="err">{error}</p>;

  const reasonTally: Record<string, number> = {};
  for (const row of rows ?? []) {
    for (const reason of row.reasons) reasonTally[reason] = (reasonTally[reason] ?? 0) + 1;
  }

  return (
    <>
      <div className="panel">
        <h2>Why each break candidate is or is not a break</h2>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          8-K item 1.02 reports the termination of any material definitive agreement, so
          a cancelled revolving credit facility is filed the same way a dead merger is.
          Every candidate is read, the verdict keeps the text it was based on, and a
          document that does not say clearly is recorded as unclear rather than counted.
        </p>
        <div className="controls">
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            {STATUSES.map((value) => (
              <option key={value || "all"} value={value}>
                {value ? value.replace(/_/g, " ") : "every verdict"}
              </option>
            ))}
          </select>
          <span className="muted">{rows ? `${count(rows.length)} candidates` : "…"}</span>
        </div>
        {Object.keys(reasonTally).length > 0 && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
            {Object.entries(reasonTally)
              .sort((a, b) => b[1] - a[1])
              .map(([reason, n]) => (
                <span key={reason} className="tag">
                  {reason.replace(/_/g, " ")} {n}
                </span>
              ))}
          </div>
        )}
      </div>

      <div className="panel" style={{ marginTop: 14 }}>
        <table>
          <thead>
            <tr>
              <th>Target</th>
              <th>Announced</th>
              <th>Reported</th>
              <th className="num">Days</th>
              <th>Verdict</th>
              <th>Reasons</th>
              <th className="num">Fee</th>
            </tr>
          </thead>
          <tbody>
            {rows?.map((row) => {
              const key = `${row.cik}-${row.announced}`;
              return (
                <Fragment key={key}>
                  <tr onClick={() => setOpen(open === key ? null : key)} style={{ cursor: "pointer" }}>
                    <td>{row.company}</td>
                    <td className="mono">{row.announced}</td>
                    <td className="mono">{row.resolved_on ?? "-"}</td>
                    <td className="num">{row.days_to_resolution ?? ""}</td>
                    <td>
                      <span className={`tag ${row.status === "confirmed" ? "terminated" : "unresolved"}`}>
                        {row.status.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="muted" style={{ fontSize: 12 }}>{row.reasons.join(", ")}</td>
                    <td className="num">{row.break_fee_usd ? money(row.break_fee_usd) : ""}</td>
                  </tr>
                  {open === key && (
                    <tr>
                      <td colSpan={7}>
                        <div className="excerpt">{row.excerpt || "No section text captured."}</div>
                        {row.document && <p className="muted" style={{ fontSize: 11 }}>from {row.document}</p>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {rows && rows.length === 0 && (
          <p className="muted">Nothing here yet. Run <span className="mono">make breaks</span>.</p>
        )}
      </div>
    </>
  );
}
