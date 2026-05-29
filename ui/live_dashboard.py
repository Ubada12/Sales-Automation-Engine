"""
live_dashboard.py

Dynamic terminal dashboard.

Responsibilities:

- Runtime panel
- Warning panel
- Current stage
- Dynamic redraw
"""

from __future__ import annotations

import os
import time

from ui.progress import (
    ProgressRenderer,
)

from core.logger import (
    AppLogger,
)


class LiveDashboard:
    """
    Dynamic terminal UI.
    """

    def __init__(
        self,
        progress: ProgressRenderer,
        logger: AppLogger,
    ) -> None:

        self.progress = progress

        self.logger = logger

        self.start_time = time.time()

        self.stage = "Idle"

        self.warning = "None"

    def update_stage(
        self,
        stage: str,
    ) -> None:

        self.stage = stage

    def update_warning(
        self,
        warning: str,
    ) -> None:

        self.warning = warning

    def render(
        self,
        current: int,
        total: int,
    ) -> None:

        self._clear()

        elapsed = int(time.time() - self.start_time)

        percent = self.progress.percentage(
            current,
            total,
        )

        bar = self.progress.build_bar(
            current,
            total,
        )

        print()

        print("=" * 45)

        print("SAP AUTOMATION ENGINE")

        print("=" * 45)

        print()

        print(f"Stage: {self.stage}")

        print()

        print(f"[{bar}]")

        print(f"{percent}%")

        print(f"{current}/{total}")

        print()

        print(f"Warning: " f"{self.warning}")

        print()

        print(f"Runtime: " f"{elapsed}s")

        print()

        print("=" * 45)

    def _clear(
        self,
    ) -> None:

        os.system("cls" if os.name == "nt" else "clear")
