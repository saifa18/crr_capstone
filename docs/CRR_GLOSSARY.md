# CRR Glossary

Short, plain-language definitions for demo prep. Matches how each term is
actually used in this app — not a general market-education document.

**CRR (Congestion Revenue Right)**
A financial instrument ERCOT auctions that pays (or, for an Obligation,
can charge) its holder based on the price difference between two grid
points. Bought to hedge — or speculate on — transmission congestion.

**Source**
The grid point a CRR is measured *from*. Paired with a Sink to define a
path.

**Sink**
The grid point a CRR is measured *to*. Paired with a Source to define a
path.

**Path**
A Source → Sink pair. The unit everything in this app is organized
around (Explorer, Path Settlements, per-participant activity).

**Obligation**
A CRR type whose payoff is the raw settlement spread (Sink SPP − Source
SPP) — can be positive or negative, meaning the holder can owe money.

**Option**
A CRR type whose payoff is the settlement spread floored at zero — the
holder never owes money, only ever receives or breaks even.

**SPP (Settlement Point Price)**
ERCOT's real Day-Ahead Market price at a specific settlement point
(hub, load zone, or node), for a specific hour. The live input to Path
Settlements' math.

**Settlement (Path Settlement Value)**
What a CRR position was actually worth, computed from real ERCOT SPPs:
Sink SPP − Source SPP for Obligations, floored at zero for Options,
multiplied by awarded MW. Not the same as auction price, and not
necessarily net trading profit — acquisition cost and fees aren't
included.

**Auction price (clearing price)**
What a participant paid (or was awarded) for a CRR at ERCOT's auction.
Sizing/cost information, not a settlement outcome.

**Notional value**
Awarded MW × auction clearing price. A sizing figure for comparing
position size — not a time-scaled total settlement amount.

**Net MW**
Sum of a participant's awarded MW across matching certificates, signed
so a BUY adds and a SELL subtracts.

**Certificate**
One CRR award record — one row of "this participant was awarded this
much MW, this type, this path, this auction month."

**Time of use (TOU)**
An hour-of-day/day-of-week bucket (Peak Weekday, Peak Weekend, Off-Peak)
used to group settlement and pricing data.

**Binding constraint**
A real ERCOT transmission element whose capacity limit was reached in a
given hour, from ERCOT's live Day-Ahead security-constrained
optimization — the physical reason two grid points can price apart.

**Contingency**
The outage/scenario ERCOT was evaluating when a constraint became
binding. "BASE CASE" means no modeled outage — the element was binding
under normal system conditions.

**Base case**
See Contingency — the "no assumed outage" condition.

**Shadow price**
The marginal economic impact ($/MWh) of one binding constraint —
roughly, how much relaxing that one limit by 1 MW would be worth. Not a
CRR settlement price, an auction price, or profit.

**Element endpoints**
The two physical substations (From Station / To Station) that a
monitored transmission element connects — not a CRR Source/Sink.
