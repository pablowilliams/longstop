// Mirrors longstop.api.schemas. A field renamed on the server breaks the build
// here rather than rendering as undefined in the browser.

export type Label =
  | "completed"
  | "completed_shell"
  | "terminated"
  | "acquirer_side"
  | "pending"
  | "unresolved"
  | "not_registrant";

export interface DealRow {
  cik: number;
  company: string;
  sic_description: string;
  tickers: string[];
  announced: string;
  label: Label;
  resolved_on: string | null;
  days_to_resolution: number | null;
  announcement_forms: string[];
  evidence: string[];
  shell: boolean;
}

export interface DealPage {
  total: number;
  offset: number;
  limit: number;
  rows: DealRow[];
}

export interface BreakRow {
  cik: number;
  company: string;
  announced: string;
  resolved_on: string | null;
  days_to_resolution: number | null;
  status: string;
  reasons: string[];
  break_fee_usd: number | null;
  document: string | null;
  excerpt: string;
}

export interface UniverseSummary {
  episodes: number;
  labels: Record<string, number>;
  resolved: number;
  break_events: number;
  break_events_explicit: number;
  completion_rate: number | null;
  completion_rate_denominator: number;
  shell_episodes: number;
  operating_company_deals: {
    episodes: number;
    resolved: number;
    break_events: number;
    completion_rate: number | null;
  };
  unresolved_share: number | null;
  excluded: Record<string, number>;
  sign_to_close_days: {
    n: number;
    p10: number | null;
    median: number | null;
    p90: number | null;
  };
  by_year: Record<string, Record<string, number>>;
  announcement_forms?: Record<string, number>;
  top_sic?: Record<string, number>;
  caveats?: string[];
  index?: Record<string, unknown>;
}

export interface CompanyIn {
  net_income: number;
  diluted_shares: number;
  share_price: number;
  cash: number;
  debt: number;
  ebitda: number;
  book_equity: number;
}

export interface DealIn {
  offer_per_share: number;
  cash_consideration_pct: number;
  cash_from_balance_sheet_pct: number;
  new_debt_rate: number;
  forgone_cash_yield: number;
  tax_rate: number;
  pretax_synergies: number;
  synergy_phasing: number;
  transaction_fees: number;
  refinance_target_debt: boolean;
  intangible_step_up: number;
  intangible_life_years: number;
}

export interface SourcesAndUses {
  equity_purchase_price: number;
  target_debt_refinanced: number;
  transaction_fees: number;
  cash_from_balance_sheet: number;
  new_debt: number;
  new_equity: number;
  target_cash_acquired: number;
  total_uses: number;
  total_sources: number;
  balances: boolean;
}

export interface ProForma {
  sources_and_uses: SourcesAndUses;
  shares_issued: number;
  pro_forma_shares: number;
  pro_forma_net_income: number;
  pro_forma_eps: number;
  acquirer_standalone_eps: number;
  accretion_pct: number;
  premium_pct: number;
  goodwill: number;
  pro_forma_net_debt: number;
  pro_forma_net_debt_to_ebitda: number | null;
  after_tax_synergies: number;
  incremental_interest: number;
  forgone_interest: number;
  incremental_amortisation: number;
  synergies_for_breakeven: number;
  announced_synergies_required_note: string;
}

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

export interface ProFormaResponse {
  pro_forma: ProForma;
  tornado: Swing[];
  decomposition: Decomposition;
}

// The published dashboard has no server. These files are built from the same
// data the API serves, by `make site`, and are committed, so the numbers on the
// page are the numbers in the repository rather than whatever a running process
// happened to hold. The FastAPI app is still there for programmatic access.

const BASE = import.meta.env.BASE_URL;

async function file<T>(name: string): Promise<T> {
  const response = await fetch(`${BASE}data/${name}`);
  if (!response.ok) {
    throw new Error(
      `${response.status} loading ${name}. Run \`make site\` to build the data files.`,
    );
  }
  return (await response.json()) as T;
}

let dealsCache: DealRow[] | null = null;
let breaksCache: BreakRow[] | null = null;

export const api = {
  summary: () => file<UniverseSummary>("summary.json"),

  deals: async (params: {
    label?: string;
    q?: string;
    limit?: number;
    offset?: number;
  }): Promise<DealPage> => {
    dealsCache = dealsCache ?? (await file<DealRow[]>("deals.json"));
    let rows = dealsCache;
    if (params.label) rows = rows.filter((row) => row.label === params.label);
    if (params.q) {
      const needle = params.q.toLowerCase();
      rows = rows.filter(
        (row) =>
          row.company.toLowerCase().includes(needle) ||
          (row.tickers ?? []).join(" ").toLowerCase().includes(needle),
      );
    }
    const offset = params.offset ?? 0;
    const limit = params.limit ?? 50;
    return { total: rows.length, offset, limit, rows: rows.slice(offset, offset + limit) };
  },

  breaks: async (status?: string): Promise<BreakRow[]> => {
    breaksCache = breaksCache ?? (await file<BreakRow[]>("breaks.json"));
    return status ? breaksCache.filter((row) => row.status === status) : breaksCache;
  },
};
