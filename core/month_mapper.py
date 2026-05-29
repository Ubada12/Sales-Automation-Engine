"""
month_mapper.py

Dynamic SAP month-block detection engine.

Responsibilities:
    - Detect SAP month blocks from column headers
    - Support both short names (Jan, Feb, Apr) and full names (January, April)
    - Expose ordered provision columns for downstream engines
    - Expose ordered balance columns for zero-crossing detection

SAP month-block structure (one block per month):
    <Month> Inv        ← invoice reference column
    <Month> Amt        ← amount invoiced that month
    <Month> Balance    ← running balance after invoicing  (= prev_balance - amt)
    Provision          ← remaining provision (same value as Balance, stored separately)
    Comments           ← free-text notes

BUG FIXED:
    The original pattern only matched three-letter abbreviations (e.g. "apr inv").
    The real SAP export uses "April Inv" (full name). The regex now accepts both
    short and full English month names so no month block is silently skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


class MonthMappingError(Exception):
    """Raised when no SAP month blocks can be detected in the column list."""
    pass


@dataclass(frozen=True)
class MonthBlock:
    """
    Immutable descriptor for one SAP month block.

    Stores the *exact* column names as they appear in the dataframe
    (after pandas de-duplication but before any case normalisation).
    The month attribute is always stored as the three-letter abbreviation
    regardless of how it appeared in the source file (e.g. "april" → "apr").
    """

    # Three-letter normalised month name, e.g. "jan", "feb", "apr"
    month: str

    # Column names exactly as found in the dataframe
    invoice_column: str
    amount_column: str
    balance_column: str
    provision_column: str
    comment_column: str


class MonthMapper:
    """
    Dynamically detects ordered SAP month blocks from a list of column headers.

    Usage:
        mapper = MonthMapper()
        blocks = mapper.detect(dataframe.columns.tolist())
        # blocks is an ordered list of MonthBlock from earliest to latest month

    The mapper is stateful: after detect() succeeds the detected blocks are
    stored and can be queried via provision_columns() and balance_columns().
    """

    # ---------------------------------------------------------------------------
    # Regex: matches both abbreviated ("Jan Inv") and full ("January Inv") forms.
    # Capture group 1 is the month token which we normalise to 3-letter form.
    # ---------------------------------------------------------------------------
    _MONTH_PATTERN = re.compile(
        r"^("
        r"jan(?:uary)?"
        r"|feb(?:ruary)?"
        r"|mar(?:ch)?"
        r"|apr(?:il)?"
        r"|may"
        r"|jun(?:e)?"
        r"|jul(?:y)?"
        r"|aug(?:ust)?"
        r"|sep(?:tember)?"
        r"|oct(?:ober)?"
        r"|nov(?:ember)?"
        r"|dec(?:ember)?"
        r")\s+inv$",
        re.IGNORECASE,
    )

    # Canonical 3-letter form for every possible match group value
    _NORMALIZE: dict[str, str] = {
        "jan": "jan", "january": "jan",
        "feb": "feb", "february": "feb",
        "mar": "mar", "march": "mar",
        "apr": "apr", "april": "apr",
        "may": "may",
        "jun": "jun", "june": "jun",
        "jul": "jul", "july": "jul",
        "aug": "aug", "august": "aug",
        "sep": "sep", "september": "sep",
        "oct": "oct", "october": "oct",
        "nov": "nov", "november": "nov",
        "dec": "dec", "december": "dec",
    }

    def __init__(self) -> None:
        # Populated by detect(); empty until first successful call
        self.month_blocks: List[MonthBlock] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, columns: List[str]) -> List[MonthBlock]:
        """
        Scan *columns* for SAP month blocks and store them in order.

        A valid month block requires the four columns immediately following
        the "<Month> Inv" column to match the expected SAP pattern:
            index+0 : <Month> Inv        (trigger)
            index+1 : <Month> Amt        (must contain "amt")
            index+2 : <Month> Balance    (must contain "balance")
            index+3 : Provision[.N]      (must contain "provision")
            index+4 : Comments[.N]       (free-text, no validation)

        Args:
            columns: Raw column list from pandas (may contain de-dup suffixes
                     like "Provision.1", "Provision.2" etc.)

        Returns:
            Ordered list of MonthBlock objects (earliest month first).

        Raises:
            MonthMappingError: If no valid month blocks are found at all.
        """

        detected: List[MonthBlock] = []
        total = len(columns)

        for index, column in enumerate(columns):

            normalised = str(column).strip().lower()
            match = self._MONTH_PATTERN.match(normalised)

            if not match:
                continue

            # Need at least 4 more columns after this one
            if index + 4 >= total:
                continue

            # Peek at the next four columns
            amt_col   = columns[index + 1]
            bal_col   = columns[index + 2]
            prov_col  = columns[index + 3]
            cmnt_col  = columns[index + 4]

            # Validate expected column structure
            if "amt"      not in str(amt_col).lower():
                continue
            if "balance"  not in str(bal_col).lower():
                continue
            if "provision" not in str(prov_col).lower():
                continue

            # Normalise month token to 3-letter form
            raw_month = match.group(1).lower()
            short_month = self._NORMALIZE.get(raw_month, raw_month[:3])

            block = MonthBlock(
                month=short_month,
                invoice_column=str(column),
                amount_column=str(amt_col),
                balance_column=str(bal_col),
                provision_column=str(prov_col),
                comment_column=str(cmnt_col),
            )

            detected.append(block)

        if not detected:
            raise MonthMappingError(
                "No SAP month blocks detected. "
                "Expected columns like 'Jan Inv / Jan Amt / Jan Balance / Provision'. "
                "Check that the input file is a valid SAP export."
            )

        self.month_blocks = detected
        return detected

    def provision_columns(self) -> List[str]:
        """
        Return the provision column names in chronological order
        (earliest month first), normalised to lowercase.

        These are the columns that hold the *remaining balance* after
        each month's invoicing — used by MoneyEngine to find the latest
        outstanding amount.
        """
        return [
            str(block.provision_column).strip().lower()
            for block in self.month_blocks
        ]

    def balance_columns(self) -> List[str]:
        """
        Return the balance column names in chronological order,
        normalised to lowercase.

        These are the intermediate running-balance columns (e.g.
        "jan balance", "feb balance") — used by MoneyEngine to detect
        whether the provision ever hit zero (zero-crossing check).
        """
        return [
            str(block.balance_column).strip().lower()
            for block in self.month_blocks
        ]

    def all_checkpoint_columns(self) -> List[str]:
        """
        Return every column that represents a provision checkpoint,
        in chronological order, normalised to lowercase.

        This includes both the balance columns and the provision columns
        for each month block — giving the most complete picture of whether
        the balance ever touched zero.

        Used by MoneyEngine.add_business_amount() to build the
        has_zero_crossing flag.
        """
        result: List[str] = []
        for block in self.month_blocks:
            result.append(str(block.balance_column).strip().lower())
            result.append(str(block.provision_column).strip().lower())
        return result
