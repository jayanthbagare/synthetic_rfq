# Hermes RFQ Skill Suite — Meridian Industrial Systems

Seven skills for end-to-end procurement automation: Sales Order → Work Order →
Vendor Selection → RFQ Emails → Bid Tracking → Evaluation → Shortlist.

Messaging channel: **Telegram**  
Workspace: **Google Workspace** (Gmail, Calendar, Drive, Docs, Sheets)  
Simulation layer: **MiroFish** (scenarios 1, 6, 7)  
Data source: `generate_rfq_data.py` (19 CSVs in Google Drive)

---

## Skill map

```
rfq-orchestrator          ← master coordinator (start here)
├── rfq-vendor-selector   ← Phase 1: picks 8 vendors from master sheet
├── rfq-email-composer    ← Phase 2: sends personalised Gmail RFQs
├── rfq-email-tracker     ← Phase 3: monitors inbox, extracts bids (cron)
├── rfq-bid-evaluator     ← Phase 4: weighted scoring of received bids
├── rfq-vendor-finalizer  ← Phase 5: produces shortlist + Drive summary
└── mirofish-rfq-bridge   ← cross-phase: simulation bridge (scenarios 1,6,7)
```

---

## Installation

```bash
# 1. Copy all skills to Hermes skills directory
cp hermes-skills/*.md ~/.hermes/skills/

# 2. Verify Hermes sees them
hermes skills list | grep rfq

# 3. Set required environment variables
hermes config set MERIDIAN_DRIVE_FOLDER_ID   "your_drive_folder_id"
hermes config set MERIDIAN_VENDOR_SHEET_ID   "your_vendor_sheet_id"
hermes config set MERIDIAN_SHEETS_BID_LOG_ID "your_bid_log_sheet_id"
hermes config set PROCUREMENT_EMAIL          "procurement@meridian-industrial.com"
hermes config set MIROFISH_BASE_URL          "http://localhost:5001"

# 4. Ensure google-workspace skill is active
hermes skills install official/productivity/google-workspace

# 5. Start gateway on Telegram
hermes gateway

# 6. Pin critical skills (prevents auto-archival)
hermes curator pin rfq-orchestrator
hermes curator pin rfq-email-tracker
hermes curator pin mirofish-rfq-bridge
```

---

## Google Sheets structure required

Create a Google Sheet and note its ID as `MERIDIAN_SHEETS_BID_LOG_ID`.
Add these tabs (exact names):

| Tab name | Purpose |
|---|---|
| `Vendors` | Mirror of `01_vendors.csv` |
| `WorkOrders` | Mirror of `07_work_orders.csv` |
| `RFQEvents` | One row per RFQ issued |
| `RFQInvites` | One row per vendor invited per RFQ |
| `EmailLog` | One row per email sent/received with Gmail thread IDs |
| `Bids` | All incoming bid records |
| `BidEvaluation` | Scored and ranked bids |
| `Shortlist` | Final 5 vendors per RFQ |
| `Disputes` | Open vendor disputes |
| `MiroFishPredictions` | Predictions from all three scenarios |

Create a second Sheet for vendor master (`MERIDIAN_VENDOR_SHEET_ID`) with tab `Vendors`.

Upload the 19 CSVs from `generate_rfq_data.py` to the Drive folder
(`MERIDIAN_DRIVE_FOLDER_ID`). The MiroFish bridge loads these directly.

---

## Triggering from Telegram

```
# Start a full RFQ pipeline
/rfq WO-2024-0042

# Check bid status mid-cycle
/bids RFQ-0042

# Trigger evaluation manually
/evaluate RFQ-0042

# Finalise shortlist manually
/finalize RFQ-0042

# Run MiroFish simulations
/mirofish 1 RFQ-0042     ← vendor pre-sim (before emails)
/mirofish 6 RFQ-0042     ← supply shock (after shortlist)
/mirofish 7 V021         ← new vendor profiling

# Natural language also works:
"Start procurement for WO-2024-0042"
"Any bids on the Kovacs RFQ?"
"Run a stress test on the shortlist"
"Profile Helios Micro Systems before we invite them"
```

---

## Cron jobs set automatically

| Job | Schedule | Purpose |
|---|---|---|
| `bid-monitor-{rfq_id}` | `*/30 * * * *` | Poll Gmail for new bids |
| `rfq-deadline-check` | `0 8 * * *` | Morning check: upcoming deadlines |

---

## Data flow

```
generate_rfq_data.py
        │
        ▼
  Google Drive (19 CSVs)
        │
  ┌─────┴──────────────────────────────────────┐
  │                                            │
  ▼                                            ▼
Google Sheets                            MiroFish
(live operational data)            (simulation engine)
  │                                            │
  └───────────────┬────────────────────────────┘
                  │
            Hermes Skills
                  │
            Telegram Bot
```

---

## Environment variables reference

| Variable | Description |
|---|---|
| `MERIDIAN_DRIVE_FOLDER_ID` | Google Drive folder containing all 19 CSV data files |
| `MERIDIAN_VENDOR_SHEET_ID` | Sheets ID of the vendor master workbook |
| `MERIDIAN_SHEETS_BID_LOG_ID` | Sheets ID of the operational bid log workbook |
| `PROCUREMENT_EMAIL` | Gmail address used to send/receive RFQ emails |
| `MIROFISH_BASE_URL` | MiroFish API base URL (local or remote) |
