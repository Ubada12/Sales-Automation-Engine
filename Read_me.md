# SAP Automation Engine

> Enterprise-grade SAP Purchase Order Automation System
> Automated SAP Excel processing engine for generating operational, financial, and audit reporting sheets from raw SAP exports.

---

## Overview

SAP Automation Engine is a production-focused Excel automation platform that processes SAP-exported purchase order workbooks and automatically generates three business reporting sheets with fully standardised pipelines.

The system transforms a raw SAP master export file into structured outputs used by operations teams, finance teams, and audit workflows — eliminating manual filtering, manual provision tracking, and manual pivot creation.

---

## Business Problem

The SAP master export is a single large Excel file containing every purchase order line with monthly provision balances. Manually extracting business insights from it required:

| Manual task | Problem |
|---|---|
| Filter active vs settled POs | Human error, missed rows |
| Track which month's balance is current | Wrong amounts |
| Group by vendor for financial summaries | Slow, inconsistent |
| Drill down PO contributions per GL bucket | Difficult audit trail |
| Identify every individual job activity | No operational visibility |

SAP Automation Engine automates all of the above in a single run.

---

## Input

```
input/
└── input_master.xlsx     ← Raw SAP export, single source of truth
```

The master file has a fixed structure:

- **Rows 1–3**: SAP summary/subtotal rows (skipped automatically)
- **Row 4**: Column headers
- **Row 5 onwards**: Data rows, one per PO-Job-GL combination

### Master Column Structure

| Column | Header | Purpose |
|--------|--------|---------|
| A | Year | Row category: `Y` = current year, `new`/`New` = open POs, `2026` = next year |
| D | Purchase Order | SAP PO number (e.g. 661101903) or "NonPO" |
| E | Vendor Name | SAP vendor |
| F | Job | Activity/job description |
| H | Done | Computed: `=Vendor & "-" & Job` |
| L | GL Acct | General Ledger account |
| M | Cost Centre | Cost centre code |
| N | Internalordernumber | Internal order / ION |
| R | Dec Provision | Starting provision amount (budget set aside) |
| T | Comment | Overall row status: `Provision`, `Close`, `From Open PO`, etc. |
| U | Jan Inv | January invoice reference |
| V | Jan Amt | Amount invoiced in January |
| W | Jan Balance | Remaining after January: `= Dec Provision − Jan Amt` |
| X | Provision | Jan remaining provision (same as Jan Balance) |
| Y | Comments | January per-month status note |
| Z–AD | Feb block | Same 5-column pattern for February |
| AE–AI | Mar block | Same 5-column pattern for March |
| AJ–AN | April block | Same 5-column pattern for April |

> Each month block follows the exact pattern:
> `<Month> Inv → <Month> Amt → <Month> Balance → Provision → Comments`

---

## The Provision Chain (Universal Money Rule)

The core financial concept in this system is the **rolling provision balance**:

```
Dec Provision  ← starting budget
       ↓ minus Jan Amt (invoice paid)
Jan Balance    ← remaining after January
       ↓ minus Feb Amt
Feb Balance    ← remaining after February
       ↓ minus Mar Amt
Mar Balance    ← remaining after March
       ↓ minus Apr Amt
Apr Balance    ← remaining after April  ← FINAL OUTSTANDING AMOUNT
```

**Business Amount = the latest available non-null provision value, scanning from April backwards to January.**

If no invoice was received in a month, that month's balance equals the previous month's balance. So a row with no invoices at all will show the same amount across all months — equal to the original Dec Provision.

### Example

```
Dec Provision = 7,055,328
Jan Provision = 7,055,328   (no January invoice)
Feb Provision = 4,703,552   (February invoice paid = 2,351,776)
Mar Provision = 2,939,720   (March invoice paid = 1,763,832)
Apr Provision = (none yet)

Final Business Amount = 2,939,720   ← latest available
```

### Month Detection

Month blocks are detected **dynamically** from column headers using a pattern match for `<MonthName> Inv`. Both abbreviated and full names are supported:

- `Jan Inv`, `January Inv`
- `Feb Inv`, `February Inv`
- `Mar Inv`, `March Inv`
- `Apr Inv`, `April Inv`  ← SAP uses "April" not "Apr"
- and so on for all 12 months

No months are hardcoded. Future SAP exports with different month ranges work automatically.

---

## Active Row Filtering (The Core Business Rule)

Not every master row appears in the output. A row is **active** (included in all three output sheets) only when ALL of the following are true:

### Rule 1 — Has a Purchase Order

The Purchase Order column must be non-blank. NonPO rows (non-SAP-backed spend) are kept — they represent real budget commitments even without a formal PO.

### Rule 2 — Not manually closed (main Comment)

If the main Comment column (col T) = `"Close"`, the row has been manually marked as closed by the team. Excluded.

### Rule 3 — Not closed at monthly level (monthly Comments)

Each month block has its own Comments column. If **any** monthly Comments column says `"close"`, the provision was settled for that month and the row must be excluded.

This catches rows like:
```
Main Comment   = "From Open PO"   ← looks active
Feb Comments   = "close"          ← settled at Feb level → EXCLUDED
```

### Rule 4 — Has remaining provision (business_amount > 0)

The latest available provision value must be greater than zero.

Values below ₹1.00 are treated as effectively zero — these are floating-point rounding artefacts from Excel formula chains (e.g. `0.33`, `0.20`) and do not represent real outstanding amounts.

### Rule 5 — Balance never hit zero (zero-crossing check)

Even if the final balance is positive, a row is excluded if **any intermediate monthly balance reached ≤ 0 at any checkpoint**.

Why: if a provision was fully invoiced in January (Jan Balance = 0), the PO line was settled. Even if a new provision was added in February, the row represents a re-opened entry that should not appear in the current outstanding list.

```
Example (EXCLUDED):
  Dec Provision = 50,000
  Jan Balance   = 50,000
  Feb Balance   = 50,000
  Mar Balance   = 50,000
  Apr Balance   = 0        ← hit zero → EXCLUDED

Example (EXCLUDED):
  Dec Provision = 249,414
  Jan Balance   = 0        ← hit zero in Jan → EXCLUDED
  Feb Balance   = 1,158,125  (new provision added, but row is still excluded)

Example (INCLUDED):
  Dec Provision = 366,802
  Jan Balance   = 209,919  (Jan invoice paid = 156,883)
  Feb Balance   = 209,919
  Mar Balance   = 53,036   (Mar invoice paid = 156,883)
  Apr Balance   = 53,036   ← still positive, never hit zero → INCLUDED
  Business Amount = 53,036
```

---

## Output Sheet Logic

All three output sheets are derived from the **same set of active rows**. Pivot1 and Pivot2 aggregate what Sheet1 shows — they are always consistent with each other.

---

### Sheet1 — Operational Working Layer

**Business question**: *Which exact activity/job still has an outstanding provision?*

Sheet1 is a **direct row-level passthrough** of filtered active rows. No aggregation. No grouping. Each active master row becomes exactly one Sheet1 row.

**Why no grouping**: Multiple master rows can share the same PO and Job description but have different ION values or different provision amounts. Collapsing them would destroy precision and produce wrong totals.

**Output columns**:

| Column | Source |
|--------|--------|
| Year | Blank (intentional) |
| PurchaseOrder | Master col D |
| Vendor Name | Master col E |
| Job | Master col F |
| Done | `= PurchaseOrder & "-" & Vendor Name` |
| GL Acct | Master col L |
| Cost Centre | Master col M |
| Internalordernumber | Master col N |
| Provision | Latest active balance (business_amount) |
| Comments | Master col T (main Comment field) |

---

### Pivot1 — Vendor Financial Summary Layer

**Business question**: *How much total outstanding provision does each vendor contribute?*

Pivot1 aggregates active rows up to the **vendor level**. The Job column is ignored — this view is purely financial.

**Group key**: `GL Acct + Cost Centre + Internalordernumber + Vendor Name`

One row per unique combination of those four fields.

**Aggregation**:
- `Total` = SUM of all Provision values in the group
- `Purchase order` = all unique PO numbers in the group, joined as `"PO1, PO2, PO3"`
- `Done` = `Vendor Name + "-" + Total`

**Output columns**:

| Column | Content |
|--------|---------|
| GL Acct | GL Account |
| Cost Centre | Cost Centre |
| Internalordernumber | Internal Order |
| Vendor Name | Vendor |
| Total | Sum of all outstanding provisions |
| Purchase order | Comma-separated PO list |
| Done | `VendorName-Total` |

**Sorted by**: GL Acct ascending.

**Example**:

| GL Acct | Vendor | Total | Purchase order |
|---------|--------|-------|----------------|
| 6761630 | Mediacom Comm | 21,29,379 | 660912054, 660994812, 661052068 |

---

### Pivot2 — Audit / Traceability Layer

**Business question**: *Which PO contributed how much — with full drill-down hierarchy?*

Pivot2 is the **drill-down version of Pivot1**. Where Pivot1 shows one row per vendor, Pivot2 shows one row per PO within each vendor. It answers: for a given GL + vendor combination, exactly which POs make up the total?

**Group key**: `GL Acct + Cost Centre + Internalordernumber + Vendor Name + Purchase Order`

One row per PO within each vendor bucket.

**Aggregation**:
- `Total` = SUM of all Provision values for that PO
- `Done` = `PO + "-" + Vendor Name`

**Hierarchy display**: Pivot2 uses visual blanking to show the parent-child relationship. A field is shown only when it changes from the previous row. When a higher-level field changes, all lower-level fields are also shown (reset).

```
Rule:
  show GL     = GL changed
  show CC     = CC changed  OR  GL changed
  show ION    = ION changed  OR  CC changed  OR  GL changed
  show Vendor = Vendor changed  OR  any parent changed
```

**Example output**:

```
GL Acct   | CC         | ION          | Vendor         | PO        | Total
----------|------------|--------------|----------------|-----------|--------
6761600   | IN00068207 | SGPI99999999 | Quess Corp     | 660966053 | 209,458
(blank)   | (blank)    | (blank)      | (blank)        | 660976621 | 729,906
(blank)   | (blank)    | (blank)      | (blank)        | 661003740 | 732,000
(blank)   | (blank)    | (blank)      | ADECCO         | 661007059 | 129,595
(blank)   | (blank)    | (blank)      | (blank)        | 661007071 |   9,548
6761610   | IN00068207 | 520150000805 | RAN IDEAS      | 660916787 | 250,000
```

**Sheet structure**:

```
Row 1: (blank)
Row 2: (blank)
Row 3: "Sum of Provision"
Row 4: Column headers
Row 5+: Data rows
Last row: "Grand Total" + sum of all provisions
```

**Output columns**:

| Column | Content |
|--------|---------|
| GL Acct | Shown on first PO of each GL group, blank otherwise |
| Cost Centre | Shown when it or a parent changes |
| Internalordernumber | Shown when it or a parent changes |
| Vendor Name | Shown when it or a parent changes |
| PurchaseOrder | Always shown |
| Done | `PO-VendorName` |
| Total | Sum of provisions for this PO |

---

## Project Architecture

```
SAP Automation Engine/
│
├── config/
│   ├── config.yaml          ← All runtime settings
│   └── config.py            ← YAML loader / config accessor
│
├── core/
│   ├── validator.py         ← SAP file validation, header detection
│   ├── cleaner.py           ← Data normalisation pipeline
│   ├── month_mapper.py      ← Dynamic month block detection
│   ├── money_engine.py      ← Provision calculation + zero-crossing
│   ├── grouping_engine.py   ← Generic groupby aggregation helpers
│   ├── formatter.py         ← Excel workbook export + formatting
│   └── logger.py            ← Structured logging + crash reporting
│
├── pivots/
│   ├── sheet1_engine.py     ← Operational layer (row passthrough)
│   ├── pivot1_engine.py     ← Vendor financial summary
│   └── pivot2_engine.py     ← PO-level audit drill-down
│
├── pipeline/
│   └── runner.py            ← Pipeline orchestration + retry
│
├── ui/
│   ├── terminal.py          ← Interactive menu + file picker
│   ├── progress.py          ← Adaptive progress bar renderer
│   └── live_dashboard.py    ← Live terminal dashboard
│
├── input/                   ← Place SAP export here
├── output/                  ← Generated workbooks written here
├── logs/                    ← Run logs (retained 90 days)
│   └── crash/               ← Crash reports
├── temp/                    ← Temporary working files
│
└── main.py                  ← Application entry point
```

---

## Execution Flow

```
main.py
  │
  ├── Config loaded from config/config.yaml
  ├── Logger initialised (file + terminal)
  ├── All engines instantiated and wired
  │
  └── PipelineRunner.run()
        │
        ├── Terminal menu (user selects Sheet1 / Pivot1 / Pivot2 / All)
        ├── File picker (lists .xlsx files in input/)
        │
        └── PipelineRunner.execute()
              │
              ├── 1. Validator.validate_excel()
              │       Detects header row, validates required columns,
              │       validates month blocks are present
              │
              ├── 2. MonthMapper.detect()
              │       Scans column headers for month blocks
              │       (Jan Inv / Jan Amt / Jan Balance / Provision / Comments)
              │       Supports full and abbreviated month names
              │
              ├── 3. Cleaner.clean()
              │       Headers → lowercase
              │       Nulls → None
              │       Numeric strings → float
              │       PO identifiers → clean integer strings
              │       Grouping fields → non-null strings
              │       Exact duplicates → removed
              │       Blank-critical-field rows → removed
              │
              ├── 4. MoneyEngine.add_business_amount()
              │       For each row, scans provision columns
              │       from latest month backwards to find
              │       first non-null value → business_amount
              │       Also computes has_zero_crossing flag
              │
              ├── 5. Sheet1Engine.filter_active()
              │       Applies all 5 exclusion rules:
              │       - Blank PO removed
              │       - Main Comment = 'Close' removed
              │       - Any monthly Comments = 'close' removed
              │       - business_amount ≤ 0 removed
              │       - has_zero_crossing = True removed
              │       → Returns shared active rows dataset
              │
              ├── 6. Generate sheets (all from same active rows)
              │       Pivot1Engine.generate()   → vendor summary
              │       Pivot2Engine.generate()   → PO drill-down
              │       Sheet1Engine.generate()   → row passthrough
              │
              └── 7. Formatter.export()
                      Writes all sheets to timestamped workbook
                      Applies styling, freeze panes, filters,
                      auto-width, number formatting
                      Adds Warnings sheet + Run_Metadata sheet
```

---

## Core Components

### Validator

Dynamically detects the SAP header row by scanning the first 10 rows for a cluster of required column names (`Purchase Order`, `Vendor Name`, `GL Acct`, etc.). Handles SAP exports that contain summary rows, banner rows, or metadata rows above the actual headers.

### Cleaner

Eight-stage normalisation pipeline run in order:

1. Header normalisation (lowercase, collapse whitespace)
2. Null standardisation (`""`, `"-"`, `"na"`, `"n/a"`, `"null"`, `"none"` → `None`)
3. Text normalisation (strip whitespace, preserve original casing)
4. Numeric normalisation (convert numeric strings to `float`, strip `₹` and `,`)
5. Identifier cleanup (remove Excel float artefacts: `660702210.0` → `"660702210"`)
6. Grouping-field normalisation (`None` → `""` for consistent groupby)
7. Exact duplicate removal (configurable)
8. Bad-row removal (rows where all critical fields are blank, configurable)

### Month Mapper

Scans the column list for patterns matching `<MonthName> Inv` using a regex that supports both abbreviated (`Apr`) and full (`April`) month names. For each match, validates the next four columns follow the expected SAP block structure (`Amt → Balance → Provision → Comments`). Stores ordered `MonthBlock` objects and exposes:

- `provision_columns()` — the Provision columns for each month in order
- `balance_columns()` — the Balance columns for each month in order
- `all_checkpoint_columns()` — both Balance and Provision columns interleaved, for zero-crossing detection

### Money Engine

Fully vectorised (no row-by-row loops). Operates on entire columns at once:

- **business_amount**: scans provision columns from latest month to earliest, picks the first non-null value
- **has_zero_crossing**: True if any checkpoint column (balance or provision) has a value ≤ `1.0` — the threshold is ₹1 to catch floating-point near-zero artefacts from Excel formula chains
- **money_source**: name of the column that supplied the business amount
- **money_warning**: True if no valid provision was found (amount = 0)

### Grouping Engine

Shared by Pivot1 and Pivot2. Provides:

- `group()` — validated `groupby().agg()` wrapper
- `unique_join()` — join unique values as `"val1, val2, val3"` (comma + space)
- `sum_money()` — provision sum with numeric coercion
- `first_non_null()` — carry forward first non-null value

### Sheet1 Engine

Two public methods:

- `filter_active(df)` — applies all 5 exclusion rules, returns the shared active rows dataset used by all three output sheets
- `generate(active)` — direct row passthrough, no aggregation, builds output columns

### Pivot1 Engine

Groups active rows by `(GL Acct, Cost Centre, ION, Vendor Name)`, sums provisions, joins PO numbers. Sorts by GL Acct ascending.

### Pivot2 Engine

Groups active rows by `(GL Acct, Cost Centre, ION, Vendor Name, PO)`, sums provisions. Sorts by the full group key. Applies hierarchical blanking: each field is shown only when it or a higher-level field changes from the previous row. Appends Grand Total row.

### Formatter

Post-write styling pass using openpyxl:

- Bold + green fill on header rows
- Freeze panes below header
- Auto-filter dropdowns
- Auto-fit column widths (capped at 60 characters)
- `#,##0` number formatting on `Provision` and `Total` columns
- Red fill on critical rows in the Warnings sheet
- Pivot2 written with title row structure (blank, blank, "Sum of Provision", headers, data)

---

## Configuration Reference

All settings are in `config/config.yaml`. Business logic is not configurable — only infrastructure behaviour.

```yaml
logging:
  retention_days: 90            # Log file retention
  enable_file_logging: true     # Write to /logs/
  enable_terminal_logging: true # Echo to stdout
  developer_mode_default: false # Show DEBUG messages

performance:
  small_file_threshold: 1000    # Rows → "small" dashboard refresh rate
  medium_file_threshold: 10000  # Rows → "medium" dashboard refresh rate
  small_file_refresh_rows: 10   # Redraw every N rows (small file)
  medium_file_refresh_rows: 50  # Redraw every N rows (medium file)
  large_file_refresh_rows: 500  # Redraw every N rows (large file)

recovery:
  retry_attempts: 3             # Pipeline retry count on failure
  keep_temp_files: false        # Preserve /temp/ after run

ui:
  enable_live_dashboard: true   # Show live progress dashboard
  enable_terminal_colors: true  # ANSI colour codes
  dashboard_refresh_seconds: 0.5

workbook:
  generate_warning_sheet: true  # Include Warnings sheet
  generate_metadata_sheet: true # Include Run_Metadata sheet
  freeze_header_row: true
  enable_auto_filter: true
  auto_column_width: true
  conditional_warning_colors: true

output:
  output_prefix: "SAP_Automation"
  timestamp_format: "%Y%m%d_%H%M%S"

validation:
  normalize_invalid_provision_to_zero: true
  skip_bad_rows: true
  remove_exact_duplicates: true

debug:
  save_crash_logs: true
  enable_performance_metrics: true
```

---

## Output Workbook

Generated as `SAP_Automation_<YYYYMMDD_HHMMSS>.xlsx` in the `output/` folder.

| Sheet | Contents |
|-------|----------|
| Sheet1 | Operational layer — one row per active PO-Job line |
| Pivot1 | Vendor financial summary — one row per GL+CC+ION+Vendor bucket |
| Pivot 2 | PO audit drill-down — one row per PO with hierarchy blanking |
| Warnings | Rows where no valid provision was found (for manual review) |
| Run_Metadata | Run ID, input filename, row counts, excluded row count |

All sheets are fully editable with filters and freeze panes applied.

---

## Failure Recovery

On any pipeline failure:

1. Exception is caught by `PipelineRunner`
2. Retry up to `retry_attempts` times (1-second back-off between attempts)
3. On final failure: crash report written to `logs/crash/crash_<run_id>.log`
4. Temporary files cleaned up (unless `keep_temp_files: true`)
5. Logger shut down cleanly

Dashboard failures are silently swallowed — they never abort the pipeline.

---

## Running the System

```bash
# Place your SAP export in the input/ folder, then:
python main.py
```

The terminal menu appears:

```
========================================
SAP AUTOMATION
========================================

1 Generate Pivot1
2 Generate Pivot2
3 Generate Sheet1
4 Generate All
5 Exit

Select: 4
```

Select a file from the list, watch the live dashboard, collect your workbook from `output/`.

---

## Engineering Notes

- **Single data read**: the master file is read exactly once. All three output sheets derive from that single load.
- **Shared active filter**: `Sheet1Engine.filter_active()` is called once by the runner. Pivot1 and Pivot2 receive the same filtered dataset — they are guaranteed to be consistent with Sheet1.
- **Dynamic month detection**: adding a new month to the SAP export requires no code changes. The month mapper detects it automatically.
- **Provision tolerance**: the zero-crossing threshold is ₹1.00. Values below this are floating-point noise from Excel's balance formula chain and are treated as settled.

---

## License

Internal Company Automation System — Proprietary Business Workflow Automation
