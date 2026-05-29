"""
pivot2_engine.py

Audit / Traceability Layer — Pivot2 generation engine.

Business purpose:
    "Which PO contributed how much — drill-down hierarchy with full traceability."

Pivot2 is the drill-down version of Pivot1.  Where Pivot1 collapses all POs
into one row per vendor, Pivot2 keeps EACH PO as its own row but displays
them visually grouped under their parent (GL / CC / ION / Vendor).

Hierarchy:
    GL Acct
      └── Cost Centre
            └── ION
                  └── Vendor Name
                        └── PO 1  →  Total for this PO
                        └── PO 2  →  Total for this PO

Visual blanking rule (implemented in _apply_hierarchy):
    A field is shown (non-None) only when IT or a HIGHER-LEVEL field
    changes from the previous row.  When a field's parent changes, all
    child fields are also shown (full reset).  This creates the
    indented, readable audit display seen in the expected output.

    Formally:
        show GL     = GL changed
        show CC     = CC changed  OR  GL changed
        show ION    = ION changed  OR  CC changed  OR  GL changed
        show Vendor = Vendor changed OR ION changed OR CC changed OR GL changed

BUGS FIXED vs. original pivot2_engine.py:
    1. No hierarchy blanking — every row had all four fields populated.
    2. No sort — hierarchy blanking only works correctly on sorted data.
    3. Wrong output column names (lowercase internal names).
    4. No zero-amount / NonPO guard (now handled upstream by filter_active).
    5. Header rows ("Sum of Provision" title, column headers at row 4)
       are written by the Formatter layer, not this engine.
"""

from __future__ import annotations

import pandas as pd

from core.grouping_engine import GroupingEngine
from core.logger import AppLogger


class Pivot2EngineError(Exception):
    """Raised when Pivot2 generation fails."""
    pass


class Pivot2Engine:
    """
    Pivot2 audit drill-down engine.

    Aggregates active rows to the (GL + CC + ION + Vendor + PO) level,
    then applies hierarchical blanking for the final display.
    """

    # Grouping key — one row per PO within each vendor bucket
    GROUP_COLUMNS = [
        "gl acct",
        "cost centre",
        "internalordernumber",
        "vendor name",
        "purchase order",
    ]

    # Sort order for hierarchy building (must match GROUP_COLUMNS hierarchy)
    SORT_COLUMNS = [
        "gl acct",
        "cost centre",
        "internalordernumber",
        "vendor name",
        "purchase order",
    ]

    # Final output column order
    OUTPUT_COLUMNS = [
        "GL Acct",
        "Cost Centre",
        "Internalordernumber",
        "Vendor Name",
        "PurchaseOrder",
        "Done",
        "Total",
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
        Build Pivot2 from pre-filtered active rows.

        Args:
            active: Filtered active rows (output of Sheet1Engine.filter_active).

        Returns:
            Pivot2 dataframe with hierarchical blanking applied.
        """

        self.logger.info("Generating Pivot2 …")

        try:
            # ----------------------------------------------------------
            # 1. Aggregate: sum provision per (GL, CC, ION, Vendor, PO)
            # ----------------------------------------------------------
            aggregation = {
                "business_amount": self.grouping.sum_money,
            }

            grouped = self.grouping.group(
                active,
                self.GROUP_COLUMNS,
                aggregation,
            )

            # ----------------------------------------------------------
            # 2. Safety guard against zero-total rows
            # ----------------------------------------------------------
            before = len(grouped)
            grouped = grouped[
                grouped["business_amount"].fillna(0).gt(0)
            ].reset_index(drop=True)
            if len(grouped) < before:
                self.logger.warning(
                    f"Pivot2: {before - len(grouped)} zero-total row(s) dropped."
                )

            # ----------------------------------------------------------
            # 3. Sort — MUST happen before hierarchy blanking
            # ----------------------------------------------------------
            grouped = grouped.sort_values(
                self.SORT_COLUMNS,
                na_position="first",
            ).reset_index(drop=True)

            # ----------------------------------------------------------
            # 4. Apply hierarchical blanking
            # ----------------------------------------------------------
            final = self._apply_hierarchy(grouped)

            self.logger.success(
                f"Pivot2 generated — {len(final)} PO-level audit rows."
            )

            return final

        except Exception as exc:
            raise Pivot2EngineError(
                f"Pivot2 generate failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Private: hierarchy blanking
    # ------------------------------------------------------------------

    def _apply_hierarchy(self, sorted_df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply the hierarchical blanking rule to *sorted_df*.

        Rule: a field is shown only when it OR a higher-level field changed
        from the previous row.

            show GL     = GL changed
            show CC     = CC changed  OR  GL changed
            show ION    = ION changed  OR  CC changed  OR  GL changed
            show Vendor = Vendor changed  OR  ION/CC/GL changed

        This means: the first PO under a new vendor always shows the vendor
        name (and all parent fields that changed).  Subsequent POs under the
        same vendor blank out GL/CC/ION/Vendor and show only PO + Total.

        When the GL Account changes, ALL four parent fields are re-shown even
        if CC/ION/Vendor are the same as before — this is consistent with the
        expected output where each GL group starts with a full header row.

        Args:
            sorted_df: Grouped dataframe sorted by SORT_COLUMNS.

        Returns:
            New dataframe with OUTPUT_COLUMNS; None in blanked cells.
        """

        output_rows = []

        # Sentinel values — guaranteed not to match any real SAP value
        _SENTINEL = object()

        prev_gl     = _SENTINEL
        prev_cc     = _SENTINEL
        prev_ion    = _SENTINEL
        prev_vendor = _SENTINEL

        for _, row in sorted_df.iterrows():

            cur_gl     = row["gl acct"]
            cur_cc     = row["cost centre"]
            cur_ion    = row["internalordernumber"]
            cur_vendor = row["vendor name"]
            cur_po     = row["purchase order"]
            cur_amount = row["business_amount"]

            # ----------------------------------------------------------
            # Determine which fields changed
            # Uses sentinel comparison to handle None/NaN correctly:
            # NaN != NaN in Python, so we normalise before comparing.
            # ----------------------------------------------------------
            def _val(v):
                """Normalise for comparison: None/NaN → empty string."""
                if v is _SENTINEL:
                    return _SENTINEL
                if pd.isna(v):
                    return ""
                return str(v).strip()

            gl_changed     = _val(cur_gl)     != _val(prev_gl)
            cc_changed     = _val(cur_cc)     != _val(prev_cc)
            ion_changed    = _val(cur_ion)    != _val(prev_ion)
            vendor_changed = _val(cur_vendor) != _val(prev_vendor)

            # ----------------------------------------------------------
            # Hierarchical show/blank decision
            # ----------------------------------------------------------
            show_gl     = gl_changed
            show_cc     = cc_changed     or gl_changed
            show_ion    = ion_changed    or cc_changed  or gl_changed
            show_vendor = vendor_changed or ion_changed or cc_changed or gl_changed

            # Done = "<PO>-<VendorName>"
            done = (
                str(cur_po) if pd.isna(cur_vendor) or str(cur_vendor).strip() == ""
                else f"{cur_po}-{cur_vendor}"
            )

            output_rows.append({
                "GL Acct":             cur_gl     if show_gl     else None,
                "Cost Centre":         cur_cc     if show_cc     else None,
                "Internalordernumber": cur_ion    if show_ion    else None,
                "Vendor Name":         cur_vendor if show_vendor else None,
                "PurchaseOrder":       cur_po,
                "Done":                done,
                "Total":               cur_amount,
            })

            # Update "previous" trackers
            prev_gl     = cur_gl
            prev_cc     = cur_cc
            prev_ion    = cur_ion
            prev_vendor = cur_vendor

        result = pd.DataFrame(output_rows, columns=self.OUTPUT_COLUMNS)
        return result
