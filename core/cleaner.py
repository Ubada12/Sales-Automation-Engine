"""
cleaner.py

SAP dataframe cleaning and normalisation layer.

Responsibilities:
    - Normalise column headers to lowercase with single spaces
    - Standardise null / missing representations to Python None
    - Strip whitespace from text values (preserve original casing)
    - Convert numeric strings to float  ← BUG FIXED (see note below)
    - Clean SAP identifier formatting (remove .0 float artefacts)
    - Normalise grouping fields for consistent group-by operations
    - Remove exact-duplicate rows (configurable)
    - Optionally skip rows whose critical fields are entirely blank

BUG FIXED:
    _normalize_numeric previously only converted scientific-notation strings
    (e.g. "1.5E+06") to float.  Plain numeric strings like "600000" or
    "33222.99" were left as str, which silently broke any pandas numeric
    aggregation downstream.  The fix attempts float() on every non-None
    string value; non-numeric strings are returned unchanged.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

import pandas as pd

from config.config import Config
from core.logger import AppLogger


class CleaningError(Exception):
    """Raised when the cleaning pipeline encounters an unrecoverable error."""
    pass


class Cleaner:
    """
    SAP dataframe normalisation engine.

    All transformations are applied in a fixed, safe order:
        1. Header normalisation
        2. Null standardisation
        3. Text normalisation
        4. Numeric normalisation   ← now handles all numeric strings
        5. Identifier normalisation
        6. Grouping-field normalisation
        7. Duplicate removal
        8. Bad-row removal (optional, config-driven)
    """

    # Values that represent "missing" regardless of how they are written
    NULL_VALUES = {
        "", "-", "--", "na", "n/a", "null", "none", "nan", "#n/a", "#na",
    }

    # Columns whose values should be coerced to clean numeric strings
    # (e.g. "660702210.0" → "660702210")
    IDENTIFIER_COLUMNS = {
        "purchase order",
        "gl acct",
        "cost centre",
        "internalordernumber",
    }

    # Columns used as grouping keys — must not contain NaN after cleaning
    # (converted to empty string so groupby() is stable)
    GROUPING_COLUMNS = {
        "purchase order",
        "vendor name",
        "job",
        "gl acct",
        "cost centre",
        "internalordernumber",
    }

    # Critical fields: if ALL are blank on a row and skip_bad_rows=true,
    # the row is dropped
    CRITICAL_FIELDS = {
        "purchase order",
        "vendor name",
        "gl acct",
    }

    def __init__(self, config: Config, logger: AppLogger) -> None:
        self.config = config
        self.logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clean(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Execute the full cleaning pipeline on *dataframe*.

        Returns a cleaned copy; the original is never mutated.

        Raises:
            CleaningError: If any stage fails unexpectedly.
        """

        try:
            cleaned = dataframe.copy()

            cleaned = self._normalize_headers(cleaned)
            cleaned = self._normalize_nulls(cleaned)
            cleaned = self._normalize_text(cleaned)
            cleaned = self._normalize_numeric(cleaned)      # fixed
            cleaned = self._normalize_identifiers(cleaned)
            cleaned = self._normalize_grouping_fields(cleaned)
            cleaned = self._remove_duplicates(cleaned)
            cleaned = self._remove_bad_rows(cleaned)

            self.logger.success(
                f"Cleaning completed — {len(cleaned)} rows retained."
            )
            return cleaned

        except Exception as exc:
            raise CleaningError(f"Cleaning pipeline failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Stage 1 — Header normalisation
    # ------------------------------------------------------------------

    def _normalize_headers(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Lowercase all column headers and collapse repeated whitespace.

        NOTE: Only headers are transformed. Cell values preserve their
        original SAP casing throughout the pipeline.
        """

        mapping: Dict[str, str] = {}
        for col in dataframe.columns:
            normalised = str(col).strip().lower()
            normalised = re.sub(r"\s+", " ", normalised)
            mapping[col] = normalised

        dataframe.rename(columns=mapping, inplace=True)
        self.logger.info("Header normalisation done.")
        return dataframe

    # ------------------------------------------------------------------
    # Stage 2 — Null standardisation
    # ------------------------------------------------------------------

    def _normalize_nulls(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Convert all known null representations to Python None.

        Handles: pandas NaN/NaT, empty strings, "na", "n/a", "null",
        "none", "nan", "#n/a", "--", and plain "-".
        """

        for col in dataframe.columns:
            dataframe[col] = dataframe[col].apply(self._to_none)

        self.logger.info("Null normalisation done.")
        return dataframe

    def _to_none(self, value) -> Optional[object]:
        """Return None for any recognised null value, else return value unchanged."""

        if pd.isna(value):
            return None

        text = str(value).strip().lower()
        if text in self.NULL_VALUES:
            return None

        return value

    # ------------------------------------------------------------------
    # Stage 3 — Text normalisation
    # ------------------------------------------------------------------



    def _normalize_text(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Strip leading/trailing whitespace from all string values.

        IMPORTANT: Do NOT lowercase cell values — SAP vendor names,
        job descriptions, and PO identifiers must retain their original
        casing to match source-system records.
        """

        for col in dataframe.select_dtypes(include="object").columns:
            dataframe[col] = dataframe[col].apply(self._strip_text)

        self.logger.info("Text normalisation done.")
        return dataframe

    @staticmethod
    def _strip_text(value):
        if value is None:
            return None
        return str(value).strip()

    # ------------------------------------------------------------------
    # Stage 4 — Numeric normalisation   (BUG FIX)
    # ------------------------------------------------------------------

    def _normalize_numeric(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Convert numeric-looking string values to Python float.

        Original code only handled scientific notation (e.g. "1.5E+06").
        Regular numeric strings like "600000" or "33222.99" were left as
        str, silently breaking downstream pandas aggregation.

        Fix: attempt float() on every non-None string.  Non-numeric strings
        (vendor names, job descriptions, comments) are returned unchanged.
        Currency symbols (₹, commas) are stripped before conversion.
        """

        for col in dataframe.columns:
            dataframe[col] = dataframe[col].apply(self._to_numeric)

        self.logger.info("Numeric normalisation done.")
        return dataframe

    @staticmethod
    def _to_numeric(value):
        """
        Try to parse *value* as float.  Return original value if not numeric.

        Examples:
            600000      → 600000.0
            "33222.99"  → 33222.99
            "₹50,000"   → 50000.0
            "1.5E+6"    → 1500000.0
            "Mediacom"  → "Mediacom"   (unchanged)
            None        → None
        """

        if value is None:
            return None

        # Already numeric — return as float for type consistency
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()

        # Strip common formatting characters
        text = text.replace(",", "").replace("₹", "").strip()

        if not text:
            return None

        try:
            return float(text)
        except ValueError:
            # Not a number — preserve original string value
            return value

    # ------------------------------------------------------------------
    # Stage 5 — Identifier normalisation
    # ------------------------------------------------------------------

    def _normalize_identifiers(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Remove Excel float artefacts from SAP identifier columns.

        Excel sometimes stores integer POs as floats (e.g. 660702210.0).
        After stage 4 these become float values.  We convert them to
        clean integer strings.

        Example: 660702210.0 → "660702210"
        """

        for col in dataframe.columns:
            if col not in self.IDENTIFIER_COLUMNS:
                continue
            dataframe[col] = dataframe[col].apply(self._clean_identifier)

        self.logger.info("Identifier normalisation done.")
        return dataframe

    @staticmethod
    def _clean_identifier(value):
        """
        Convert float identifiers to clean integer strings.
        Leave non-numeric identifiers (e.g. "SGPI99999999", "NonPO") intact.
        """

        if value is None:
            return None

        # Float artefact: 660702210.0 → "660702210"
        # Guard: float NaN must be checked before int() conversion
        if isinstance(value, float):
            import math
            if math.isnan(value):
                return None
            if value == int(value):
                return str(int(value))
            # Fractional float used as an ID — preserve as-is
            return str(value)

        if isinstance(value, int):
            return str(value)

        text = str(value).strip()

        # "660702210.0" string form
        if re.match(r"^\d+\.0$", text):
            return text[:-2]

        return text

    # ------------------------------------------------------------------
    # Stage 6 — Grouping-field normalisation
    # ------------------------------------------------------------------

    def _normalize_grouping_fields(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure grouping columns contain clean strings (never NaN).

        Replacing None with "" keeps group-by operations stable across
        pandas versions.  Downstream filters explicitly check for ""
        to exclude blank-PO rows.
        """

        for col in dataframe.columns:
            if col not in self.GROUPING_COLUMNS:
                continue
            dataframe[col] = (
                dataframe[col]
                .fillna("")
                .astype(str)
                .str.strip()
            )

        self.logger.info("Grouping-field normalisation done.")
        return dataframe

    # ------------------------------------------------------------------
    # Stage 7 — Duplicate removal
    # ------------------------------------------------------------------

    def _remove_duplicates(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Drop exact-duplicate rows (configurable via config.yaml).

        Only removes rows where *every* column value is identical.
        Near-duplicates with different provision amounts are preserved.
        """

        enabled = self.config.get(
            "validation", "remove_exact_duplicates", True
        )

        if not enabled:
            return dataframe

        before = len(dataframe)
        cleaned = dataframe.drop_duplicates().reset_index(drop=True)
        removed = before - len(cleaned)

        if removed:
            self.logger.warning(f"{removed} exact duplicate row(s) removed.")

        return cleaned

    # ------------------------------------------------------------------
    # Stage 8 — Bad-row removal (optional)
    # ------------------------------------------------------------------

    def _remove_bad_rows(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Drop rows where all critical fields are blank (config-driven).

        A "bad row" is one where Purchase Order, Vendor Name, and GL Acct
        are all empty strings / None — typically a blank spacer row that
        survived duplicate removal.
        """

        enabled = self.config.get(
            "validation", "skip_bad_rows", True
        )

        if not enabled:
            return dataframe

        # Identify critical columns that actually exist in the dataframe
        present = [
            col for col in self.CRITICAL_FIELDS
            if col in dataframe.columns
        ]

        if not present:
            return dataframe

        # Keep row if at least one critical field is non-blank
        def _has_content(row: pd.Series) -> bool:
            return any(
                str(row.get(col, "")).strip() not in ("", "none", "nan")
                for col in present
            )

        before = len(dataframe)
        mask = dataframe.apply(_has_content, axis=1)
        cleaned = dataframe[mask].reset_index(drop=True)
        removed = before - len(cleaned)

        if removed:
            self.logger.warning(f"{removed} bad (all-blank critical field) row(s) skipped.")

        return cleaned
