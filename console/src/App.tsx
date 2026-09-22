import { useState } from "react";
import { BreaksView } from "./views/BreaksView";
import { DealsView } from "./views/DealsView";
import { ModelView } from "./views/ModelView";
import { UniverseView } from "./views/UniverseView";

const TABS = [
  { id: "universe", label: "Universe", render: () => <UniverseView /> },
  { id: "deals", label: "Deals", render: () => <DealsView /> },
  { id: "breaks", label: "Breaks", render: () => <BreaksView /> },
  { id: "model", label: "Merger model", render: () => <ModelView /> },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function App() {
  const [tab, setTab] = useState<TabId>("universe");
  const active = TABS.find((candidate) => candidate.id === tab) ?? TABS[0];

  return (
    <div className="shell">
      <header className="top">
        <h1>Longstop</h1>
        <span className="sub">
          Deal outcomes derived from EDGAR filings, and the merger arithmetic that goes with them
        </span>
      </header>

      <nav className="tabs">
        {TABS.map((candidate) => (
          <button
            key={candidate.id}
            aria-current={candidate.id === tab}
            onClick={() => setTab(candidate.id)}
          >
            {candidate.label}
          </button>
        ))}
      </nav>

      {active.render()}

      <footer className="note">
        Analysis of public filings about real companies. Not investment advice, and no figure
        here is a forecast. Outcome labels are derived from filings rather than annotated, and
        every rate is shown with the count behind it.
      </footer>
    </div>
  );
}
