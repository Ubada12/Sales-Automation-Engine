"""
grouping_engine.py

Generic grouping and aggregation framework shared by all pivot engines.

Responsibilities:
    - Execute pandas groupby with consistent settings
    - Provide reusable aggregation helpers (join, sum, first-non-null)
    - Validate that required columns exist before grouping
    - Log group-reduction metrics

BUG FIXED:
    unique_join previously used "," (no space) as the separator.
    The expected output format is ", " (comma + space), matching the
    original Excel pivot output.  Separator changed accordingly.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

import pandas as pd

from core.logger import AppLogger


class GroupingEngineError(Exception):
    """Raised when a grouping operation cannot be completed."""
    pass


class GroupingEngine:
    """
    Shared dataframe grouping engine.

    Instantiated once in main.py and injected into all pivot engines,
    ensuring consistent aggregation behaviour across Sheet1, Pivot1, Pivot2.
    """

    def __init__(self, logger: AppLogger) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Primary grouping method
    # ------------------------------------------------------------------

    def group(
        self,
        dataframe: pd.DataFrame,
        group_columns: List[str],
        aggregation_rules: Dict[str, str | Callable],
    ) -> pd.DataFrame:
        """
        Group *dataframe* by *group_columns* and apply *aggregation_rules*.

        Args:
            dataframe:
                Input dataframe (should be pre-filtered active rows).
            group_columns:
                Columns that define a unique bucket (e.g. GL+CC+ION+Vendor).
            aggregation_rules:
                Dict mapping column → aggregation function or string alias.
                Accepted function values: any callable that accepts a Series.

        Returns:
            Grouped and aggregated dataframe with index reset.

        Raises:
            GroupingEngineError: If required columns are missing.
        """

        try:
            self._validate_columns(dataframe, group_columns)
            self._validate_aggregates(dataframe, aggregation_rules)

            self.logger.info(
                f"Grouping {len(dataframe)} rows by {group_columns} …"
            )

            grouped = (
                dataframe
                .groupby(
                    group_columns,
                    dropna=False,   # keep NaN/blank groups intact
                    sort=False,     # caller sorts explicitly after grouping
                )
                .agg(aggregation_rules)
                .reset_index()
            )

            self.logger.success(
                f"Grouping complete: {len(dataframe)} → {len(grouped)} rows."
            )

            return grouped

        except GroupingEngineError:
            raise
        except Exception as exc:
            raise GroupingEngineError(f"Grouping failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Aggregation helper functions
    # (passed as callables inside aggregation_rules dicts)
    # ------------------------------------------------------------------

    def unique_join(self, values: pd.Series) -> str:
        """
        Join unique non-null values as a comma-separated string.

        Preserves insertion order (first occurrence wins for de-dup).
        Separator is ", " (comma + space) to match expected Excel output.

        Example:
            [661, 662, 661, 663]  →  "661, 662, 663"
        """

        seen: set = set()
        unique: List[str] = []

        for value in values:
            if pd.isna(value):
                continue
            text = str(value).strip()
            if not text or text.lower() in ("nan", "none", ""):
                continue
            if text in seen:
                continue
            seen.add(text)
            unique.append(text)

        return ", ".join(unique)

    def first_non_null(self, values: pd.Series) -> Any:
        """
        Return the first non-null value in *values*.

        Used to carry forward metadata columns (e.g. money_source)
        after a groupby collapses multiple rows into one.
        """

        for value in values:
            if pd.notna(value) and str(value).strip() not in ("", "nan", "none"):
                return value

        return None

    def sum_money(self, values: pd.Series) -> float:
        """
        Sum provision amounts.

        Coerces to numeric first so mixed str/float columns (which can
        appear if cleaner is skipped in tests) still produce correct totals.
        """

        return pd.to_numeric(values, errors="coerce").fillna(0.0).sum()

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_columns(
        self,
        dataframe: pd.DataFrame,
        columns: List[str],
    ) -> None:
        """Raise if any grouping column is absent from the dataframe."""

        missing = [c for c in columns if c not in dataframe.columns]
        if missing:
            raise GroupingEngineError(
                f"Grouping columns not found in dataframe: {missing}. "
                f"Available: {list(dataframe.columns)}"
            )

    def _validate_aggregates(
        self,
        dataframe: pd.DataFrame,
        aggregates: Dict,
    ) -> None:
        """Raise if any aggregation target column is absent from the dataframe."""

        missing = [c for c in aggregates if c not in dataframe.columns]
        if missing:
            raise GroupingEngineError(
                f"Aggregation columns not found in dataframe: {missing}. "
                f"Available: {list(dataframe.columns)}"
            )
