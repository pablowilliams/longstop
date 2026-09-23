import { useMemo, useState } from "react";
import { ShareBars, Tornado } from "../components/charts";
import { money, pp } from "../format";
import {
  build,
  synergiesForBreakeven,
  type Company as CompanyIn,
  type Deal as DealIn,
} from "../model/proforma";
import { tornado, varianceDecomposition } from "../model/sensitivity";

const ACQUIRER: CompanyIn = {
  net_income: 800e6,
  diluted_shares: 400e6,
  share_price: 50,
  cash: 1_000e6,
  debt: 2_000e6,
  ebitda: 1_800e6,
  book_equity: 5_000e6,
};

const TARGET: CompanyIn = {
  net_income: 120e6,
  diluted_shares: 100e6,
  share_price: 20,
  cash: 150e6,
  debt: 600e6,
  ebitda: 300e6,
  book_equity: 900e6,
};

const BASE: DealIn = {
  offer_per_share: 26,
  cash_consideration_pct: 0.6,
  cash_from_balance_sheet_pct: 0.4,
  new_debt_rate: 0.06,
  forgone_cash_yield: 0.02,
  tax_rate: 0.25,
  pretax_synergies: 100e6,
  synergy_phasing: 1,
  transaction_fees: 50e6,
  refinance_target_debt: true,
  intangible_step_up: 400e6,
  intangible_life_years: 10,
};

interface Control {
  key: keyof DealIn;
  label: string;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
}

const CONTROLS: Control[] = [
  { key: "offer_per_share", label: "Offer per share", min: 20, max: 60, step: 0.5, format: (v) => `$${v.toFixed(2)}` },
  { key: "pretax_synergies", label: "Pre-tax synergies", min: 0, max: 400e6, step: 10e6, format: money },
  { key: "cash_consideration_pct", label: "Cash consideration", min: 0, max: 1, step: 0.05, format: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "cash_from_balance_sheet_pct", label: "Funded from balance sheet", min: 0, max: 1, step: 0.05, format: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "new_debt_rate", label: "New debt rate", min: 0.02, max: 0.12, step: 0.0025, format: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "tax_rate", label: "Tax rate", min: 0.1, max: 0.35, step: 0.01, format: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "synergy_phasing", label: "Synergies realised", min: 0.2, max: 1, step: 0.05, format: (v) => `${(v * 100).toFixed(0)}%` },
  { key: "intangible_step_up", label: "Intangible step-up", min: 0, max: 1_200e6, step: 50e6, format: money },
  { key: "transaction_fees", label: "Transaction fees", min: 0, max: 150e6, step: 5e6, format: money },
];

export function ModelView() {
  const [deal, setDeal] = useState<DealIn>(BASE);
  const [error, setError] = useState<string | null>(null);

  // Computed in the browser, from the model in src/model, which is checked
  // against the Python implementation by src/model/__tests__/parity.test.ts on
  // every build. No server, so the sliders are instant.
  const result = useMemo(() => {
    try {
      setError(null);
      const pro_forma = build(ACQUIRER, TARGET, deal);
      return {
        pro_forma: {
          ...pro_forma,
          synergies_for_breakeven: synergiesForBreakeven(ACQUIRER, TARGET, deal),
        },
        tornado: tornado(ACQUIRER, TARGET, deal),
        decomposition: varianceDecomposition(ACQUIRER, TARGET, deal, undefined, 2000, 0),
      };
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [deal]);

  const tornadoRows = useMemo(
    () =>
      (result?.tornado ?? []).map((swing) => ({
        assumption: swing.assumption,
        low: swing.accretion_at_low,
        high: swing.accretion_at_high,
      })),
    [result],
  );

  const pf = result?.pro_forma;
  const decomposition = result?.decomposition;

  return (
    <div className="grid two">
      <div className="panel">
        <h2>Assumptions</h2>
        {CONTROLS.map((control) => (
          <div className="slider" key={control.key}>
            <div className="row">
              <span>{control.label}</span>
              <b>{control.format(deal[control.key] as number)}</b>
            </div>
            <input
              type="range"
              min={control.min}
              max={control.max}
              step={control.step}
              value={deal[control.key] as number}
              onChange={(event) =>
                setDeal({ ...deal, [control.key]: Number(event.target.value) })
              }
            />
          </div>
        ))}
        <label className="row muted" style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
          <input
            type="checkbox"
            checked={deal.refinance_target_debt}
            onChange={(event) => setDeal({ ...deal, refinance_target_debt: event.target.checked })}
          />
          Refinance the target's debt
        </label>
        <button className="ghost" style={{ marginTop: 14 }} onClick={() => setDeal(BASE)}>
          Reset to base case
        </button>
        <p className="muted" style={{ fontSize: 12, marginTop: 14 }}>
          Acquirer and target are a worked example, not a real pair. The point of the
          panel is that the answer moves, and by how much.
        </p>
      </div>

      <div>
        {error && <p className="err">{error}</p>}
        {pf && decomposition && (
          <>
            <div className="grid four">
              <div className="panel stat">
                <div className="label">Accretion</div>
                <div className="value" style={{ color: pf.accretion_pct >= 0 ? "var(--good)" : "var(--bad)" }}>
                  {pp(pf.accretion_pct)}
                </div>
                <div className="note">EPS {pf.pro_forma_eps.toFixed(3)} vs {pf.acquirer_standalone_eps.toFixed(3)}</div>
              </div>
              <div className="panel stat">
                <div className="label">Premium</div>
                <div className="value">{pf.premium_pct.toFixed(1)}%</div>
                <div className="note">to the unaffected price</div>
              </div>
              <div className="panel stat">
                <div className="label">Synergies to break even</div>
                <div className="value">{money(pf.synergies_for_breakeven)}</div>
                <div className="note">solved, not searched</div>
              </div>
              <div className="panel stat">
                <div className="label">Pro forma leverage</div>
                <div className="value">
                  {pf.pro_forma_net_debt_to_ebitda === null ? "n/a" : `${pf.pro_forma_net_debt_to_ebitda.toFixed(2)}x`}
                </div>
                <div className="note">net debt to EBITDA</div>
              </div>
            </div>

            <div className="panel" style={{ marginTop: 14 }}>
              <h2>Sources and uses</h2>
              <table>
                <tbody>
                  <tr><td>Equity purchase price</td><td className="num">{money(pf.sources_and_uses.equity_purchase_price)}</td></tr>
                  <tr><td>Target debt refinanced</td><td className="num">{money(pf.sources_and_uses.target_debt_refinanced)}</td></tr>
                  <tr><td>Transaction fees</td><td className="num">{money(pf.sources_and_uses.transaction_fees)}</td></tr>
                  <tr><td><b>Total uses</b></td><td className="num"><b>{money(pf.sources_and_uses.total_uses)}</b></td></tr>
                  <tr><td>Cash from balance sheet</td><td className="num">{money(pf.sources_and_uses.cash_from_balance_sheet)}</td></tr>
                  <tr><td>New debt</td><td className="num">{money(pf.sources_and_uses.new_debt)}</td></tr>
                  <tr><td>New equity issued</td><td className="num">{money(pf.sources_and_uses.new_equity)}</td></tr>
                  <tr><td>Target cash acquired</td><td className="num">{money(pf.sources_and_uses.target_cash_acquired)}</td></tr>
                  <tr><td><b>Total sources</b></td><td className="num"><b>{money(pf.sources_and_uses.total_sources)}</b></td></tr>
                  <tr>
                    <td>Balances</td>
                    <td className="num" style={{ color: pf.sources_and_uses.balances ? "var(--good)" : "var(--bad)" }}>
                      {pf.sources_and_uses.balances ? "yes" : "no"}
                    </td>
                  </tr>
                  <tr><td>Goodwill</td><td className="num">{money(pf.goodwill)}</td></tr>
                </tbody>
              </table>
            </div>

            <div className="panel" style={{ marginTop: 14 }}>
              <h2>One assumption at a time</h2>
              <Tornado rows={tornadoRows} />
            </div>

            <div className="panel" style={{ marginTop: 14 }}>
              <h2>All of them at once</h2>
              <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
                Sampling every assumption together, the base case sits at{" "}
                <span className="mono">{pp(decomposition.base_accretion_pct)}</span> inside a
                distribution running <span className="mono">{pp(decomposition.p5)}</span> to{" "}
                <span className="mono">{pp(decomposition.p95)}</span>. The deal is accretive in{" "}
                <span className="mono">{(decomposition.sign_flips * 100).toFixed(0)}%</span> of
                draws, which is the argument against quoting the point estimate on its own.
              </p>
              <ShareBars shares={decomposition.share_of_variance} />
              <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
                First-order shares from squared standardised regression coefficients, exact for
                a linear model and an approximation otherwise. R² of that fit is{" "}
                <span className="mono">{decomposition.linear_r_squared.toFixed(3)}</span> over{" "}
                {decomposition.samples.toLocaleString("en-GB")} draws, so the shares are worth
                reading only to the extent that number is high.
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
