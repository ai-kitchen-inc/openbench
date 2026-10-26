# Lighthouser AI -- SEMAP Compliance Copilot

Full-stack example demonstrating OpenBench as the intelligence + orchestration layer for HUD SEMAP compliance automation.

## What This Demo Shows

A chat-based copilot for Public Housing Authorities (PHAs) that validates Housing Choice Voucher (HCV) compliance across three SEMAP indicators:

| Indicator | Area | HUD Reference |
|-----------|------|---------------|
| **SEMAP 2** | Rent Reasonableness | 24 CFR 982.507 |
| **SEMAP 3** | Income Determination | 24 CFR 5.609, 5.611 |
| **SEMAP 10** | Tenant Rent / TTP | 24 CFR 5.628, 982.505, 982.508 |

## OpenBench Capabilities Showcased

| Capability | How |
|------------|-----|
| BaseAgent + ToolExecutor | 17 domain-specific tools |
| Parallel tool execution | SEMAP 2 + 3 run concurrently in full review |
| Task planning | "Full SEMAP review" decomposed into steps |
| Interactive form review | Agent extracts RFTA data, generates pre-filled form, user reviews before calculations |
| Persistent memory | Remember previous voucher reviews |
| PDFSource | Read uploaded RFTA forms |
| PDFGenerator | SEMAP compliance report PDF |
| A2UI rich components | ObChart, ObTable, ObCallout, FormRenderer |
| AG-UI transport | SSE streaming + REST actions |
| ChatEngine render queue | ContextVar-isolated visualization |
| @openbench/chat-ui SDK | Drop-in React chat interface |

## Architecture

```
Frontend (React)          Backend (FastAPI)           OpenBench
┌─────────────┐          ┌──────────────┐          ┌──────────────┐
│ ChatProvider │──SSE────▶│ /awp         │─────────▶│ ChatEngine   │
│ ChatPanel    │          │ AGUIHandler  │          │ A2UIBuilder  │
│ A2UI Render  │◀─────────│              │◀─────────│              │
└─────────────┘          │ /chat/action │          │ BaseAgent    │
                         │ /chat/upload │          │ 17 Tools     │
                         └──────────────┘          │ GeminiLLM    │
                                                   └──────────────┘
```

## Setup

### Prerequisites

- Python 3.12+ with OpenBench installed (`pip install -e ".[chat]"`)
- Node.js 18+ with pnpm
- Google API key with Gemini access

### 1. Build the chat-ui package

```bash
cd packages/chat-ui
pnpm install && pnpm build
```

### 2. Start the backend

```bash
cd examples/lighthouser
export GOOGLE_API_KEY=your-key-here
uvicorn server:app --port 8001 --reload
```

### 3. Start the frontend

```bash
cd examples/lighthouser/frontend
pnpm install
pnpm dev
```

Open http://localhost:5173 in your browser.

## Sample Queries

Below are sample queries grouped by workflow scenario. Each query shows which tools are triggered and what A2UI components are rendered.

### 1. RFTA Interactive Form Review

The flagship workflow: agent understands context and generates an interactive form for user confirmation before running calculations.

**With file upload** -- upload `sample_files/sample_rfta.txt`, then:

```
Review this RFTA
```
> `analyze_document` -> `create_rfta_review_form` -> interactive form pre-filled with extracted data -> user edits -> "Run SEMAP Review" button -> Income/TTP/HAP tables + Rent Burden/Reasonableness callouts

```
I just received an RFTA from a new applicant. Can you pull the details so I can verify everything before we process it?
```
> Same flow. Agent reads the uploaded document, extracts all relevant fields, and presents a review form.

**Without file upload** -- agent generates form from data provided in text:

```
New voucher application: tenant Rosa Martinez, V-2024-010, 3BR unit at 450 West Oak Blvd in suburban_west. Proposed rent $1,650 with $150 utility allowance. Household of 5 (3 dependents), annual income $34,000, $5,400 in childcare. Set up the review form.
```
> `create_rfta_review_form` called directly with all values pre-filled -> user reviews -> submit -> SEMAP results

```
I need to process a new move-in. Here's what I have: V-2024-015, James Lee, 2BR downtown, $1,400 rent, $125 UA, household of 3, 1 dependent, $32,000 income. Let me review before calculating.
```
> Same flow without file. Agent maps the data to form fields.

**Minimal data** -- agent generates form with partial pre-fill:

```
Start a SEMAP review for a new 2-bedroom voucher downtown.
```
> `create_rfta_review_form` with only bedrooms=2 and area="downtown" pre-filled, other fields blank for user to complete.

### 2. Rent Reasonableness -- SEMAP 2 (24 CFR 982.507)

```
Validate rent for V-2024-001
```
> `validate_rent` -> bar chart (proposed $1,400 vs 3 comparables) + success callout

```
Is $1,850 reasonable for a 3-bedroom in suburban_west?
```
> `validate_rent` -> bar chart + warning callout (rent exceeds market average)

```
Show me market comparables for 2-bedroom units downtown
```
> `fetch_market_data` -> table (address, rent, sqft, condition) for 3 comparable units

```
What would the SEMAP 2 score be if 95 out of 100 units passed?
```
> `calculate_semap2_score` -> warning callout: 0/20 (95% below 98% threshold)

```
Calculate SEMAP 2 score for 200 total units, 198 passed
```
> `calculate_semap2_score` -> success callout: 20/20 (99% pass rate)

### 3. Income Determination -- SEMAP 3 (24 CFR 5.609, 5.611)

```
Verify income for V-2024-002
```
> `verify_income` -> table (Social Security $18,000 + Pension $4,000 = $22,000)

```
What are the HUD deductions for someone earning $36,000 with 2 dependents and $4,800 in childcare?
```
> `calculate_deductions` -> itemized deductions table with CFR references

```
Calculate deductions: $22,000 gross, elderly/disabled, $3,200 medical expenses
```
> `calculate_deductions` -> table with $400 elderly + medical excess over 3% threshold

```
Determine the adjusted income for V-2024-001
```
> `determine_adjusted_income` -> full pipeline: income verification + deductions + summary table

```
Run income determination for V-2024-003
```
> `determine_adjusted_income` -> Aisha Johnson: $28,000 gross - $7,440 deductions = $20,560 adjusted

### 4. Tenant Rent / TTP -- SEMAP 10 (24 CFR 5.628, 982.505, 982.508)

```
Calculate TTP for V-2024-002
```
> `determine_adjusted_income` + `calculate_ttp` -> table with all 4 HUD methods, selected TTP marked

```
What is the TTP for $20,560 adjusted income and $28,000 gross?
```
> `calculate_ttp` -> 30% adjusted=$514, 10% gross=$233, minimum=$50 -> TTP=$514

```
Calculate HAP: payment standard $1,550, TTP $514, rent $1,400, utility allowance $125
```
> `calculate_hap` -> breakdown table: HAP from standard, HAP from rent, tenant share

```
Check if V-2024-003 passes the rent burden test
```
> `determine_adjusted_income` + `calculate_ttp` + `calculate_hap` + `validate_rent_burden` -> warning callout: exceeds 40%

```
Validate rent burden: rent $1,850, UA $175, HAP $980, adjusted income $20,560
```
> `validate_rent_burden` -> family share and burden percentage against 40% cap

```
Does minimum rent apply if TTP is $35?
```
> `check_minimum_rent` -> warning callout: below $50, screens for hardship

```
Check minimum rent for TTP $35 with hardship exemption
```
> `check_minimum_rent` -> info callout: suspended 90 days pending determination

### 5. HUD Regulation Lookup

```
What does HUD say about rent reasonableness?
```
> `lookup_hud_regulation` -> info callout: 24 CFR 982.507 summary + 5 key points

```
Explain the TTP calculation rules
```
> `lookup_hud_regulation` -> info callout: 24 CFR 5.628

```
What are the allowable deductions under HUD rules?
```
> `lookup_hud_regulation` -> info callout: 24 CFR 5.611

```
Look up payment standards regulation
```
> `lookup_hud_regulation` -> info callout: 24 CFR 982.503

```
What is the rent burden rule?
```
> `lookup_hud_regulation` -> info callout: 24 CFR 982.508

### 6. Document Analysis (Paystub, Lease)

Upload `sample_files/sample_paystub.txt`, then:
```
Analyze this paystub and verify the annual income
```
> `analyze_document` -> extracts pay data, projects annual gross income

Upload `sample_files/sample_lease.txt`, then:
```
Review this lease for HCV compliance
```
> `analyze_document` -> analyzes lease terms, rent, utility responsibilities

```
What files have been uploaded?
```
> `analyze_document` (no filename) -> lists all uploaded files in the session

### 7. PDF Report Generation

```
Generate SEMAP report for V-2024-001
```
> `generate_semap_report` -> PDF with all 3 indicators (income, TTP/HAP, rent reasonableness)

```
Create a compliance report for V-2024-003 covering indicators 2 and 10
```
> `generate_semap_report` -> PDF focusing on rent reasonableness + tenant rent only

```
Generate SEMAP report for V-2024-002 for all indicators
```
> `generate_semap_report` -> PDF for elderly/disabled tenant with medical deduction details

### 8. Rich Visualization (create_chart, create_table, create_callout)

These tools are also available for ad-hoc data display:

```
Create a bar chart comparing rents: Proposed $1,400, Comp A $1,450, Comp B $1,480, Comp C $1,420
```
> `create_chart` -> bar chart with 4 data points

```
Show me a table of the 3 vouchers: V-2024-001 Maria Santos downtown 2BR, V-2024-002 James Washington suburban_east 1BR, V-2024-003 Aisha Johnson suburban_west 3BR
```
> `create_table` -> formatted table of voucher data

```
Flag this: rent burden at 45% exceeds the 40% limit per 24 CFR 982.508
```
> `create_callout` -> warning callout with the compliance issue

### 9. Full SEMAP Review (Task Planning + Parallel Tools)

```
Run a full SEMAP review for V-2024-001
```
> Agent plans steps -> runs SEMAP 2 + 3 + 10 in sequence -> tables + charts + callouts

```
Do a complete compliance check for V-2024-003
```
> Multi-step: income -> TTP -> HAP -> rent burden (FAILS) -> rent reasonableness

```
Review all three vouchers and compare results
```
> Parallel execution across V-2024-001, V-2024-002, V-2024-003 with comparison summary

### 10. Persistent Memory (Cross-Session)

```
What did we review earlier?
```
> Recalls previous voucher reviews from SQLite-backed memory

```
What was the TTP for the last voucher we checked?
```
> Memory retrieves previous calculation results

```
Compare V-2024-001 results with what we found for V-2024-003
```
> Cross-references current and previous review data from memory

### Tool Coverage

| # | Tool | Triggered by | A2UI Output |
|---|------|-------------|-------------|
| 1 | `validate_rent` | Rent check for a voucher | ObChart (bar) + ObCallout |
| 2 | `fetch_market_data` | Market comparables query | ObTable |
| 3 | `calculate_semap2_score` | SEMAP 2 scoring | ObCallout |
| 4 | `verify_income` | Income verification | ObTable |
| 5 | `calculate_deductions` | Deduction calculation | ObTable |
| 6 | `determine_adjusted_income` | Full income pipeline | ObTable |
| 7 | `calculate_ttp` | TTP calculation | ObTable |
| 8 | `calculate_hap` | HAP calculation | ObTable |
| 9 | `validate_rent_burden` | Rent burden check | ObCallout |
| 10 | `check_minimum_rent` | Minimum rent check | ObCallout |
| 11 | `lookup_hud_regulation` | HUD regulation lookup | ObCallout (info) |
| 12 | `analyze_document` | File upload/analysis | Text (streamed) |
| 13 | `create_rfta_review_form` | RFTA review / new voucher data | FormRenderer (14 fields) |
| 14 | `generate_semap_report` | PDF report request | ObFileCard |
| 15 | `create_chart` | Data visualization | ObChart |
| 16 | `create_table` | Tabular data display | ObTable |
| 17 | `create_callout` | Status/compliance alerts | ObCallout |

## Mock Data

Three voucher holders with different scenarios:

| Voucher | Tenant | Scenario |
|---------|--------|----------|
| V-2024-001 | Maria Santos | Standard family, 2BR downtown, passes all checks |
| V-2024-002 | James Washington | Elderly/disabled, 1BR suburban, medical deductions apply |
| V-2024-003 | Aisha Johnson | Large family, 3BR, high rent -- **intentionally fails rent burden** |

## File Structure

```
examples/lighthouser/
├── README.md              # This file
├── server.py              # FastAPI app (port 8001)
├── semap_agent.py         # Agent factory + 17 tool functions
├── schemas.py             # Tool schemas (OpenAI format, 17 tools)
├── prompt.py              # SEMAP-specific system prompt
├── mock_data.py           # Tenants, market comparables, HUD regulations
├── semap_engine.py        # Pure calculation functions (no AI deps)
├── frontend/              # React app (@openbench/chat-ui)
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       └── global.css
└── sample_files/          # Mock documents for upload testing
    ├── sample_rfta.txt
    ├── sample_paystub.txt
    └── sample_lease.txt
```

## Standalone Engine Test

Verify the pure calculation functions work independently:

```bash
cd examples/lighthouser
python semap_engine.py
```

This runs all 6 calculation functions with test data and prints results.
