# Longstop

**Do the deal protection terms predict the break, or has the market already
priced them?**

A longstop date is the deadline in a merger agreement by which the deal must
close or either side can walk. This repository is built around what happens
before that date arrives, on every US public-target merger since 2001.

Announced deals complete somewhere above nine times in ten. That base rate is
the trap in this problem, because a model predicting "closes" for every deal
scores in the nineties and knows nothing. Accuracy is therefore not reported
anywhere in this project. What gets reported is calibration, and expected value
under the asymmetry that governs the trade: a completion pays a few percent, a
break costs twenty or thirty.

## The part that makes it measurable

Nobody labels these outcomes and no vendor is needed to find them. A company
that is acquired stops being a registrant, and the filing that ends its
registration is the label. A company whose deal died carries on filing quarterly
reports, and that is the label too. Both come out of EDGAR, free, for every deal
since 2001, from filing metadata alone.

The same principle covers prices. Merger proxies state the unaffected share
price and the premium in the fairness opinion, so the premium is read out of the
document rather than fetched from a price series. That matters more than it
sounds. Free price sources are patchy on delisted securities, completed deals
delist and broken deals do not, so a naive price pull silently keeps the breaks
and loses the completions. Reading the filing removes the bias rather than
managing it.

## The universe

<!-- universe:start -->
```
deal episodes              10,051
resolved                    7,750
break candidates              565   (unconfirmed: item 1.02 covers any material agreement)
blank-cheque targets          304   (segregated: a SPAC merger is a different instrument)

label                        count     share
  completed                  7,137     71.0%
  completed_shell               48      0.5%
  terminated                   565      5.6%
  acquirer_side                389      3.9%
  pending                       18      0.2%
  unresolved                 1,023     10.2%
  not_registrant               871      8.7%

completion rate             92.7% of 7,750 resolved

sign to close, days (completed deals)
  n 7,185   p10 31   median 72   p90 261

operating companies only (blank cheques removed)
  9,747 episodes, 7,473 resolved, 563 breaks, completion rate 92.5%

break detection depends on an 8-K item code, which the SEC only numbered from 2004
  first year above 50% item coverage: 2007
  earlier years carry completions but cannot carry breaks
  right censored, under-labelled by construction: 2025
```
<!-- universe:end -->

## What has been measured so far

### Six labelling errors, each of which produced a believable table

**A slow deal is not a broken one.** Survival was measured from the
announcement, so any deal taking more than a year to close looked like a deal
that never closed. It has to be measured from the resolution.

**The target does not file item 2.01.** Completion of an acquisition is what the
buyer reports. The target reports a change in control, item 5.01. A target-side
universe watching 2.01 misses most closings.

**A blank-cheque company does not deregister.** It renames and carries on
filing, reporting the change under item 5.06, so every completed SPAC merger was
counted as a break. They are segregated rather than mixed in, because deal
protection in a SPAC merger is a different instrument.

**Continued reporting does not undo a deregistration.** A company with public
debt keeps filing 10-Ks under Section 15(d) long after its equity delists.
Treating that as a contradiction marked real completions, Aircastle and
Cincinnati Bell among them, as ambiguous.

**An episode ended when a timer expired rather than when the deal resolved.**
A company that is the target of two deals in quick succession had them chained
into one, and the outcome of the second was recorded against the terms of the
first. An episode now also ends at a termination or a deregistration, whatever
the gap.

**An episode reached forward past the next deal to find its own outcome.** Baker
Hughes announced with Halliburton in February 2015, that deal was terminated in
May 2016, and the company delisted in July 2017 on closing with GE. The 2015
episode took the 2017 deregistration and was recorded as an 867 day completion,
with its own termination sitting unused in its evidence. The resolution horizon
is now capped at the next announcement.

Those last two mattered more than the rest. **They recovered 114 breaks, taking
the count from 451 to 565**, and both failed in the same direction: a hidden
break is invisible forever, whereas a false one is caught when the document is
read. That asymmetry is now the tie-breaking rule wherever the code has a
choice.

A further category has no metadata fix at all. A DEFM14A can be filed by a buyer
seeking approval to issue shares, and from metadata alone that is
indistinguishable from a target whose deal broke. Those are labelled
`acquirer_side` or `unresolved` and set aside rather than counted.

### The break label does not exist before 2004, and the data says so itself

Whether a deal broke is read from 8-K item 1.02. The SEC's numbered item scheme
arrived during 2004, so for earlier filings that evidence cannot exist. The
effect is visible without knowing the history:

| year | episodes carrying any 8-K item evidence |
|---|---|
| 2001 | 2.6% |
| 2003 | 12.7% |
| 2004 | 27.5% |
| 2007 | 54.2% |
| 2015 | 80.3% |

Completions are unaffected, because a deregistration is a form type rather than
an item code, which is why 2001 still resolves 410 deals by deregistration and
finds five breaks in 741 episodes. A 0.7% break rate is not a finding about
2001. It is the absence of a field.

So the universe runs from 2001 and **the break label is only usable from 2007**,
the first year above half coverage. The report computes that year from the data
rather than taking it from a date in a footnote, and the most recent year is
flagged separately as right censored, because a break usually becomes visible
only once the target has carried on reporting for a year after its last deal
filing.

Inside that window the break rate sits between 6.0% and 9.8% every year from 2007
to 2022, which is where the published figures sit. **2023 comes out at 2.5% and I
cannot currently explain it.** Its resolution coverage looks normal. It is either
a real feature of a thin deal year or a defect not yet found, and it is written
down here rather than smoothed over.

### A break is only a break once the document says so

8-K item 1.02 reports the termination of any material definitive agreement, so a
cancelled revolving credit facility files exactly like a dead merger. One 2020
episode resolved four days after its own definitive proxy, which is not a deal
dying. So every candidate is read.

That reading needed one thing that is easy to miss. Filings define a term once
and use the abbreviation forever after, and the Aon and Willis Towers Watson 8-K,
among the clearest breaks in the dataset, says only that **"the BCA was
terminated by mutual consent"**. No list of agreement names will ever match
that. The classifier therefore harvests the document's own definitions, reading
each `(the "X")` together with the text in front of it, and the nearest phrase
decides which class the abbreviation belongs to. Nearest, not merger-first:
giving merger priority classified that same filing's credit agreement as a
merger agreement.

Verdicts keep the text they were based on, and a document that does not say
clearly is recorded as unclear rather than counted.

**The result is the reason the document layer exists.** Of 437 break candidates
inside the usable window, across 5,523 resolved deals:

| | candidates | as a share of resolved deals |
|---|---|---|
| raw item 1.02 label | 437 | 7.91% |
| confirmed a merger died | 105 | 1.90% |
| shown to be something else entirely | 160 | |
| undecided, and left that way | 172 | |

**More than a third of the raw label is not a deal break.** It is employee stock
option plans, equity forward contracts, revolving credit facilities and the sale
of an apartment complex, all filed under the same item. A model trained on the
raw label trains on a third noise, and its calibration would be measuring
paperwork rather than deals.

What the check cannot do is manufacture certainty. The honest statement is that
the break rate lies between 1.90% and 5.02% depending on the 172 undecided, and
the upper bound sits at the low end of the published range. Some real breaks
never file item 1.02 at all, which puts them among the unresolved rather than
among the candidates, so the candidate set is a floor too. Both bounds are
reported. Neither is split.

Among the confirmed breaks the stated reason was mutual agreement 17 times and
regulatory 11 times, with a superior proposal, a failed shareholder vote and a
material adverse effect claim behind them.

### Extraction that checks itself

A merger proxy states the per-share consideration, the unaffected price and the
premium, in three places hundreds of pages apart. They are arithmetically
related, so an extraction can be checked against the document itself:

```
premium = consideration / unaffected price - 1
```

When the three extracted figures satisfy that identity, all three were read
correctly and no annotator was needed to say so. When they do not, the
extraction reports a mismatch instead of a number. That is what makes extraction
accuracy measurable on real filings without a labelled set.

### The merger model, and what actually drives it

The pro forma is the arithmetic a deal team does in a spreadsheet, written down
so it can be tested: sources and uses that must balance, purchase price
allocation, accretion or dilution, pro forma leverage. The synergy break-even is
solved in closed form rather than searched, because accretion is linear in
synergies.

The prediction going in was that synergies and the financing mix dominate the
answer. Half of that is wrong. Sampling every assumption together on the worked
deal:

| assumption | share of variance |
|---|---|
| pre-tax synergies | 62.2% |
| intangible step-up | 13.2% |
| synergy phasing | 11.7% |
| new debt rate | 8.9% |
| cash against stock mix | 0.1% |

**The three assumptions asserted with the least evidence account for 87% of the
answer, and the one negotiated hardest contributes almost nothing.** The base
case sits at +6.8% inside a distribution running -6.5% to +17.8%, and the deal is
accretive in 71% of draws, which is the argument against quoting a point
estimate at all.

First-order shares come from squared standardised regression coefficients, exact
for a linear model and an approximation otherwise, so the R squared of that fit
is reported next to them.

## Run it

```bash
make setup
export LONGSTOP_CONTACT="you@example.com"   # the SEC requires clients to identify themselves
make test
make universe          # both stages plus the report
make breaks            # read every break candidate's 8-K
make console-install
make console-build
make api               # API and console on :8000
```

The contact address is read from the environment and never stored in the
repository. The client refuses to make a request without one, rate limits itself
below the SEC's stated ceiling, caches every response, and records the targets it
could not reach rather than discarding the ones it could. A rebuild after the
first run needs no network.

Stage one transfers roughly three gigabytes of quarterly filing indexes and keeps
only the matching rows. Stage two is threaded, because a filer's submissions JSON
runs to megabytes and one request at a time projected to over eight hours.

## The console

Four views, typed against the API schemas so a field renamed on the server breaks
the build rather than rendering as undefined. The universe and its outcomes by
year, the deal table, every break candidate with the text its verdict was based
on, and the merger model with a live assumption panel, a tornado and the variance
decomposition. Charts are inline SVG.

## Honest limits

- **S-4 and 425 filings are excluded**, because their registrant is the acquirer
  and this universe is keyed on the target. Deals where the target filed neither
  a proxy nor a 14D-9 fall outside it.
- **The episode gap is a parameter, not a truth.** Eighteen months separates one
  company's two deals from one company's one long deal. The value is in the
  output so its effect on the deal count is visible, and resolution events split
  episodes regardless of it.
- **The terms extractor is deterministic and abstains.** Patterns miss. The
  reconciliation is what makes the misses visible rather than silent, and the
  language-model adapter sits behind the same interface so the numbers still
  reproduce without a key.
- **No completion probability is modelled yet.** When one is, it will arrive with
  an interval and a sample size, and never as a bare figure.
- **Nothing here is advice.** It analyses public filings about real companies.

## Licence

MIT. Filings are fetched from EDGAR under the SEC's terms of use and are not
redistributed here.
