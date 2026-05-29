"""
logger.py

Production logging layer.

Responsibilities:

- File logging
- Terminal logging
- Crash logging
- Session tracking
- Timer metrics
- Safe fallback handling
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class LoggerInitializationError(Exception):
    """
    Logger initialization failure.
    """
    pass


class AppLogger:

    """
    Central logging manager.
    """

    def __init__(
        self,
        logs_dir: Path,
        crash_dir: Path,
        enable_terminal: bool,
        enable_file: bool,
        developer_mode: bool,
    ) -> None:

        self.logs_dir = logs_dir
        self.crash_dir = crash_dir

        self.enable_terminal = enable_terminal
        self.enable_file = enable_file

        self.developer_mode = developer_mode

        self.run_id = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        self.logger = logging.getLogger(
            "sap_automation"
        )

        self._initialize()

    def _initialize(self) -> None:

        try:

            self.logs_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            self.crash_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            self.logger.handlers.clear()

            self.logger.setLevel(
                logging.DEBUG
            )

            formatter = logging.Formatter(
                (
                    "%(asctime)s | "
                    "%(levelname)s | "
                    "%(message)s"
                )
            )

            if self.enable_file:

                log_file = (
                    self.logs_dir
                    / f"{self.run_id}.log"
                )

                file_handler = logging.FileHandler(
                    log_file,
                    encoding="utf-8",
                )

                file_handler.setFormatter(
                    formatter
                )

                self.logger.addHandler(
                    file_handler
                )

            if self.enable_terminal:

                stream = logging.StreamHandler(
                    sys.stdout
                )

                stream.setFormatter(
                    formatter
                )

                self.logger.addHandler(
                    stream
                )

        except Exception as exc:

            raise LoggerInitializationError(
                str(exc)
            ) from exc

    def info(
        self,
        message: str,
    ) -> None:

        self.logger.info(message)

    def success(
        self,
        message: str,
    ) -> None:

        self.logger.info(
            f"[SUCCESS] {message}"
        )

    def warning(
        self,
        message: str,
    ) -> None:

        self.logger.warning(message)

    def error(
        self,
        message: str,
    ) -> None:

        self.logger.error(message)

    def debug(
        self,
        message: str,
    ) -> None:

        if self.developer_mode:

            self.logger.debug(message)

    def critical(
        self,
        message: str,
        exc: Optional[Exception] = None,
    ) -> None:

        self.logger.critical(message)

        if exc:

            crash_file = (
                self.crash_dir
                /
                f"crash_{self.run_id}.log"
            )

            try:

                with crash_file.open(
                    "w",
                    encoding="utf-8",
                ) as file:

                    file.write(
                        str(exc)
                    )

            except OSError:

                pass

    def shutdown(self) -> None:

        handlers = list(
            self.logger.handlers
        )

        for handler in handlers:

            handler.close()

            self.logger.removeHandler(
                handler
            )