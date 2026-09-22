export function money(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}bn`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(0)}m`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(0)}k`;
  return `$${value.toFixed(0)}`;
}

export function pct(value: number | null, digits = 1): string {
  return value === null ? "n/a" : `${(value * 100).toFixed(digits)}%`;
}

export function pp(value: number, digits = 2): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function count(value: number): string {
  return value.toLocaleString("en-GB");
}
