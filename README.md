# Order-to-Audit System — Sri Lakshmi Snacks

A working prototype for the Winter 2026 internship problem statement (Centre for Digital Infrastructure, NIT Tiruchirappalli): one unified system carrying a small food manufacturer from a salesman's mobile order to the auditor's monthly statutory reports.

**Benchmark Status: 20 of 20 Section 5 figures match exactly.** Run `python manage.py run_benchmark` or open the browser-based **Interactive Benchmark Studio** (`/benchmark/`) to verify them live.

---

## Quick Start

### Windows (Single Command)
```bat
run.bat
```
Then open <http://127.0.0.1:8000/>.

### Any Platform (Virtualenv)
```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Linux/macOS: .venv/bin/pip
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_benchmark
.venv/Scripts/python manage.py runserver
```

### Docker
```bash
docker compose up --build
```

---

## Demo Roles & 1-Click Role Switcher

Every account uses the password **`benchmark123`**.  
The prototype includes a **1-Click Role Switcher Bar** on every page and on the login screen, allowing evaluators to jump between roles instantly without re-typing credentials.

| Role | Username | Can do | Device / Experience |
| --- | --- | --- | --- |
| **Factory admin** | `admin` | Verify/approve orders, raise GST invoices, record dispatch, record payments | Desktop billing desk |
| **Production supervisor** | `production` | Purchases, production runs, issues, scrap/output, overheads, BOM planning | Tablet / floor screen |
| **Salesman A** | `salesman_a` | Orders for Retailer A (Tamil Nadu); customer-wise tracking | Mobile-first (< 1 min order) |
| **Salesman B** | `salesman_b` | Orders for Distributor B (Karnataka); tests shortage & IGST | Mobile-first |
| **Accountant / auditor** | `accountant` | Read-only monthly reports (GSTR-1/3B, stock ledger, sales, ageing) | Desktop exports |
| **Owner** | `owner` | Executive dashboard, KPIs, variance alerts, stock valuation, dues | Any device |

---

## Interactive Prototype Features

1. **Interactive Benchmark Studio (`/benchmark/`)**:
   - Live browser runner executing the 9-step scenario and evaluating all 20 Section 5 checks live.
   - 20/20 PASS scorecard with expected vs actual values.
   - Complete Step 8 run cost sheet breakdown ($₹31.14$ cost per packet, $37.7\%$ margin).
   - "Reset to Clean Seed" button to restore initial benchmark master data anytime.
2. **Production Planning & BOM Simulator (`/production/plan/`)**:
   - Enter target packet count (e.g. 200, 500, 1000) or batches.
   - Computes standard ingredients required and compares against live on-hand warehouse stock.
   - Flags material shortages and allows 1-click creation of production run drafts.
3. **Mobile-First Salesman Order Flow**:
   - Quick quantity preset buttons (`+10`, `+50`, `+100`).
   - Live line amount and order total calculation in the browser.
   - Stock availability status indicators per product.
   - Offline order capture toggle with sync indicator.
4. **GST Tax Invoice & WhatsApp Sharing**:
   - Full GST tax invoice with financial year sequence (`TN/26-27/0001`), HSN codes, and place-of-supply tax split (CGST+SGST vs IGST).
   - 1-click **Share via WhatsApp** button and **Copy Summary** for customer communication.
   - ReportLab vector PDF invoice download.
5. **Auditor-Ready Reports & Tally XML Export**:
   - Stock summary & append-only transaction ledger.
   - Sales register with customer and product breakdowns.
   - GST outward supplies summary (GSTR-1 & GSTR-3B).
   - Purchase register.
   - Production consumption, yield, and variance report.
   - Receivables outstanding with 0–30, 31–60, 61–90, and 90+ day ageing buckets.
   - Exports to **Excel (.xlsx)**, **CSV**, **PDF**, and **Tally-compatible XML**.
6. **Bilingual Floor Staff Interface (Tamil / English)**:
   - Header toggle switches navigation, badges, and food item labels between English and தமிழ் (Tamil) for factory floor operators.
7. **Reorder Alerts & Stock Health Badges**:
   - Visual dashboard warning when raw materials fall below safety reorder points.

---

## Benchmark Results (Section 5)

| Check | Expected | Actual Result | Status |
| --- | --- | --- | --- |
| Flour weighted average rate | ₹43.125 | ₹43.1250 | **PASS** |
| Flour closing balance | 120 kg | 120.000 kg | **PASS** |
| Oil closing balance | 19.5 L | 19.500 L | **PASS** |
| Spice mix closing | 3.8 kg | 3.800 kg | **PASS** |
| Pouches closing | 306 pcs | 306.000 pcs | **PASS** |
| Cartons closing | 21 pcs | 21.000 pcs | **PASS** |
| Finished goods after run | 238 packets | 238.000 packets | **PASS** |
| Finished goods after dispatch | 88 packets | 88.000 packets | **PASS** |
| Yield variance | -6% (188 vs 200) | -6.00% (Flagged) | **PASS** |
| Oil consumption variance | +5% (10.5 vs 10 L) | +5.00% (Flagged Adverse) | **PASS** |
| Pouch variance | -3% (194 vs 200) | -3.00% (Within tolerance) | **PASS** |
| Carton variance | -10% (9 vs 10) | -10.00% (Flagged Favourable) | **PASS** |
| Retailer A invoice | ₹7,875.00 | ₹7,875.00 (₹7,500 + ₹187.50 + ₹187.50) | **PASS** |
| Retailer A outstanding | ₹3,875.00 | ₹3,875.00 (After ₹4,000 payment) | **PASS** |
| Distributor B shortage | 32 packets | 32.000 packets flagged | **PASS** |
| Interstate IGST on B | ₹300.00 | ₹300.00 (5% on ₹6,000) | **PASS** |
| Total run material cost | ₹4,055.00 | ₹4,055.00 | **PASS** |
| Total run cost (w/ overheads) | ₹5,855.00 | ₹5,855.00 | **PASS** |
| Cost per good packet | ₹31.14 | ₹31.14 (₹5,855 ÷ 188 pkts) | **PASS** |
| Wholesale margin per packet | ₹18.86 | ₹18.86 (37.7% margin) | **PASS** |

---

## Architectural Decisions & Edge Cases

1. **Valuation Method: Moving Weighted Average (AS 2 / Ind AS 2)**:
   Simple to audit, permitted under Indian Accounting Standards. Handles part-batches naturally without cost layers. (For comparison: FIFO gives ₹30.90, Last Price gives ₹31.54).
2. **Cost per Packet Divides by Good Packets**:
   $$\text{Cost per packet} = \frac{₹5,855.00}{188} = ₹31.14$$
   Yield loss is loaded directly onto sellable stock rather than hidden in a separate write-off.
3. **Overheads Added via Revaluation Ledger Movement**:
   Overheads (Labour ₹1,200 + Power ₹600) arrive after production completion. They post as a zero-quantity `REVALUATION` movement on `StockMovement`, increasing finished goods valuation without altering physical counts.
4. **Tolerance Rule is Strict Greater-Than**:
   - Pouches (194 used vs 200 plan) is exactly $-3.00\%$ $\rightarrow$ **not flagged**.
   - Cartons (9 used vs 10 plan) is $-10.00\%$ $\rightarrow$ **flagged as favourable** (188 packets need only 9.4 cartons).
5. **Single Stock Writer & Reversals**:
   No model field stores an editable stock balance. Balances are derived from `StockMovement`. Corrections are recorded as reversal rows; invoices are cancelled via formal credit notes.

---

## Automated Test Suite

Run the full automated test suite (24 tests covering stock maths, tax splits, unit conversions, permissions, and benchmark assertions):

```bash
python manage.py test ota
```
