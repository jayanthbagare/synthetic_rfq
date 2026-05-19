# MiroFish — RFQ Simulation Run Guide

Complete instructions for running MiroFish against the Meridian Industrial
Systems RFQ dataset. Covers setup, seed file preparation, and step-by-step
walkthroughs for all three scenarios used in this training program.

---

## What MiroFish actually does (before you touch anything)

MiroFish is not a REST API you POST data to. It is a **5-stage pipeline** with
a browser UI. Each stage must complete before the next unlocks. Understanding
this flow prevents confusion:

```
Stage 1 — Graph Build     Upload seed docs → GraphRAG knowledge graph (Zep)
Stage 2 — Env Setup       Knowledge graph → agent personas + simulation config
Stage 3 — Simulation      Agents run interaction rounds in parallel (Twitter + Reddit)
Stage 4 — Report          ReportAgent synthesises findings into structured markdown
Stage 5 — Deep Interact   Chat with any agent or the ReportAgent directly
```

The "Twitter" and "Reddit" platforms in MiroFish are **role-playing environments**,
not actual social media. In our RFQ context they map to:
- **Twitter agents** → vendors making quick bid decisions, reacting to market signals
- **Reddit agents** → vendor communities deliberating, sharing supply chain intel

You guide the simulation through your **seed documents** and your
**prediction requirement** (one natural language sentence). MiroFish does the
rest automatically.

---

## Part 1 — Install and configure MiroFish

### Option A: Docker (recommended for training)

```bash
git clone https://github.com/666ghj/MiroFish.git
cd MiroFish
cp .env.example .env
```

Edit `.env`:
```env
# Any OpenAI-compatible LLM endpoint
# For training: Claude via Anthropic API (use a proxy that wraps it as OpenAI format)
# Or: Qwen-plus on Alibaba DashScope (recommended by MiroFish team, generous free tier)
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# Zep Cloud — free tier is enough for this training program
# Sign up at: https://app.getzep.com/
ZEP_API_KEY=your_zep_api_key_here
```

```bash
# Start everything
docker compose up -d

# Verify services
curl http://localhost:3000   # frontend
curl http://localhost:5001   # backend Flask API
```

### Option B: Source (if you need to inspect internals)

```bash
git clone https://github.com/666ghj/MiroFish.git
cd MiroFish
cp .env.example .env
# edit .env as above

# Install all dependencies in one command
npm run setup:all

# Start both frontend and backend
npm run dev
```

Frontend: `http://localhost:3000`  
Backend API: `http://localhost:5001`

### Option C: Offline / fully local (no cloud APIs)

Use the English fork with local models:
```bash
git clone https://github.com/nikmcfly/MiroFish-Offline.git
cd MiroFish-Offline
cp .env.example .env
```
Edit `.env` for local stack:
```env
LLM_API_KEY=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL_NAME=qwen2.5:14b      # 14b fits on 16GB VRAM; use 32b for best results

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=mirofish

EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_BASE_URL=http://localhost:11434
```
```bash
# Pull models first (one-time, large download)
ollama pull qwen2.5:14b
ollama pull nomic-embed-text

# Start everything
docker compose up -d
```

> **Note for training demos**: Use Option A or B with DashScope/Qwen-plus. The
> free tier handles 40-round simulations comfortably. Avoid running > 40 rounds
> until you know your cost structure — 1000 agents × 50 rounds ≈ 50,000 LLM
> calls.

---

## Part 2 — Prepare seed documents from the synthetic data

MiroFish accepts **PDF, MD, or TXT files**. The CSVs from `generate_rfq_data.py`
need to be converted into narrative seed documents that MiroFish's GraphRAG can
extract entities and relationships from. Raw CSV dumps are not good seeds —
they lack the relational narrative that GraphRAG needs.

Run this script to generate the three scenario seed documents:

```bash
python3 prepare_mirofish_seeds.py
# Outputs to ./mirofish_seeds/
#   scenario_1_vendor_presim.md
#   scenario_6_supply_shock.md
#   scenario_7_new_vendor.md
```

### Seed preparation script

```python
# prepare_mirofish_seeds.py
# Converts synthetic CSV data into narrative seed documents for MiroFish
import pandas as pd, os, textwrap
from datetime import datetime

DATA_DIR   = "./output"   # from generate_rfq_data.py
SEED_DIR   = "./mirofish_seeds"
os.makedirs(SEED_DIR, exist_ok=True)

vendors  = pd.read_csv(f"{DATA_DIR}/01_vendors.csv")
perf     = pd.read_csv(f"{DATA_DIR}/02_vendor_performance.csv")
comms    = pd.read_csv(f"{DATA_DIR}/03_commodity_prices.csv")
signals  = pd.read_csv(f"{DATA_DIR}/04_market_signals.csv")
bids     = pd.read_csv(f"{DATA_DIR}/12_bids.csv")
evals    = pd.read_csv(f"{DATA_DIR}/13_bid_evaluation.csv")
personas = pd.read_csv(f"{DATA_DIR}/17_mirofish_agent_personas.csv")
events   = pd.read_csv(f"{DATA_DIR}/18_mirofish_world_events.csv")

# ── Scenario 1 seed ───────────────────────────────────────────────────────────
def build_scenario_1_seed():
    lines = [
        "# Meridian Industrial Systems — Vendor Procurement Intelligence Report",
        f"*Generated: {datetime.now().strftime('%B %Y')}*\n",
        "## Executive Summary",
        "Meridian Industrial Systems (MIS) is a Bangalore-based manufacturer of "
        "CNC machines and robotic assembly cells. This report profiles the active "
        "vendor ecosystem for Mechanical Parts, Electrical Components, and Raw "
        "Materials procurement. Meridian issues approximately 180 RFQs per year "
        "across 24 active vendors in 3 categories.\n",
        "## Vendor Profiles\n",
    ]

    for _, v in vendors[vendors["is_new_vendor"] == False].iterrows():
        # Last 3 months of performance
        vp = perf[perf["vendor_id"] == v["vendor_id"]].tail(3)
        avg_otd = vp["on_time_delivery_rate"].mean() if len(vp) else v["base_otd_rate"]
        avg_pi  = vp["price_index"].mean() if len(vp) else v["base_price_index"]

        lines.append(f"### {v['vendor_name']} ({v['country']})")
        lines.append(
            f"Category: {v['category']}. Relationship: {v['relationship_years']} years. "
            f"Behavioural profile: {v['behavioral_archetype'].replace('_',' ')}. "
            f"Risk tier: {v['risk_tier']}. Certifications: {v['certifications']}. "
            f"Average on-time delivery (recent): {avg_otd:.0%}. "
            f"Price index vs market: {avg_pi:.2f} "
            f"({'below' if avg_pi < 1.0 else 'above'} market). "
            f"Payment preference: {v['preferred_payment_terms']}. "
            f"Financial health score: {v['financial_health_score']}/10.\n"
        )

    lines += [
        "## Recent Market Signals\n",
        "The following events have occurred in the past 18 months and are "
        "affecting vendor behaviour and bid patterns:\n",
    ]
    for _, s in signals.iterrows():
        lines.append(f"- **{s['date']}** ({s['signal_type']}, source: {s['source']}): "
                     f"{s['full_text']}")

    lines += [
        "\n## Prediction Requirement",
        "Given current market conditions and each vendor's historical behaviour, "
        "predict which vendors are most likely to submit competitive bids for the "
        "next Mechanical Parts RFQ, what price band they will bid at relative to "
        "the market index, and their probable lead time commitment.",
    ]

    with open(f"{SEED_DIR}/scenario_1_vendor_presim.md", "w") as f:
        f.write("\n".join(lines))
    print("✓ scenario_1_vendor_presim.md written")

# ── Scenario 6 seed ───────────────────────────────────────────────────────────
def build_scenario_6_seed():
    shock_events = events[events["scenario"] == "scenario_6"]
    recent_comms = comms[comms["shock_flag"] == 1].groupby("commodity").tail(4)

    lines = [
        "# Meridian Industrial Systems — Supply Chain Disruption Intelligence Brief",
        f"*Classified: Procurement Risk Assessment — {datetime.now().strftime('%B %Y')}*\n",
        "## Situation Overview",
        "Meridian Industrial Systems has shortlisted 5 vendors for RFQ-0042 "
        "(Mechanical Parts, €38,000 estimated value). Before issuing purchase orders, "
        "procurement management has requested a stress test of each vendor's resilience "
        "under the following active market disruptions.\n",
        "## Active Disruption Events\n",
    ]

    for _, e in shock_events.iterrows():
        lines.append(f"### {e['event_type'].replace('_',' ').title()}: {e['description'][:60]}…")
        lines.append(
            f"Date: {e['event_date']}. Severity: {e['severity_1_10']}/10. "
            f"Affected roles: {e['affected_agent_roles']}. "
            f"Full description: {e['description']} "
            f"Mitigation options: {e['mitigation_option_1']}; {e['mitigation_option_2']}.\n"
        )

    lines += ["\n## Commodity Price Impact\n"]
    for _, r in recent_comms.iterrows():
        lines.append(
            f"- **{r['commodity']}** ({r['unit']}): Price {r['price']:.2f} "
            f"as of week {r['week_start']}. Shock-affected: YES."
        )

    lines += [
        "\n## Shortlisted Vendor Profiles\n",
        "The following 5 vendors have been shortlisted and must be stress-tested:\n",
    ]

    shortlisted = evals[evals["selected"] == True].drop_duplicates("vendor_id").head(5)
    for _, e in shortlisted.iterrows():
        v = vendors[vendors["vendor_id"] == e["vendor_id"]].iloc[0]
        lines.append(
            f"- **{v['vendor_name']}** ({v['country']}): "
            f"{v['behavioral_archetype'].replace('_',' ')}, "
            f"capacity utilisation {v['capacity_utilization_pct']}%, "
            f"financial health {v['financial_health_score']}/10, "
            f"risk tier: {v['risk_tier']}."
        )

    lines += [
        "\n## Prediction Requirement",
        "Under each of the active disruption events listed above, predict for each "
        "shortlisted vendor: (1) their resilience — will they hold their bid price "
        "and delivery commitment? (2) by how much will their price likely revise "
        "upward? (3) what is the probability they cannot fulfil the purchase order? "
        "(4) which mitigation option is each vendor most likely to invoke?",
    ]

    with open(f"{SEED_DIR}/scenario_6_supply_shock.md", "w") as f:
        f.write("\n".join(lines))
    print("✓ scenario_6_supply_shock.md written")

# ── Scenario 7 seed ───────────────────────────────────────────────────────────
def build_scenario_7_seed():
    new_vendors  = vendors[vendors["is_new_vendor"] == True]
    known_vendors= vendors[vendors["is_new_vendor"] == False]

    lines = [
        "# Meridian Industrial Systems — New Vendor Due Diligence Report",
        f"*Procurement Risk: New Vendor Onboarding — {datetime.now().strftime('%B %Y')}*\n",
        "## Background",
        "Meridian has identified 4 new vendors not yet in the approved vendor list. "
        "These vendors have no transaction history with Meridian. To assess their "
        "likely bid behaviour, this report pairs each new vendor with 2 established "
        "analog vendors whose profiles are most similar in category, country risk, "
        "and company size.\n",
        "## New Vendor Profiles\n",
    ]

    for _, nv in new_vendors.iterrows():
        lines.append(f"### Candidate: {nv['vendor_name']} ({nv['country']}, {nv['city']})")
        lines.append(
            f"Category: {nv['category']}. Onboarded: {nv['onboarded_date']}. "
            f"Risk tier: {nv['risk_tier']}. Financial health: {nv['financial_health_score']}/10. "
            f"Certifications: {nv['certifications']}. Payment terms: {nv['preferred_payment_terms']}. "
            f"No historical RFQ participation. Behavioral prior: unknown.\n"
        )

        # Find 2 analogs: same category, established, medium or low risk
        analogs = known_vendors[
            (known_vendors["category"] == nv["category"]) &
            (known_vendors["risk_tier"].isin(["low","medium"]))
        ].head(2)

        lines.append("**Analog vendors used to construct behavioral prior:**\n")
        for _, av in analogs.iterrows():
            ap = perf[perf["vendor_id"] == av["vendor_id"]].tail(6)
            avg_otd = ap["on_time_delivery_rate"].mean() if len(ap) else av["base_otd_rate"]
            avg_pi  = ap["price_index"].mean() if len(ap) else av["base_price_index"]
            avg_rr  = ap["response_rate"].mean() if len(ap) else av["base_response_rate"]
            lines.append(
                f"- **{av['vendor_name']}** ({av['country']}): "
                f"{av['behavioral_archetype'].replace('_',' ')}, "
                f"{av['relationship_years']} yr relationship, "
                f"OTD {avg_otd:.0%}, price index {avg_pi:.2f}, "
                f"response rate {avg_rr:.0%}, "
                f"quality score {av['base_quality_score']}/10.\n"
            )

    lines += [
        "\n## Prediction Requirement",
        "For each new vendor candidate above, use the behavioral profiles of the "
        "paired analog vendors to construct a synthetic behavioral prior. Predict: "
        "(1) the probability the new vendor will respond to an initial RFQ invite, "
        "(2) their expected bid price relative to the market index, "
        "(3) their likely lead time commitment, "
        "(4) a synthetic trust score (0–1) reflecting predicted reliability, "
        "(5) the appropriate maximum trial PO value to limit exposure.",
    ]

    with open(f"{SEED_DIR}/scenario_7_new_vendor.md", "w") as f:
        f.write("\n".join(lines))
    print("✓ scenario_7_new_vendor.md written")

build_scenario_1_seed()
build_scenario_6_seed()
build_scenario_7_seed()
print(f"\nSeed files written to {os.path.abspath(SEED_DIR)}/")
print("Upload each .md file to MiroFish at http://localhost:3000")
```

After running this you'll have three `.md` files, one per scenario.
Each is 2–4 pages of dense, structured narrative — the right size for MiroFish
(longer than a news article, shorter than a book).

---

## Part 3 — Running Scenario 1: Vendor Pre-Simulation

**Purpose**: Before sending real RFQ emails, predict which vendors will respond
and at what price band. The output informs `rfq-vendor-selector`.

**When in the Hermes flow**: Between Phase 0 (work order parsed) and Phase 2
(emails sent). Hermes calls `/mirofish 1 {rfq_id}` to trigger this.

### Step-by-step in the MiroFish UI

**1. Open** `http://localhost:3000` → you see the Home page with a file drop zone.

**2. Upload seed file**  
Drag `mirofish_seeds/scenario_1_vendor_presim.md` into the upload zone.
You can also upload `03_commodity_prices.csv` and `04_market_signals.csv`
as supplementary seed files (MiroFish accepts multiple files per project).

**3. Enter prediction requirement**  
In the text field below the upload zone, paste exactly:

```
For the upcoming Meridian Industrial Systems RFQ in the Mechanical Parts
category, predict which of the profiled vendors will submit a bid, at what
price band relative to the market index, and their likely lead time
commitment. Flag any vendors showing signs of capacity stress or price
volatility based on their recent performance trends.
```

**4. Click "Start Engine" (启动引擎)**  
MiroFish submits the files to the Flask backend. The backend:
- Extracts entities (vendors, commodities, market events, relationships)
- Sends them to Zep Cloud to build a GraphRAG knowledge graph
- You see a real-time D3.js graph forming — nodes are vendors, commodities,
  countries; edges are relationships

This takes **3–8 minutes** depending on seed document size and LLM speed.
Watch the graph grow — when no new edges appear for 30 seconds, it's done.

**5. Click "Continue" → Stage 2: Environment Setup**  
MiroFish generates agent personas automatically from the knowledge graph.
You'll see profiles appearing: each vendor becomes a Twitter-style agent with:
- A unique personality derived from their behavioral archetype
- Memory seeded with their historical performance narrative
- Activity schedule (when they "post" = when they place bids)

For Scenario 1, expect **20–30 agents** (vendors + buyer + market agents).

**6. Click "Continue" → Stage 3: Run Simulation**  
Click **Start Simulation**.

Recommended settings for Scenario 1:
- **Rounds**: 25–30 (enough for bid decisions to emerge without excessive cost)
- Both Twitter and Reddit platforms enabled

Watch the live feed — vendor agents will:
- "Post" their bid decisions (aggressive bidders post early with low prices)
- "Repost" or "like" market signal posts (showing they noticed supply disruptions)
- "Do nothing" for some rounds (indicating they're still deliberating)

The pattern of activity = the simulation's prediction of real behavior.

**7. Click "Continue" → Stage 4: Report Generation**  
The ReportAgent runs its three-tool analysis loop:
- `InsightForge` — deep-dives on each vendor agent's decisions
- `PanoramaSearch` — full-scope view of bid price distributions
- `InterviewAgents` — directly queries vendor agents: "Why did you bid at this price?"

The final report will contain:
- Ranked list of vendors by predicted response probability
- Price band estimates per vendor (with confidence ranges)
- Lead time predictions
- Risk flags for volatile/stressed vendors

**8. Stage 5: Deep Interaction — extract the predictions**  
After reading the report, use the ReportAgent chat to extract structured data:

```
You: Give me a JSON list of each vendor with their predicted response
probability (0-1), bid price range vs market index (low, high), and
lead time in days. Format as an array of objects.
```

Copy the JSON response → paste into the `MiroFishPredictions` tab of your
Google Sheet (or let the `mirofish-rfq-bridge` Hermes skill do this automatically
when triggered via `/mirofish 1 {rfq_id}`).

**Also interview individual agents** to understand edge cases:
```
[Select agent: "Cerro Negro Metals SA agent"]
You: Why did you decide to bid aggressively on this RFQ?
Agent: [responds based on its seeded memory and behavioral rules]
```

---

## Part 4 — Running Scenario 6: Supply Shock Stress Test

**Purpose**: After the 5-vendor shortlist is set, stress-test each against
active market disruptions before committing to purchase orders.

**When in the Hermes flow**: After `rfq-bid-evaluator` (Phase 4), before PO
issuance. Hermes calls `/mirofish 6 {rfq_id}`.

### Step-by-step in the MiroFish UI

**1. Create a new project** (do not reuse Scenario 1's project — different seed)

**2. Upload seed file**  
Upload `mirofish_seeds/scenario_6_supply_shock.md`.  
Also upload `18_mirofish_world_events.csv` (the shock events file).

**3. Enter prediction requirement**

```
Meridian Industrial Systems has shortlisted 5 vendors for an urgent
Mechanical Parts procurement. Three simultaneous supply chain shocks are
active: Hamburg port strike (3-week backlog), US aluminium tariff (+25%),
and rare earth quota cuts from China (+28% on neodymium). Predict how each
shortlisted vendor will respond to these pressures: will they hold their
quoted price and delivery date, by how much will they revise upward, and
what is the probability they cannot fulfil the purchase order?
```

**4. Start Engine → wait for graph build**  
The graph for Scenario 6 is richer — it includes shock events as entities,
with edges to the vendors they affect (e.g. "Hamburg strike → affects →
Kovacs Precision GmbH"). Watch for these cross-edges forming. They are the
causal chains MiroFish will simulate.

**5. Stage 2: Environment Setup**  
Agents include:
- The 5 shortlisted vendor agents
- A market analyst agent (represents the LME / commodity desk)
- A freight forwarder agent (Suez/Hamburg routing intel)
- An EU trade desk regulator agent
- A Meridian buyer agent

**6. Stage 3: Simulation — inject shocks mid-run**  
Start the simulation with **40–50 rounds**.

MiroFish injects market signal posts automatically from the seed data. You can
also **manually inject variables** mid-simulation from the God's-eye view:

After round 10, click the injection panel and add:
```
Variable: aluminium_price_shock_pct = 25
Affected agents: all vendor agents with aluminium exposure
Message: "BREAKING: US imposes 25% tariff on aluminium imports effective immediately"
```

Watch which vendor agents:
- Immediately revise their "bid" posts upward (volatile/aggressive archetypes)
- Stay quiet and absorb the shock (reliable/conservative archetypes)
- Drop out of the feed entirely (highest dropout risk)

**7. Report + Deep Interaction**  
Ask the ReportAgent:
```
You: For each of the 5 shortlisted vendors, give me:
1. Their resilience score (0-1) under the combined shocks
2. Expected price revision percentage
3. Expected lead time extension in days
4. Dropout probability
Format as a JSON array.
```

Use this output to feed back into `rfq-bid-evaluator`'s MiroFish blend step
(15% resilience weight on composite score).

**Interview the at-risk vendor directly:**
```
[Select: vendor agent with highest dropout probability]
You: You dropped out of the bidding simulation. What would change your decision?
```

The agent's answer tells you exactly what Meridian could offer (faster payment,
smaller minimum order, volume guarantee) to retain this vendor — actionable
procurement intelligence.

---

## Part 5 — Running Scenario 7: New Vendor Synthetic Due Diligence

**Purpose**: Build a behavioral profile for a new vendor with no transaction
history, using established analog vendors as the behavioral prior.

**When in the Hermes flow**: On-demand, before `rfq-vendor-selector` includes
a new vendor on an invite list. Triggered via `/mirofish 7 {vendor_id}`.

### Step-by-step in the MiroFish UI

**1. Create a new project**

**2. Upload seed file**  
Upload `mirofish_seeds/scenario_7_new_vendor.md`.

**3. Enter prediction requirement**

```
Meridian Industrial Systems is evaluating four new vendors with no transaction
history. For each new vendor, use the behavioral profiles of the paired analog
vendors to construct a behavioral prior. Predict each new vendor's: response
probability to an initial RFQ, expected bid price vs market, likely lead time,
synthetic trust score (0-1), and maximum recommended trial purchase order value
to limit Meridian's exposure on first engagement.
```

**4. Stage 2: Environment Setup — what to watch**  
MiroFish will generate agents for:
- Each new vendor (persona built from scratch — watch how sparse their profiles are)
- Each analog vendor (rich profiles drawn from 18 months of seeded history)
- A Meridian buyer agent

The key thing to observe: the new vendor agents start with **generic, thin
profiles**. As the simulation runs, they inherit behavioral tendencies from
their analog neighbors in the social graph. This is the synthetic prior forming.

**5. Stage 3: Simulation — shorter run**  
Use **20–25 rounds** (new vendor profiling converges faster than shock scenarios).

Watch the new vendor agents copy and adapt the analog vendors' posting patterns.
An `aggressive_bidder` analog → the new vendor will skew toward competitive
early posting. A `conservative` analog → the new vendor will post late and
formally.

**6. Report + Deep Interaction**

Ask:
```
You: For each new vendor candidate, synthesise a behavioral profile based on
how they interacted with the analog vendors. Provide: (1) synthetic trust
score 0-1, (2) estimated RFQ response rate, (3) expected bid relative to
market, (4) recommended maximum trial PO value in USD, (5) onboarding risk
rating: low/medium/high.
Return as JSON.
```

Interview the new vendor agent directly:
```
[Select: "Helios Micro Systems agent"]
You: If invited to bid on a €15,000 electrical components RFQ with a 21-day
deadline, how would you respond and what price would you offer?
```

The agent's answer — drawn from its analog-informed persona — gives the
`rfq-vendor-selector` a probability-weighted prior to work with.

---

## Part 6 — Practical guidance for the training program

### Simulation cost control

| Setting | Training demo | Full simulation |
|---|---|---|
| Rounds | 15–25 | 40–50 |
| Agents | Auto (MiroFish decides) | Auto |
| Seed doc size | 3–5 pages | 5–15 pages |
| Est. LLM tokens | 500K–1.5M | 2M–5M |
| Qwen-plus cost | ~$0.50–$1.50 | ~$2–$5 |

Start every demo run at 20 rounds. Only go to 50 if the 20-round report lacks
sufficient differentiation between vendors.

### Reusing a knowledge graph

Once Stage 1 (graph build) completes for a seed document, the graph is saved
in Zep. You can run **multiple simulations from the same graph** with different
prediction requirements — skipping the 3–8 minute graph build each time.

From the History view in MiroFish:
- Click on a previous project
- Click "New Simulation" — jumps directly to Stage 2
- Change the prediction requirement text
- Proceed to Stage 3

Use this when demonstrating Scenarios 1 and 6 back-to-back — build the graph
once with a combined seed, then run two separate simulations from it.

### What makes a good seed document

| Good | Bad |
|---|---|
| Named entities with relationships | Anonymous descriptions |
| Historical events with dates | Generic statements |
| Behavioral patterns with examples | One-line vendor summaries |
| Market signals with quantified impact | Vague trend claims |
| Narrative arc (things changed over time) | Flat static snapshots |

The `prepare_mirofish_seeds.py` script above is built around these principles.
Each seed includes named vendors, quantified performance data, dated events,
and causal language ("Hamburg strike → delays → Kovacs affected").

### Reading the simulation output for the training audience

When debriefing the simulation results with your training group, use these
three questions to structure the discussion:

1. **What surprised you?** — Which vendor agent behaved differently from what
   the scoring model predicted? Why might a swarm simulation surface that when
   a spreadsheet didn't?

2. **Where did emergence happen?** — Did any vendor agents collectively change
   behaviour after a shock injection that no single agent would have done alone?
   That's the Theory of Constraints angle — the constraint becomes visible when
   the system is stressed.

3. **What would you do differently in procurement?** — If MiroFish predicted
   vendor X has 60% dropout probability under a port disruption, how does that
   change your shortlisting, your PO split, or your buffer stock strategy?

These questions connect MiroFish's output back to the Hermes RFQ pipeline and
to the TOC / Throughput Accounting framing of Edge Consulting.

---

## Part 7 — Connecting MiroFish output back to Hermes

After each scenario run, the predictions need to reach the Hermes skill layer.
There are two paths:

### Path A: Manual (for training demos)

1. Copy the JSON from MiroFish's ReportAgent chat
2. Open the Google Sheet `MERIDIAN_SHEETS_BID_LOG_ID`
3. Paste into the `MiroFishPredictions` tab, with columns:
   `rfq_id | vendor_id | scenario | score/probability | notes | date`
4. Hermes skills (`rfq-vendor-selector`, `rfq-bid-evaluator`) read this tab
   automatically on their next run

### Path B: Automated via Hermes skill (production)

The `mirofish-rfq-bridge` skill handles this end-to-end when triggered from
Telegram. It:
1. Generates the seed document programmatically from the live Sheets data
2. Uploads it to MiroFish via the Flask backend API
3. Polls the backend for completion
4. Parses the report output via the ReportAgent chat endpoint
5. Writes structured predictions back to the `MiroFishPredictions` Sheet tab

For Path B to work with the current MiroFish version, the bridge uses these
actual backend endpoints (confirmed from the source):

```
POST http://localhost:5001/api/projects
  multipart/form-data: files[], requirement (text)
  → returns: { project_id }

GET  http://localhost:5001/api/projects/{project_id}/status
  → returns: { stage, status, graph_id }

POST http://localhost:5001/api/simulation/start
  body: { project_id }
  → returns: { simulation_id }

GET  http://localhost:5001/api/simulation/{simulation_id}/run_state
  → returns: { status, current_round, total_rounds }

POST http://localhost:5001/api/report/generate
  body: { simulation_id }
  → returns: { report_id }

POST http://localhost:5001/api/report/chat
  body: { report_id, message, history: [] }
  → returns: { response }
```

These map exactly to what `mirofish-rfq-bridge.md` calls `submit_to_mirofish()`
and `poll_mirofish()`. The bridge collapses all 5 stages into one Hermes skill
invocation.

---

## Quick reference

```
MiroFish UI       http://localhost:3000
MiroFish API      http://localhost:5001

Seed files        ./mirofish_seeds/
  scenario_1_vendor_presim.md      → 25 rounds, ~$1
  scenario_6_supply_shock.md       → 40 rounds, ~$2
  scenario_7_new_vendor.md         → 20 rounds, ~$0.75

Hermes trigger    /mirofish 1|6|7 {rfq_id or vendor_id}

Output goes to    Google Sheet: MiroFishPredictions tab

Key skills that read MiroFish output:
  rfq-vendor-selector   (reads scenario_1 response probabilities)
  rfq-bid-evaluator     (reads scenario_6 resilience scores)
  rfq-vendor-finalizer  (flags scenario_7 new vendors in shortlist)
```
