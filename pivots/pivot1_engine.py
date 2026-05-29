"""
pivot1_engine.py

Vendor Financial Summary Layer — Pivot1 generation engine.

Business purpose:
    "How much total outstanding provision does each vendor contribute?"

Pivot1 aggregates Sheet1's active rows up to vendor level:
    Group key: GL Acct + Cost Centre + ION + Vendor Name
    Total     = SUM of all Provision values in the group
    PO list   = all unique PO numbers in the group, comma-separated

One row per (GL, CC, ION, Vendor) combination.

BUGS FIXED vs. original pivot1_engine.py:
    1. Output column names were lowercase SAP internal names
       (gl acct, cost centre, business_amount …).
       Fixed to match the expected Excel column headers:
       GL Acct | Cost Centre | Internalordernumber | Vendor Name |
       Total   | Purchase order | Done
    2. No explicit sort — output is now sorted by GL Acct for readability.
    3. No NonPO / zero-amount guard — engine now receives pre-filtered
       active rows from runner.py (via sheet1.filter_active), so these
       rows are already excluded upstream.
"""

from __future__ import annotations

import pandas as pd

from core.grouping_engine import GroupingEngine
from core.logger import AppLogger


class Pivot1EngineError(Exception):
    """Raised when Pivot1 generation fails."""
    pass


class Pivot1Engine:
    """
    Pivot1 generation engine.

    Aggregates active rows to the (GL + CC + ION + Vendor) level.
    Receives pre-filtered rows; no row-level filtering is performed here.
    """

    # Grouping key — same four fields used in the expected output
    GROUP_COLUMNS = [
        "gl acct",
        "cost centre",
        "internalordernumber",
        "vendor name",
    ]

    # Final output column order (must match expected Excel structure)
    OUTPUT_COLUMNS = [
        "GL Acct",
        "Cost Centre",
        "Internalordernumber",
        "Vendor Name",
        "Total",
        "Purchase order",
        "Done",
    ]

    def __init__(
        self,
        grouping_engine: GroupingEngine,
        logger: AppLogger,
    ) -> None:

        self.grouping = grouping_engine
        self.logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, active: pd.DataFrame) -> pd.DataFrame:
        """
        Build Pivot1 from pre-filtered active rows.

        Args:
            active: Filtered active rows (output of Sheet1Engine.filter_active).

        Returns:
            Pivot1 dataframe sorted by GL Acct with correct column names.
        """

        self.logger.info("Generating Pivot1 …")

        try:
            # ----------------------------------------------------------
            # Aggregate: sum provision, join PO numbers
            # ----------------------------------------------------------
            aggregation = {
                "purchase order":  self.grouping.unique_join,
                "business_amount": self.grouping.sum_money,
            }

            grouped = self.grouping.group(
                active,
                self.GROUP_COLUMNS,
                aggregation,
            )

            # ----------------------------------------------------------
            # Safety guard: remove any zero-total rows that might
            # survive if filter_active was bypassed in unit tests
            # ----------------------------------------------------------
            before = len(grouped)
            grouped = grouped[
                grouped["business_amount"].fillna(0).gt(0)
            ].reset_index(drop=True)
            if len(grouped) < before:
                self.logger.warning(
                    f"Pivot1: {before - len(grouped)} zero-total row(s) dropped."
                )

            # ----------------------------------------------------------
            # Sort by GL Acct for a consistent, readable output
            # ----------------------------------------------------------
            grouped = grouped.sort_values(
                ["gl acct", "cost centre", "internalordernumber", "vendor name"],
                na_position="first",
            ).reset_index(drop=True)

            # ----------------------------------------------------------
            # Build output columns with correct names
            # ----------------------------------------------------------

            # Total = sum of all provision amounts in the group
            grouped["Total"] = grouped["business_amount"]

            # Done = "<VendorName>-<Total>"  (matches original Excel format)
            grouped["Done"] = (
                grouped["vendor name"].fillna("")
                + "-"
                + grouped["business_amount"].apply(
                    lambda x: str(round(x, 2)) if pd.notna(x) else "0"
                )
            )

            # Rename Purchase order (already joined by unique_join)
            grouped["Purchase order"] = grouped["purchase order"]

            # Rename structural columns
            grouped.rename(
                columns={
                    "gl acct":             "GL Acct",
                    "cost centre":         "Cost Centre",
                    "internalordernumber": "Internalordernumber",
                    "vendor name":         "Vendor Name",
                },
                inplace=True,
            )

            # ----------------------------------------------------------
            # Select final output columns in correct order
            # ----------------------------------------------------------
            final = grouped[self.OUTPUT_COLUMNS].copy()

            self.logger.success(
                f"Pivot1 generated — {len(final)} vendor-bucket rows."
            )

            return final

        except Exception as exc:
            raise Pivot1EngineError(
                f"Pivot1 generate failed: {exc}"
            ) from exc
