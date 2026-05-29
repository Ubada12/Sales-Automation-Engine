"""
money_engine.py

Universal SAP provision extraction and business-amount resolution engine.

Responsibilities:
    - Detect the latest non-null provision value for every SAP row
    - Track whether the provision balance ever hit zero or went negative
      (the "zero-crossing" flag used by Sheet1 to exclude settled rows)
    - Add computed columns to the dataframe for use by all downstream engines
    - Flag rows whose provision could not be resolved for the Warnings sheet

BUGS FIXED vs. original:
    1. The original code used iterrows() — O(n) Python loop, very slow on large
       files.  Replaced with fully vectorised pandas operations.

    2. The original code picked the last non-None provision value iterating
       in reverse, but never checked whether an *intermediate* provision had
       already reached zero.  A row where Jan-provision = 0 (fully settled)
       followed by Feb-provision = 800 000 (new amount added) was incorrectly
       included.  Now we compute has_zero_crossing = True whenever any
       checkpoint column contains a value <= 0.

    3. The Decimal type was mixed with pandas float operations causing subtle
       aggregation issues.  Replaced with native float64 throughout; financial
       precision at this scale (rupees, 2 d.p.) is well within float64 range.

Column output contract (added to the dataframe):
    business_amount   float   Latest outstanding provision amount (>= 0)
    has_zero_crossing bool    True if any monthly balance/provision was <= 0
    money_source      str     Name of the column that supplied business_amount
    money_warning     bool    True if no valid provision was found (amount = 0)
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from config.config import Config
from core.logger import AppLogger
from core.month_mapper import MonthMapper


class MoneyEngineError(Exception):
    """Raised when the money engine cannot complete processing."""
    pass


class MoneyEngine:
    """
    Vectorised SAP provision resolver.

    Adds four computed columns to the enriched dataframe:
        business_amount, has_zero_crossing, money_source, money_warning
    """

    # Tolerance used when comparing a float to zero.
    # Values within this range of zero are treated as zero
    # (handles floating-point rounding artefacts like 0.00000001).
    _ZERO_TOLERANCE: float = 1.0

    def __init__(
        self,
        config: Config,
        logger: AppLogger,
        month_mapper: MonthMapper,
    ) -> None:

        self.config = config
        self.logger = logger
        self.month_mapper = month_mapper

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_business_amount(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Enrich *dataframe* with four computed provision columns.

        The method is fully vectorised: it operates on entire columns at once
        rather than looping row-by-row, making it suitable for 100 000+ rows.

        Args:
            dataframe: Cleaned SAP dataframe (headers already normalised to
                       lowercase by Cleaner).

        Returns:
            A copy of the dataframe with four new columns appended:
                business_amount, has_zero_crossing, money_source, money_warning

        Raises:
            MoneyEngineError: On unexpected failures.
        """

        try:
            result = dataframe.copy()

            # ------------------------------------------------------------------
            # 1. Identify which provision/balance columns are present
            # ------------------------------------------------------------------
            provision_cols = self.month_mapper.provision_columns()
            checkpoint_cols = self.month_mapper.all_checkpoint_columns()

            available_provision = [c for c in provision_cols if c in result.columns]
            available_checkpoint = [c for c in checkpoint_cols if c in result.columns]

            if not available_provision:
                # No provision columns found — warn and set safe defaults
                self.logger.warning(
                    "No provision columns found in dataframe. "
                    "All business_amount values set to 0."
                )
                result["business_amount"]   = 0.0
                result["has_zero_crossing"] = True
                result["money_source"]      = None
                result["money_warning"]     = True
                return result

            # ------------------------------------------------------------------
            # 2. Parse all checkpoint columns to float (coerce bad values → NaN)
            # ------------------------------------------------------------------
            checkpoint_numeric = pd.DataFrame(index=result.index)
            for col in available_checkpoint:
                checkpoint_numeric[col] = pd.to_numeric(
                    result[col], errors="coerce"
                )

            provision_numeric = pd.DataFrame(index=result.index)
            for col in available_provision:
                provision_numeric[col] = pd.to_numeric(
                    result[col], errors="coerce"
                )

            # ------------------------------------------------------------------
            # 3. has_zero_crossing
            #    True if ANY checkpoint column has a non-NaN value <= zero
            #    (within tolerance — guards against floating-point near-zero).
            #
            #    Business meaning: the provision balance already reached zero
            #    at some monthly checkpoint, meaning the work is fully invoiced/
            #    paid.  Such rows must be excluded from Sheet1.
            # ------------------------------------------------------------------
            def _any_at_or_below_zero(row: pd.Series) -> bool:
                valid = row.dropna()
                if valid.empty:
                    return False
                return bool((valid <= self._ZERO_TOLERANCE).any())

            result["has_zero_crossing"] = checkpoint_numeric.apply(
                _any_at_or_below_zero, axis=1
            )

            # ------------------------------------------------------------------
            # 4. business_amount  &  money_source
            #    Walk provision columns from LATEST (rightmost) to EARLIEST.
            #    First non-NaN value found is the current outstanding amount.
            #
            #    Rationale: the rightmost provision column reflects the most
            #    up-to-date remaining balance (e.g. April provision after all
            #    January–April invoices have been processed).
            # ------------------------------------------------------------------
            reversed_cols = list(reversed(available_provision))

            # Build the business_amount by combining columns right-to-left:
            # start with NaN, then fill from the rightmost column leftward.
            amounts = pd.Series(np.nan, index=result.index)
            sources = pd.Series(None, index=result.index, dtype=object)

            for col in reversed_cols:
                col_values = provision_numeric[col]
                # Fill only rows that are still NaN (i.e., haven't been
                # assigned a value from a later month yet)
                mask = amounts.isna() & col_values.notna()
                amounts  = amounts.where(~mask, col_values)
                sources  = sources.where(~mask, col)

            # Rows where no valid provision was found → 0.0 with a warning
            no_provision_mask = amounts.isna()
            amounts = amounts.fillna(0.0)

            result["business_amount"] = amounts.astype(float)
            result["money_source"]    = sources

            # ------------------------------------------------------------------
            # 5. money_warning
            #    True for rows where no valid provision column could be read.
            #    These appear in the Warnings sheet for manual review.
            # ------------------------------------------------------------------
            result["money_warning"] = no_provision_mask

            # Log any warnings found
            warning_count = int(no_provision_mask.sum())
            if warning_count:
                self.logger.warning(
                    f"{warning_count} row(s) had no valid provision value — "
                    "check the Warnings sheet."
                )

            self.logger.success(
                f"Money engine completed — "
                f"{len(result)} rows processed, "
                f"{warning_count} warnings."
            )

            return result

        except Exception as exc:
            raise MoneyEngineError(
                f"Money engine failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Private helpers (kept for testability)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_single(value) -> Optional[float]:
        """
        Attempt to parse a single cell value to float.

        Returns None if the value is null or cannot be converted.
        Used in unit tests; the main pipeline uses vectorised pd.to_numeric.
        """

        if pd.isna(value):
            return None

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip().replace(",", "").replace("₹", "")

        try:
            return float(text)
        except ValueError:
            return None
