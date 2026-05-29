"""
main.py

Application gate.

Responsibilities:

- Bootstrap app
- Dependency wiring
- Entry point only
"""

from __future__ import annotations

from pathlib import Path

from config.config import Config

from core.logger import AppLogger

from core.validator import Validator
from core.cleaner import Cleaner
from core.money_engine import MoneyEngine
from core.grouping_engine import GroupingEngine
from core.month_mapper import MonthMapper
from core.formatter import Formatter

from pivots.pivot1_engine import Pivot1Engine
from pivots.pivot2_engine import Pivot2Engine
from pivots.sheet1_engine import Sheet1Engine

from ui.progress import ProgressRenderer
from ui.live_dashboard import LiveDashboard
from ui.terminal import TerminalUI

from pipeline.runner import PipelineRunner

ROOT = Path(__file__).resolve().parent


def main() -> None:
    """
    Application entry.
    """

    config = Config(ROOT / "config" / "config.yaml")

    logger = AppLogger(
        logs_dir=ROOT / "logs",
        crash_dir=ROOT / "logs" / "crash",
        enable_terminal=config.get(
            "logging",
            "enable_terminal_logging",
        ),
        enable_file=config.get(
            "logging",
            "enable_file_logging",
        ),
        developer_mode=config.get(
            "logging",
            "developer_mode_default",
        ),
    )

    month_mapper = MonthMapper()

    grouping = GroupingEngine(logger)

    progress = ProgressRenderer(config)

    dashboard = LiveDashboard(
        progress,
        logger,
    )

    terminal = TerminalUI(logger)

    runner = PipelineRunner(
        root=ROOT,
        config=config,
        logger=logger,
        terminal=terminal,
        dashboard=dashboard,
        validator=Validator(logger),
        cleaner=Cleaner(
            config,
            logger,
        ),
        money_engine=MoneyEngine(
            config,
            logger,
            month_mapper,
        ),
        formatter=Formatter(
            config,
            logger,
        ),
        pivot1=Pivot1Engine(
            grouping,
            logger,
        ),
        pivot2=Pivot2Engine(
            grouping,
            logger,
        ),
        sheet1=Sheet1Engine(
            grouping,
            logger,
        ),
        month_mapper=month_mapper,
    )

    runner.run()


if __name__ == "__main__":
    main()
