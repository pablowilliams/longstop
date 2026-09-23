// The merger model exists twice: in Python, where it is the source of truth, and
// in TypeScript, so the deployed page can move a slider without a server.
//
// Two implementations of the same arithmetic drift apart quietly. Python writes
// its answers to public/data/golden-proforma.json during `make site`, and this
// fails if TypeScript disagrees. Regenerate the golden file when the Python
// model changes on purpose; never edit it by hand to make a test pass.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { build, synergiesForBreakeven, type Company, type Deal } from "../proforma";
import { tornado, varianceDecomposition } from "../sensitivity";

interface Golden {
  acquirer: Company;
  target: Company;
  cases: Record<string, {
    deal: Deal;
    pro_forma: Record<string, number | Record<string, number | boolean>>;
    synergies_for_breakeven: number;
    tornado: { assumption: string; accretion_at_low: number; accretion_at_high: number }[];
  }>;
  decomposition: {
    share_of_variance: Record<string, number>;
    dominant: string[];
    base_accretion_pct: number;
  };
}

const golden: Golden = JSON.parse(
  readFileSync(join(__dirname, "../../../public/data/golden-proforma.json"), "utf8"),
);

const SCALAR_FIELDS = [
  "shares_issued", "pro_forma_shares", "pro_forma_net_income", "pro_forma_eps",
  "acquirer_standalone_eps", "accretion_pct", "premium_pct", "goodwill",
  "pro_forma_net_debt", "after_tax_synergies", "incremental_interest",
  "forgone_interest", "incremental_amortisation",
] as const;

const SOURCES_FIELDS = [
  "equity_purchase_price", "target_debt_refinanced", "transaction_fees",
  "cash_from_balance_sheet", "new_debt", "new_equity", "target_cash_acquired",
  "total_uses", "total_sources",
] as const;

describe("the TypeScript model agrees with Python", () => {
  for (const [name, expected] of Object.entries(golden.cases)) {
    describe(name, () => {
      const actual = build(golden.acquirer, golden.target, expected.deal);

      for (const field of SCALAR_FIELDS) {
        it(`matches ${field}`, () => {
          const target = expected.pro_forma[field] as number;
          expect(actual[field]).toBeCloseTo(target, 6);
        });
      }

      for (const field of SOURCES_FIELDS) {
        it(`matches sources and uses: ${field}`, () => {
          const target = (expected.pro_forma.sources_and_uses as Record<string, number>)[field];
          expect(actual.sources_and_uses[field]).toBeCloseTo(target, 6);
        });
      }

      it("balances, as Python says it does", () => {
        expect(actual.sources_and_uses.balances).toBe(
          (expected.pro_forma.sources_and_uses as Record<string, boolean>).balances,
        );
      });

      it("solves the same break-even", () => {
        expect(synergiesForBreakeven(golden.acquirer, golden.target, expected.deal))
          .toBeCloseTo(expected.synergies_for_breakeven, 4);
      });

      it("produces the same tornado, in the same order", () => {
        const actualSwings = tornado(golden.acquirer, golden.target, expected.deal);
        expect(actualSwings.map((s) => s.assumption)).toEqual(
          expected.tornado.map((s) => s.assumption),
        );
        actualSwings.forEach((swing, index) => {
          expect(swing.accretion_at_low).toBeCloseTo(expected.tornado[index].accretion_at_low, 6);
          expect(swing.accretion_at_high).toBeCloseTo(expected.tornado[index].accretion_at_high, 6);
        });
      });
    });
  }
});

describe("the decomposition agrees in shape", () => {
  // The two languages do not share a random number generator, so the draws
  // differ by construction. What has to agree is the conclusion.
  const actual = varianceDecomposition(
    golden.acquirer, golden.target, golden.cases.base.deal, undefined, 4000, 0,
  );

  it("puts synergies first, as Python does", () => {
    expect(actual.dominant[0]).toBe(golden.decomposition.dominant[0]);
  });

  it("agrees on each assumption's share within two points", () => {
    for (const [name, share] of Object.entries(golden.decomposition.share_of_variance)) {
      expect(actual.share_of_variance[name]).toBeCloseTo(share, 1);
    }
  });

  it("agrees on the base case, which is not sampled", () => {
    // Python rounds its decomposition outputs to four places for readability in
    // the JSON; the model itself is exact and is checked to six places above.
    expect(actual.base_accretion_pct).toBeCloseTo(golden.decomposition.base_accretion_pct, 3);
  });

  it("explains most of the variance linearly, or says it does not", () => {
    expect(actual.linear_r_squared).toBeGreaterThan(0.5);
    expect(actual.linear_r_squared).toBeLessThanOrEqual(1);
  });
});
