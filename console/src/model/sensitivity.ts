// Sensitivity views, ported from src/longstop/finance/sensitivity.py.
//
// The tornado is deterministic and is checked against Python's answers exactly.
// The decomposition samples, and two languages do not share a random number
// generator, so its test checks that the ordering and the magnitudes agree
// rather than that two different RNGs produce identical draws.

import { build, type Company, type Deal } from "./proforma";

export type Assumption = keyof Pick<
  Deal,
  | "pretax_synergies"
  | "cash_consideration_pct"
  | "cash_from_balance_sheet_pct"
  | "new_debt_rate"
  | "tax_rate"
  | "synergy_phasing"
  | "intangible_step_up"
  | "transaction_fees"
  | "forgone_cash_yield"
>;

export const DEFAULT_RANGES: Record<Assumption, [number, number]> = {
  pretax_synergies: [0, 300e6],
  cash_consideration_pct: [0, 1],
  cash_from_balance_sheet_pct: [0, 1],
  new_debt_rate: [0.03, 0.1],
  tax_rate: [0.15, 0.3],
  synergy_phasing: [0.4, 1],
  intangible_step_up: [0, 1_000e6],
  transaction_fees: [10e6, 120e6],
  forgone_cash_yield: [0, 0.05],
};

export interface Swing {
  assumption: string;
  low_value: number;
  high_value: number;
  accretion_at_low: number;
  accretion_at_high: number;
  swing_pp: number;
}

export interface Decomposition {
  base_accretion_pct: number;
  mean_accretion_pct: number;
  std_accretion_pp: number;
  p5: number;
  p95: number;
  share_of_variance: Record<string, number>;
  linear_r_squared: number;
  samples: number;
  sign_flips: number;
  dominant: string[];
}

function accretion(acquirer: Company, target: Company, deal: Deal, over: Partial<Deal>): number {
  return build(acquirer, target, { ...deal, ...over }).accretion_pct;
}

export function tornado(
  acquirer: Company,
  target: Company,
  deal: Deal,
  ranges: Record<string, [number, number]> = DEFAULT_RANGES,
): Swing[] {
  const swings = Object.entries(ranges).map(([name, [low, high]]) => {
    const atLow = accretion(acquirer, target, deal, { [name]: low } as Partial<Deal>);
    const atHigh = accretion(acquirer, target, deal, { [name]: high } as Partial<Deal>);
    return {
      assumption: name,
      low_value: low,
      high_value: high,
      accretion_at_low: atLow,
      accretion_at_high: atHigh,
      swing_pp: Math.abs(atHigh - atLow),
    };
  });
  return swings.sort((a, b) => b.swing_pp - a.swing_pp);
}

// Seeded so the page gives the same answer twice. A different generator from
// Python's, which is why the parity test compares shape rather than draws.
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Solves (X'X)b = X'y by Gaussian elimination with partial pivoting. */
function leastSquares(design: number[][], y: number[]): number[] {
  const k = design[0].length;
  const xtx: number[][] = Array.from({ length: k }, () => new Array(k).fill(0));
  const xty: number[] = new Array(k).fill(0);
  for (let row = 0; row < design.length; row += 1) {
    for (let i = 0; i < k; i += 1) {
      xty[i] += design[row][i] * y[row];
      for (let j = 0; j < k; j += 1) xtx[i][j] += design[row][i] * design[row][j];
    }
  }
  const augmented = xtx.map((row, i) => [...row, xty[i]]);
  for (let col = 0; col < k; col += 1) {
    let pivot = col;
    for (let row = col + 1; row < k; row += 1) {
      if (Math.abs(augmented[row][col]) > Math.abs(augmented[pivot][col])) pivot = row;
    }
    [augmented[col], augmented[pivot]] = [augmented[pivot], augmented[col]];
    const lead = augmented[col][col];
    if (Math.abs(lead) < 1e-12) continue;
    for (let row = 0; row < k; row += 1) {
      if (row === col) continue;
      const factor = augmented[row][col] / lead;
      for (let j = col; j <= k; j += 1) augmented[row][j] -= factor * augmented[col][j];
    }
  }
  return augmented.map((row, i) =>
    Math.abs(row[i]) < 1e-12 ? 0 : row[k] / row[i],
  );
}

function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return 0;
  const index = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length));
  return sorted[index];
}

export function varianceDecomposition(
  acquirer: Company,
  target: Company,
  deal: Deal,
  ranges: Record<string, [number, number]> = DEFAULT_RANGES,
  samples = 2000,
  seed = 0,
): Decomposition {
  const names = Object.keys(ranges);
  const random = mulberry32(seed);

  const draws: number[][] = [];
  const outputs: number[] = [];
  for (let i = 0; i < samples; i += 1) {
    const row = names.map((name) => {
      const [low, high] = ranges[name];
      return low + random() * (high - low);
    });
    draws.push(row);
    outputs.push(
      accretion(
        acquirer, target, deal,
        Object.fromEntries(names.map((name, j) => [name, row[j]])) as Partial<Deal>,
      ),
    );
  }

  const mean = outputs.reduce((a, b) => a + b, 0) / samples;
  const variance = outputs.reduce((a, b) => a + (b - mean) ** 2, 0) / (samples - 1);
  const spread = Math.sqrt(variance);

  const shares: Record<string, number> = {};
  let rSquared = 0;
  if (spread > 0) {
    const columnMeans = names.map((_, j) => draws.reduce((a, r) => a + r[j], 0) / samples);
    const columnStd = names.map((_, j) =>
      Math.sqrt(draws.reduce((a, r) => a + (r[j] - columnMeans[j]) ** 2, 0) / (samples - 1)),
    );
    const usable = names.map((_, j) => columnStd[j] > 0);
    const design = draws.map((row) => {
      const scaled = names
        .map((_, j) => (usable[j] ? (row[j] - columnMeans[j]) / columnStd[j] : null))
        .filter((v): v is number => v !== null);
      return [...scaled, 1];
    });
    const y = outputs.map((value) => (value - mean) / spread);
    const beta = leastSquares(design, y);
    const fitted = design.map((row) => row.reduce((a, v, i) => a + v * beta[i], 0));
    const residual = y.reduce((a, v, i) => a + (v - fitted[i]) ** 2, 0);
    const total = y.reduce((a, v) => a + v * v, 0);
    rSquared = Math.max(0, 1 - residual / total);

    const raw: Record<string, number> = {};
    let index = 0;
    names.forEach((name, j) => {
      raw[name] = usable[j] ? beta[index] ** 2 : 0;
      if (usable[j]) index += 1;
    });
    const sum = Object.values(raw).reduce((a, b) => a + b, 0) || 1;
    for (const name of names) shares[name] = Math.round((raw[name] / sum) * 1e4) / 1e4;
  } else {
    for (const name of names) shares[name] = 0;
  }

  const sorted = [...outputs].sort((a, b) => a - b);
  const ordered = Object.entries(shares).sort((a, b) => b[1] - a[1]);
  const dominant: string[] = [];
  let running = 0;
  for (const [name, share] of ordered) {
    dominant.push(name);
    running += share;
    if (running >= 0.8) break;
  }

  return {
    base_accretion_pct: build(acquirer, target, deal).accretion_pct,
    mean_accretion_pct: mean,
    std_accretion_pp: spread,
    p5: percentile(sorted, 5),
    p95: percentile(sorted, 95),
    share_of_variance: shares,
    linear_r_squared: rSquared,
    samples,
    sign_flips: outputs.filter((v) => v > 0).length / samples,
    dominant,
  };
}
