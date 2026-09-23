// The merger consequences model, ported from src/longstop/finance/proforma.py so
// the deployed page can move a slider without a server.
//
// Two implementations of the same arithmetic is exactly the situation where they
// drift apart quietly, so the Python one writes its answers to
// public/data/golden-proforma.json and model.test.ts fails if this disagrees.
// Python remains the source of truth; this file follows it.

export interface Company {
  net_income: number;
  diluted_shares: number;
  share_price: number;
  cash: number;
  debt: number;
  ebitda: number;
  book_equity: number;
}

export interface Deal {
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
}

export function eps(company: Company): number {
  if (company.diluted_shares === 0) throw new Error("diluted_shares cannot be zero");
  return company.net_income / company.diluted_shares;
}

export function premium(offerPerShare: number, unaffectedPrice: number): number {
  if (unaffectedPrice <= 0) throw new Error("unaffected_price must be positive");
  return 100 * (offerPerShare / unaffectedPrice - 1);
}

export function build(acquirer: Company, target: Company, deal: Deal): ProForma {
  const equityPrice = deal.offer_per_share * target.diluted_shares;
  const cashPortion = equityPrice * deal.cash_consideration_pct;
  const stockPortion = equityPrice - cashPortion;

  const debtRefinanced = deal.refinance_target_debt ? target.debt : 0;
  const cashNeeded = cashPortion + debtRefinanced + deal.transaction_fees;

  let fromBalanceSheet = Math.min(
    cashNeeded * deal.cash_from_balance_sheet_pct,
    Math.max(acquirer.cash, 0),
  );
  let newDebt = cashNeeded - fromBalanceSheet - target.cash;
  if (newDebt < 0) {
    // More cash available than the deal needs. The excess is not a negative
    // borrowing, it simply is not raised.
    fromBalanceSheet += newDebt;
    newDebt = 0;
  }

  const sharesIssued = acquirer.share_price > 0 ? stockPortion / acquirer.share_price : 0;

  const afterTax = 1 - deal.tax_rate;
  const afterTaxSynergies = deal.pretax_synergies * deal.synergy_phasing * afterTax;
  const incrementalInterest = newDebt * deal.new_debt_rate * afterTax;
  const forgoneInterest = fromBalanceSheet * deal.forgone_cash_yield * afterTax;
  const incrementalAmortisation =
    deal.intangible_life_years > 0
      ? (deal.intangible_step_up / deal.intangible_life_years) * afterTax
      : 0;

  const proFormaNetIncome =
    acquirer.net_income +
    target.net_income +
    afterTaxSynergies -
    incrementalInterest -
    forgoneInterest -
    incrementalAmortisation;
  const proFormaShares = acquirer.diluted_shares + sharesIssued;
  const proFormaEps = proFormaNetIncome / proFormaShares;
  const standaloneEps = eps(acquirer);

  const goodwill = equityPrice - target.book_equity - deal.intangible_step_up;
  const proFormaEbitda =
    acquirer.ebitda + target.ebitda + deal.pretax_synergies * deal.synergy_phasing;
  const proFormaNetDebt =
    acquirer.debt +
    newDebt +
    (deal.refinance_target_debt ? 0 : target.debt) -
    Math.max(acquirer.cash - fromBalanceSheet, 0);

  const totalUses = equityPrice + debtRefinanced + deal.transaction_fees;
  const totalSources = fromBalanceSheet + newDebt + stockPortion + target.cash;

  return {
    sources_and_uses: {
      equity_purchase_price: equityPrice,
      target_debt_refinanced: debtRefinanced,
      transaction_fees: deal.transaction_fees,
      cash_from_balance_sheet: fromBalanceSheet,
      new_debt: newDebt,
      new_equity: stockPortion,
      target_cash_acquired: target.cash,
      total_uses: totalUses,
      total_sources: totalSources,
      balances: Math.abs(totalSources - totalUses) < 1,
    },
    shares_issued: sharesIssued,
    pro_forma_shares: proFormaShares,
    pro_forma_net_income: proFormaNetIncome,
    pro_forma_eps: proFormaEps,
    acquirer_standalone_eps: standaloneEps,
    accretion_pct: 100 * (proFormaEps / standaloneEps - 1),
    premium_pct: premium(deal.offer_per_share, target.share_price),
    goodwill,
    pro_forma_net_debt: proFormaNetDebt,
    pro_forma_net_debt_to_ebitda: proFormaEbitda > 0 ? proFormaNetDebt / proFormaEbitda : null,
    after_tax_synergies: afterTaxSynergies,
    incremental_interest: incrementalInterest,
    forgone_interest: forgoneInterest,
    incremental_amortisation: incrementalAmortisation,
  };
}

/**
 * Pre-tax synergies at which the deal is exactly EPS neutral.
 *
 * Solved rather than searched. Pro forma net income is linear in synergies and
 * the share count does not depend on them. A negative result means the deal is
 * already accretive without any.
 */
export function synergiesForBreakeven(
  acquirer: Company,
  target: Company,
  deal: Deal,
): number {
  const without = build(acquirer, target, { ...deal, pretax_synergies: 0 });
  const requiredAfterTax =
    eps(acquirer) * without.pro_forma_shares - without.pro_forma_net_income;
  const denominator = (1 - deal.tax_rate) * deal.synergy_phasing;
  if (denominator === 0) throw new Error("synergies cannot move EPS when phasing is zero");
  return requiredAfterTax / denominator;
}
