import { useEffect, useState } from "react";
import { api, type UniverseSummary } from "../api";
import { StackedBars, colourFor } from "../components/charts";
import { count, pct } from "../format";

const ORDER = [
  "completed",
  "completed_shell",
  "terminated",
  "acquirer_side",
  "unresolved",
  "pending",
  "not_registrant",
];

export function UniverseView() {
  const [data, setData] = useState<UniverseSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.summary().then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="err">{error}</p>;
  if (!data) return <p className="muted">Loading the universe.</p>;

  const years = Object.keys(data.by_year).sort();
  const rows = years.map((year) => ({ key: year, counts: data.by_year[year] }));
  const operating = data.operating_company_deals;

  return (
    <>
      <div className="grid four">
        <div className="panel stat">
          <div className="label">Deal episodes</div>
          <div className="value">{count(data.episodes)}</div>
          <div className="note">{years[0]} to {years[years.length - 1]}</div>
        </div>
        <div className="panel stat">
          <div className="label">Completion rate</div>
          <div className="value">{pct(data.completion_rate)}</div>
          <div className="note">of {count(data.completion_rate_denominator)} resolved</div>
        </div>
        <div className="panel stat">
          <div className="label">Break candidates</div>
          <div className="value">{count(data.break_events)}</div>
          <div className="note">unconfirmed until read</div>
        </div>
        <div className="panel stat">
          <div className="label">Sign to close</div>
          <div className="value">{data.sign_to_close_days.median ?? "n/a"}d</div>
          <div className="note">
            p10 {data.sign_to_close_days.p10} · p90 {data.sign_to_close_days.p90}
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 14 }}>
        <h2>Outcomes by year of announcement</h2>
        <StackedBars rows={rows} order={ORDER} />
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 10 }}>
          {ORDER.map((label) => (
            <span key={label} className="muted" style={{ fontSize: 12 }}>
              <span
                style={{
                  display: "inline-block",
                  width: 9,
                  height: 9,
                  background: colourFor(label),
                  borderRadius: 2,
                  marginRight: 5,
                }}
              />
              {label.replace(/_/g, " ")} {count(data.labels[label] ?? 0)}
            </span>
          ))}
        </div>
      </div>

      <div className="grid two" style={{ marginTop: 14 }}>
        <div className="panel">
          <h2>Operating companies only</h2>
          <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
            Blank-cheque targets are held out. A SPAC merger's registrant survives the
            closing, renames and carries on filing, so its deal protection is a
            different instrument and mixing it in moves the break rate.
          </p>
          <table>
            <tbody>
              <tr><td>Episodes</td><td className="num">{count(operating.episodes)}</td></tr>
              <tr><td>Resolved</td><td className="num">{count(operating.resolved)}</td></tr>
              <tr><td>Break candidates</td><td className="num">{count(operating.break_events)}</td></tr>
              <tr><td>Completion rate</td><td className="num">{pct(operating.completion_rate)}</td></tr>
              <tr><td>Blank-cheque episodes held out</td><td className="num">{count(data.shell_episodes)}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h2>What this universe does not claim</h2>
          {(data.caveats ?? []).map((caveat, index) => (
            <p key={index} className="caveat">{caveat}</p>
          ))}
        </div>
      </div>

      <div className="grid two" style={{ marginTop: 14 }}>
        <div className="panel">
          <h2>Announcement forms</h2>
          <table>
            <tbody>
              {Object.entries(data.announcement_forms ?? {}).slice(0, 10).map(([form, n]) => (
                <tr key={form}><td className="mono">{form}</td><td className="num">{count(n)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel">
          <h2>Where the targets come from</h2>
          <table>
            <tbody>
              {Object.entries(data.top_sic ?? {}).slice(0, 10).map(([sic, n]) => (
                <tr key={sic}><td>{sic}</td><td className="num">{count(n)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
