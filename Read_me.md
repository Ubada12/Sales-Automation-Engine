# SAP Automation Engine

> Enterprise-grade SAP Purchase Order Automation System  
> Automated SAP Excel processing engine for generating operational, financial, and audit reporting sheets from raw SAP exports.

---

# Overview

SAP Automation Engine is a production-focused Excel automation platform designed to process SAP exported purchase order workbooks and automatically generate business reporting sheets with fully standardized processing pipelines.

The system transforms raw SAP export files into structured reporting outputs used by operations teams, sales teams, finance teams, and audit workflows.

The automation performs:

- SAP validation
- Data normalization
- Dynamic month detection
- Universal business amount extraction
- Vendor financial aggregation
- PO traceability generation
- Operational reporting generation
- Excel formatting
- Workbook generation
- Logging
- Recovery handling
- Performance optimization

---

# Business Problem

Manual SAP processing required:

- Manual filtering
- Manual PO aggregation
- Manual amount extraction
- Manual vendor grouping
- Manual operational reporting
- Multiple pivot creation workflows

Problems:

- Human errors
- Slow execution
- Repetitive work
- Difficult audit tracing
- High maintenance effort

SAP Automation Engine eliminates these manual workflows.

---

# Input Architecture

Input:

```text
Master SAP Export (.xlsx)
```

Single source of truth.

Outputs generated independently.

Architecture:

```text
Master SAP

├── Pivot1
│
├── Pivot2
│
└── Sheet1
```

No dependency chain exists between output sheets.

---

# Universal Money Rule

## Purpose

Determine final business amount from SAP row.

## Rule

System dynamically identifies:

```text
Latest Available Provision
```

Example:

```text
Dec Provision = 7,055,328

Jan Provision = 6,467,384

Feb Provision = 4,703,552

Mar Provision = 2,939,720
```

Final Business Amount:

```text
2,939,720
```

System automatically detects months dynamically.

No hardcoded:

- January
- February
- March
- April

Future SAP exports remain compatible.

---

# Output Sheet Logic

---

## Pivot1

### Purpose

Vendor Financial Summary Layer

Business Question:

```text
How much total business does vendor contribute?
```

Grouping Logic:

```text
GL
+
CC
+
Internal Order
+
Vendor
```

Ignored:

```text
Job
```

PO Handling:

Multiple PO values:

```text
661101903
661101904
661101907
```

Become:

```text
661101903,661101904,661101907
```

Amount Logic:

```text
SUM(BusinessAmount)
```

Output Example:

| Vendor | Total Amount | Purchase Orders |
|---------|--------------|-----------------|
| Vendor A | 1,709,703 | PO1,PO2,PO3 |

---

## Pivot2

### Purpose

Audit Layer / Traceability Layer

Business Question:

```text
Which PO contributed how much?
```

Grouping:

```text
GL
+
CC
+
Internal Order
+
Vendor
+
PO
```

Ignored:

```text
Job
```

Amount Logic:

```text
SUM(BusinessAmount)
```

Example:

| Vendor | PO | Contribution |
|---------|----|--------------|
| Vendor A | PO001 | 500000 |
| Vendor A | PO002 | 1200000 |

---

## Sheet1

### Purpose

Operational Working Layer

Business Question:

```text
Which exact activity/job exists?
```

Grouping:

```text
PO
+
Vendor
+
Job
+
GL
+
CC
+
Internal Order
```

Rule:

If ANY grouping field changes:

```text
Create New Row
```

Example:

Input:

```text
Vendor = Mediacom

Job = Fixed Retainership
```

Output:

```text
Separate Row
```

Input:

```text
Vendor = Mediacom

Job = Variable Retainership
```

Output:

```text
Separate Row
```

Purpose:

Operational visibility.

---

# Project Architecture

```text
sap_automation/

├── input/

├── output/

├── logs/
│   └── crash/

├── config/
│   ├── config.yaml
│   └── config.py

├── core/
│   ├── money_engine.py
│   ├── grouping_engine.py
│   ├── validator.py
│   ├── cleaner.py
│   ├── formatter.py
│   ├── month_mapper.py
│   └── logger.py

├── pivots/
│   ├── pivot1_engine.py
│   ├── pivot2_engine.py
│   └── sheet1_engine.py

├── ui/
│   ├── terminal.py
│   ├── progress.py
│   └── live_dashboard.py

├── tests/

├── temp/

└── main.py
```

---

# Core Components

## Validator Engine

Responsibilities:

- SAP structure validation
- Column validation
- Duplicate header validation
- Provision validation
- Dynamic month detection
- Input workbook validation

---

## Cleaner Engine

Responsibilities:

- Header normalization
- Numeric normalization
- Null standardization
- Exact duplicate removal
- Identifier cleanup

Examples:

```text
661101903.0

↓

661101903
```

```text
₹50,000

↓

50000
```

---

## Money Engine

Purpose:

```text
SAP Row

↓

Latest Provision Detection

↓

Business Amount
```

Single source of truth.

---

## Grouping Engine

Generic grouping engine used by:

- Pivot1
- Pivot2
- Sheet1

Purpose:

Reduce duplicate business logic.

---

# Logging System

Supported Levels:

```text
INFO
SUCCESS
WARNING
ERROR
DEBUG
CRITICAL
```

Features:

- File logging
- Terminal logging
- Crash logging
- Session tracking
- Timing metrics
- Performance metrics

Retention:

```text
90 Days
```

---

# Terminal UI

Features:

- Dynamic dashboard
- Progress bars
- Runtime panel
- Current stage visibility
- Warning panel
- Developer mode
- Interactive menus

Design Principle:

```text
LIVE TERMINAL UI

NO TERMINAL SPAM
```

---

# Workbook Features

Generated workbook:

```text
SAP_Automation_TIMESTAMP.xlsx
```

Sheets:

```text
Sheet1

Pivot1

Pivot2

Warnings

Run_Metadata
```

Formatting:

- Auto width
- Filters
- Freeze header row
- Number formatting
- Warning highlighting

Workbook remains:

```text
Fully Editable
```

---

# Performance Optimizations

Implemented planning:

- Read Excel once
- Compute money once
- Adaptive dashboard refresh
- Efficient grouping
- Controlled logging
- Memory cleanup
- Lazy loading

Target scalability:

```text
100000+ Rows
```

---

# Failure Recovery

Features:

- Retry handling
- Temporary workbook recovery
- Rollback protection
- Dashboard fallback
- Logger fallback
- Safe cleanup
- Crash reports

Retry policy:

```text
3 Attempts
```

---

# Configuration

System behavior configurable via:

```text
config/config.yaml
```

Configurable:

- Logging behavior
- UI behavior
- Performance tuning
- Retry handling
- Workbook generation settings

Business logic remains locked.

---

# Execution Flow

```text
User

↓

main.py

↓

Validator

↓

Cleaner

↓

Month Mapper

↓

Money Engine

↓

Grouping Engine

↓

Pivot Engines

↓

Formatter

↓

Workbook Export

↓

Output Workbook
```

---

# Engineering Philosophy

This system follows:

```text
Understand Business

↓

Reverse Engineer Logic

↓

Handle Edge Cases

↓

Design Architecture

↓

Optimize

↓

Implement
```

Business logic first.

Implementation second.

---

# Status

```text
Business Logic
LOCKED

Architecture
LOCKED

Engineering Design
LOCKED

Ready For Implementation
```

---

# Future Enhancements

Potential additions:

- Multi-user execution
- Cloud execution mode
- SAP direct connector
- Dashboard analytics
- Historical comparison engine
- Automated scheduling

---

# License

Internal Company Automation System

Proprietary Business Workflow Automation

---