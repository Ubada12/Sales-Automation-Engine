"""
validator.py

SAP workbook validation layer.

Responsibilities:

- File validation
- Dynamic SAP header detection
- SAP structure validation
- Critical field validation
- Dynamic month validation
"""

from __future__ import annotations

from pathlib import Path
from typing import List
from typing import Set

import pandas as pd

from core.logger import AppLogger
from core.month_mapper import (
    MonthMapper,
    MonthMappingError,
)


class ValidationError(Exception):
    """
    Validation failure.
    """

    pass


class Validator:
    """
    SAP validation engine.
    """

    REQUIRED_COLUMNS = {
        "year",
        "purchase order",
        "vendor name",
        "job",
        "gl acct",
        "cost centre",
        "internalordernumber",
        "done",
    }

    HEADER_SCAN_LIMIT = 10

    def __init__(
        self,
        logger: AppLogger,
    ) -> None:

        self.logger = logger

        self.month_mapper = MonthMapper()

    def validate_excel(
        self,
        file_path: Path,
    ) -> pd.DataFrame:
        """
        Validate SAP workbook.

        Args:
            file_path:
                SAP workbook

        Returns:
            Validated dataframe
        """

        if not file_path.exists():

            raise ValidationError(f"Missing file: {file_path}")

        try:

            header_row = self._detect_header_row(file_path)

            dataframe = pd.read_excel(
                file_path,
                dtype=object,
                header=header_row,
            )

        except Exception as exc:

            raise ValidationError(f"Excel read failed: {exc}") from exc

        self.logger.info(f"Loaded rows: {len(dataframe)}")

        self._validate_columns(dataframe.columns)

        self._validate_months(dataframe.columns)

        self._validate_critical_fields(dataframe)

        return dataframe

    def _detect_header_row(
        self,
        file_path: Path,
    ) -> int:
        """
        Dynamically detect SAP header row.

        SAP exports may contain:
        - Empty top rows
        - Banner rows
        - Metadata rows

        Returns:
            Header row index
        """

        preview = pd.read_excel(
            file_path,
            header=None,
            nrows=self.HEADER_SCAN_LIMIT,
            dtype=str,
        )

        for index, row in preview.iterrows():

            normalized = {
                str(value).strip().lower() for value in row.tolist() if pd.notna(value)
            }

            matched = self.REQUIRED_COLUMNS & normalized

            if len(matched) >= 4:

                self.logger.success(("Header row detected: " f"{index + 1}"))

                return index

        raise ValidationError("Unable to detect SAP header row")

    def _validate_columns(
        self,
        columns,
    ) -> None:
        """
        Validate SAP structure.
        """

        normalized: Set[str] = {str(column).strip().lower() for column in columns}

        missing = self.REQUIRED_COLUMNS - normalized

        if missing:

            raise ValidationError(("Missing columns: " f"{sorted(missing)}"))

        self.logger.success("Column validation passed")

    def _validate_months(
        self,
        columns,
    ) -> None:
        """
        Validate SAP month blocks.
        """

        try:

            detected = self.month_mapper.detect(list(columns))

            self.logger.success(("Months detected: " f"{len(detected)}"))

        except MonthMappingError as exc:

            raise ValidationError("Month detection failed") from exc

    def _validate_critical_fields(
        self,
        dataframe: pd.DataFrame,
    ) -> None:
        """
        Validate critical SAP business fields.
        """

        critical = [
            "purchase order",
            "vendor name",
            "job",
            "gl acct",
            "cost centre",
            "internalordernumber",
        ]

        normalized = {str(column).lower(): column for column in dataframe.columns}

        for field in critical:

            actual = normalized.get(field)

            if not actual:

                continue

            missing = dataframe[actual].isna().sum()

            if missing:

                self.logger.warning((f"{field} missing: " f"{missing}"))

        self.logger.success("Critical validation completed")
