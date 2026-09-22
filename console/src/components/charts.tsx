// Inline SVG. A tornado and a few bars do not justify a charting dependency, and
// a dependency would have to be themed anyway.
//
// Everything here uses a wide viewBox scaled uniformly. Stretching the box to
// fit with preserveAspectRatio="none" stretches the text along with the bars,
// which turned the axis labels into unreadable glyphs.

const WIDTH = 1000;

interface StackRow {
  key: string;
  counts: Record<string, number>;
}

const LABEL_COLOURS: Record<string, string> = {
  completed: "#4fbf8b",
  completed_shell: "#3f8f70",
  terminated: "#e2645c",
  acquirer_side: "#6aa6ff",
  unresolved: "#d6a54a",
  pending: "#8b95a5",
  not_registrant: "#4a5260",
};

export function colourFor(label: string): string {
  return LABEL_COLOURS[label] ?? "#6aa6ff";
}

export function StackedBars({ rows, order, height = 210 }: {
  rows: StackRow[];
  order: string[];
  height?: number;
}) {
  const totals = rows.map((row) => order.reduce((sum, key) => sum + (row.counts[key] ?? 0), 0));
  const peak = Math.max(1, ...totals);
  const barWidth = WIDTH / Math.max(rows.length, 1);
  const plot = height - 26;
  const labelEvery = Math.max(1, Math.ceil(rows.length / 12));

  return (
    <svg viewBox={`0 0 ${WIDTH} ${height}`} style={{ width: "100%", height }}>
      {rows.map((row, index) => {
        let offset = 0;
        const x = index * barWidth;
        return (
          <g key={row.key}>
            {order.map((label) => {
              const count = row.counts[label] ?? 0;
              if (!count) return null;
              const barHeight = (count / peak) * plot;
              const y = plot - offset - barHeight;
              offset += barHeight;
              return (
                <rect
                  key={label}
                  x={x + barWidth * 0.14}
                  y={y}
                  width={barWidth * 0.72}
                  height={barHeight}
                  fill={colourFor(label)}
                >
                  <title>{`${row.key} ${label.replace(/_/g, " ")}: ${count}`}</title>
                </rect>
              );
            })}
            {index % labelEvery === 0 && (
              <text x={x + barWidth / 2} y={height - 8} fill="#8b95a5" fontSize="12" textAnchor="middle">
                {row.key}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export function Tornado({ rows }: { rows: { assumption: string; low: number; high: number }[] }) {
  if (!rows.length) return null;
  const extent = Math.max(...rows.flatMap((row) => [Math.abs(row.low), Math.abs(row.high)]), 1);
  const rowHeight = 30;
  const height = rows.length * rowHeight + 24;
  const scale = (value: number) => WIDTH / 2 + (value / extent) * (WIDTH * 0.45);

  return (
    <svg viewBox={`0 0 ${WIDTH} ${height}`} style={{ width: "100%", height }}>
      <line x1={scale(0)} x2={scale(0)} y1={0} y2={height - 22} stroke="#39414f" strokeWidth="1" />
      {rows.map((row, index) => {
        const left = Math.min(scale(row.low), scale(row.high));
        const right = Math.max(scale(row.low), scale(row.high));
        const y = index * rowHeight + 5;
        return (
          <g key={row.assumption}>
            <rect x={left} y={y} width={Math.max(right - left, 2)} height={12} fill="#6aa6ff" opacity="0.85">
              <title>
                {`${row.assumption}: ${row.low.toFixed(2)}pp to ${row.high.toFixed(2)}pp`}
              </title>
            </rect>
            <text x={8} y={y + 24} fill="#8b95a5" fontSize="12">
              {row.assumption.replace(/_/g, " ")}
            </text>
          </g>
        );
      })}
      <text x={scale(0)} y={height - 6} fill="#8b95a5" fontSize="12" textAnchor="middle">
        EPS neutral
      </text>
    </svg>
  );
}

export function ShareBars({ shares }: { shares: Record<string, number> }) {
  const entries = Object.entries(shares)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <p className="muted">No assumption explains any variance here.</p>;
  return (
    <div>
      {entries.map(([name, share]) => (
        <div key={name} style={{ marginBottom: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
            <span className="muted">{name.replace(/_/g, " ")}</span>
            <span className="mono">{(share * 100).toFixed(1)}%</span>
          </div>
          <div style={{ background: "#1d222b", height: 6, borderRadius: 3 }}>
            <div style={{ width: `${share * 100}%`, height: 6, borderRadius: 3, background: "#6aa6ff" }} />
          </div>
        </div>
      ))}
    </div>
  );
}
