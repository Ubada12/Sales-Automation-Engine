"""
progress.py

Progress rendering engine.

Responsibilities:

- Adaptive refresh strategy
- Progress bar rendering
- Percentage generation
"""

from __future__ import annotations

from config.config import Config


class ProgressRenderer:
    """
    Terminal progress renderer.
    """

    BAR_SIZE = 30

    def __init__(
        self,
        config: Config,
    ) -> None:

        self.config = config

    def build_bar(
        self,
        current: int,
        total: int,
    ) -> str:
        """
        Render progress bar.
        """

        if total <= 0:

            total = 1

        ratio = current / total

        filled = int(ratio * self.BAR_SIZE)

        empty = self.BAR_SIZE - filled

        return "█" * filled + "░" * empty

    def percentage(
        self,
        current: int,
        total: int,
    ) -> int:

        if total <= 0:

            return 0

        return int((current / total) * 100)

    def refresh_step(
        self,
        rows: int,
    ) -> int:
        """
        Adaptive refresh.
        """

        small = self.config.get(
            "performance",
            "small_file_threshold",
            1000,
        )

        medium = self.config.get(
            "performance",
            "medium_file_threshold",
            10000,
        )

        if rows <= small:

            return self.config.get(
                "performance",
                "small_file_refresh_rows",
                10,
            )

        if rows <= medium:

            return self.config.get(
                "performance",
                "medium_file_refresh_rows",
                50,
            )

        return self.config.get(
            "performance",
            "large_file_refresh_rows",
            500,
        )
