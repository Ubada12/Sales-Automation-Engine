"""
sheet1_engine.py

Operational Working Layer — Sheet1 generation engine.

Business purpose:
    "Which exact activity / job still has an outstanding provision?"

Sheet1 is a ROW-LEVEL PASSTHROUGH of the filtered master rows.
Every qualifying master row becomes exactly one Sheet1 row.
There is NO grouping, NO aggregation, NO summing.

Why no grouping:
    Multiple master rows can share the same (PO, Job) text but have
    different ION values, different GL Accts, or different provision
    amounts.  Collapsing them destroys precision and produces wrong totals.
    The ground-truth output keeps each row individually.

Two public methods:
    filter_active(df)  →  returns filtered "active rows" shared with
                          Pivot1 and Pivot2 engines
    generate(active)   →  builds the final formatted Sheet1 dataframe

BUGS FIXED:
    1. Removed groupby/aggregation — Sheet1 is now a direct row passthrough.
    2. Removed NonPO filter — ground truth includes NonPO rows.
    3. Added Comment='Close' filter.
    4. Added has_zero_crossing filter.
    5. Added blank-PO filter.
"""

from __future__ import annotations

import pandas as pd

from core.logger import AppLogger


class Sheet1EngineError(Exception):
    """Raised when Sheet1 generation fails."""
    pass


class Sheet1Engine:
    """
    Sheet1 generation engine.

    Each output row corresponds to exactly one master SAP row.
    No aggregation is performed.
    """

    # Columns we carry through to the output
    OUTPUT_COLUMNS = [
        "Year",
        "PurchaseOrder",
        "Vendor Name",
        "Job",
        "Done",
        "GL Acct",
        "Cost Centre",
        "Internalordernumber",
        "Provision",
        "Comments",
    ]

    def __init__(
        self,
        grouping_engine,   # kept in signature for interface compatibility
        logger: AppLogger,
    ) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter_active(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Filter *dataframe* to only rows with an outstanding provision.

        Shared with Pivot1 and Pivot2 — they aggregate the same rows
        that Sheet1 displays.

        Exclusion rules:
            1. Purchase Order is blank / missing
               NOTE: NonPO rows are KEPT (ground truth includes them)
            2. Comment = 'Close'  (manually closed by team)
            3. business_amount <= 0  (no remaining balance)
            4. has_zero_crossing = True  (balance hit zero at some checkpoint)

        Args:
            dataframe: Enriched SAP dataframe (output of MoneyEngine).

        Returns:
            Filtered dataframe with only active / outstanding rows.
        """

        try:
            active = dataframe.copy()
            before = len(active)

            # ----------------------------------------------------------
            # Rule 1: Remove rows with truly blank Purchase Order
            #         NonPO strings are preserved — they represent
            #         non-PO-backed spend that still needs tracking.
            # ----------------------------------------------------------
            active = active[
                active["purchase order"]
                .fillna("")
                .str.strip()
                .str.len()
                .gt(0)
            ]
            blank_removed = before - len(active)
            if blank_removed:
                self.logger.warning(
                    f"{blank_removed} row(s) removed — blank Purchase Order."
                )

            # ----------------------------------------------------------
            # Rule 2: Remove 'Close' rows
            #
            # Two independent close signals exist in SAP exports:
            #
            #   a) Main Comment column (col T, header = "comment"):
            #      Overall row status — 'Close' means the entire PO
            #      line has been manually closed.
            #
            #   b) Monthly Comments columns (headers = "comments",
            #      "comments.1", "comments.2", "comments.3" …):
            #      Per-month closure signal — 'close' in any of these
            #      means the provision was settled for that month and
            #      the row must be excluded.
            #
            # We check BOTH.  The monthly columns are detected
            # dynamically by looking for any header that starts with
            # "comments" (plural) — pandas appends .1 .2 … for
            # duplicates so all month blocks are caught automatically.
            # ----------------------------------------------------------

            # a) Main comment column
            if "comment" in active.columns:
                before_close = len(active)
                active = active[
                    ~active["comment"]
                    .fillna("")
                    .str.strip()
                    .str.lower()
                    .eq("close")
                ]
                close_removed = before_close - len(active)
                if close_removed:
                    self.logger.warning(
                        f"{close_removed} row(s) removed — main Comment = 'Close'."
                    )

            # b) Monthly comments columns (comments, comments.1, comments.2 …)
            monthly_cmt_cols = [
                col for col in active.columns
                if str(col).lower().startswith("comments")
            ]
            if monthly_cmt_cols:
                before_mcmt = len(active)
                # Build a mask: True if ANY monthly comments cell == 'close'
                monthly_close_mask = active[monthly_cmt_cols].apply(
                    lambda col: col.fillna("").astype(str)
                                   .str.strip().str.lower().eq("close")
                ).any(axis=1)
                active = active[~monthly_close_mask]
                mcmt_removed = before_mcmt - len(active)
                if mcmt_removed:
                    self.logger.warning(
                        f"{mcmt_removed} row(s) removed — monthly Comments = 'close'."
                    )

            # ----------------------------------------------------------
            # Rule 3: Remove zero business_amount rows
            # ----------------------------------------------------------
            before_zero = len(active)
            active = active[active["business_amount"].fillna(0).gt(0)]
            zero_removed = before_zero - len(active)
            if zero_removed:
                self.logger.warning(
                    f"{zero_removed} row(s) removed — business_amount = 0."
                )

            # ----------------------------------------------------------
            # Rule 4: Remove zero-crossing rows
            # ----------------------------------------------------------
            if "has_zero_crossing" in active.columns:
                before_zc = len(active)
                active = active[~active["has_zero_crossing"]]
                zc_removed = before_zc - len(active)
                if zc_removed:
                    self.logger.warning(
                        f"{zc_removed} row(s) removed — "
                        "provision fully settled at a monthly checkpoint."
                    )

            active = active.reset_index(drop=True)

            self.logger.success(
                f"filter_active: {before} → {len(active)} rows "
                f"({before - len(active)} excluded)."
            )
            return active

        except Exception as exc:
            raise Sheet1EngineError(f"filter_active failed: {exc}") from exc

    def generate(self, active: pd.DataFrame) -> pd.DataFrame:
        """
        Build Sheet1 output from pre-filtered active rows.

        NO grouping or aggregation.  Each row in *active* produces
        exactly one row in the output.

        Args:
            active: Pre-filtered dataframe from filter_active().

        Returns:
            Formatted Sheet1 dataframe with OUTPUT_COLUMNS.
        """

        self.logger.info("Generating Sheet1 …")

        try:
            out = active.copy()

            # ----------------------------------------------------------
            # Build output columns
            # ----------------------------------------------------------
            out["Year"] = ""

            out["PurchaseOrder"] = out["purchase order"]

            out["Vendor Name"] = out["vendor name"]

            out["Job"] = out["job"]

            # Done = "<PO>-<VendorName>"
            out["Done"] = (
                out["purchase order"].astype(str)
                + "-"
                + out["vendor name"].fillna("")
            )

            out["GL Acct"] = out["gl acct"]

            out["Cost Centre"] = out["cost centre"]

            out["Internalordernumber"] = out["internalordernumber"]

            # Provision = the current outstanding balance (business_amount)
            out["Provision"] = out["business_amount"]

            # Comments: use SAP comment field if present, else "Provision"
            if "comment" in out.columns:
                out["Comments"] = out["comment"].fillna("Provision")
            else:
                out["Comments"] = "Provision"

            # ----------------------------------------------------------
            # Select and order final columns
            # ----------------------------------------------------------
            final = out[self.OUTPUT_COLUMNS].reset_index(drop=True)

            self.logger.success(
                f"Sheet1 generated — {len(final)} operational rows."
            )
            return final

        except Exception as exc:
            raise Sheet1EngineError(f"Sheet1 generate failed: {exc}") from exc
