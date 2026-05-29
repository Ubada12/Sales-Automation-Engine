"""
runner.py

Pipeline execution layer.

Responsibilities:
    - Orchestrate the full SAP processing pipeline
    - Share a single filtered "active rows" dataset across all three engines
    - Drive the live dashboard with stage updates and progress
    - Implement retry logic for recoverable failures (config-driven)
    - Generate warning and metadata sheets
    - Clean up temporary files after completion

BUGS FIXED vs. original runner.py:
    1. Pivot1 and Pivot2 were generated from the raw enriched dataframe,
       meaning they included fully-settled rows that Sheet1 excludes.
       Fixed: sheet1.filter_active() is called once and the result is
       shared with ALL three engines.

    2. _warnings() used DataFrame.get("col", False) which is only valid
       for dict-like access; on a DataFrame it returns a column Series if
       the column exists, or the scalar False if not — making the boolean
       index crash or silently return nothing.
       Fixed: explicit column existence check then boolean indexing.

    3. The LiveDashboard was instantiated and stored but never called.
       Fixed: dashboard.update_stage() and dashboard.render() are now
       driven from execute() at each pipeline stage.

    4. retry_attempts from config was never used.
       Fixed: execute() is wrapped in a retry loop that respects the
       configured number of attempts.

    5. config.ui.enable_live_dashboard is now honoured: when false,
       dashboard rendering is skipped entirely.
"""

from __future__ import annotations

import gc
import shutil
import time
import traceback
from pathlib import Path

import pandas as pd


class PipelineRunner:
    """
    SAP pipeline orchestrator.

    Wires together all engines and drives them in the correct order:
        validate → clean → detect months → enrich (money) →
        filter active rows → generate sheets → format → export
    """

    def __init__(
        self,
        *,
        root,
        config,
        logger,
        terminal,
        dashboard,
        validator,
        cleaner,
        money_engine,
        formatter,
        pivot1,
        pivot2,
        sheet1,
        month_mapper,
    ):

        self.root         = root
        self.config       = config
        self.logger       = logger
        self.terminal     = terminal
        self.dashboard    = dashboard
        self.validator    = validator
        self.cleaner      = cleaner
        self.money_engine = money_engine
        self.formatter    = formatter
        self.pivot1       = pivot1
        self.pivot2       = pivot2
        self.sheet1       = sheet1
        self.month_mapper = month_mapper

        self.input_dir  = root / "input"
        self.output_dir = root / "output"
        self.temp_dir   = root / "temp"

        # Read config flags used across the pipeline
        self._dashboard_enabled = self.config.get(
            "ui", "enable_live_dashboard", True
        )
        self._retry_attempts = max(
            1, self.config.get("recovery", "retry_attempts", 3)
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Main entry point called by main.py.

        Shows the interactive menu, lets the user choose a file,
        then executes the pipeline with retry.
        """

        try:
            self._prepare()

            selected = self.terminal.select_operation()

            if selected == 5:
                self.logger.info("User exited.")
                return

            file = self.terminal.choose_input_file(self.input_dir)

            workbook = self._execute_with_retry(file, selected)

            self.logger.success(f"Output written to: {workbook}")

        except Exception as exc:
            self._recover(exc)

        finally:
            self._cleanup()

    # ------------------------------------------------------------------
    # Pipeline execution (with retry)
    # ------------------------------------------------------------------

    def _execute_with_retry(
        self,
        input_file: Path,
        operation: int,
    ) -> Path:
        """
        Execute the pipeline, retrying up to retry_attempts times on failure.

        A retry is triggered for any exception *except* user-facing errors
        (FileNotFoundError, KeyboardInterrupt) where retrying would be futile.
        """

        last_exc: Exception | None = None

        for attempt in range(1, self._retry_attempts + 1):

            try:
                return self.execute(input_file, operation)

            except (FileNotFoundError, KeyboardInterrupt):
                # Non-recoverable — do not retry
                raise

            except Exception as exc:
                last_exc = exc
                self.logger.warning(
                    f"Pipeline attempt {attempt}/{self._retry_attempts} failed: "
                    f"{exc}"
                )
                if attempt < self._retry_attempts:
                    # Brief back-off before retrying
                    time.sleep(1.0)
                else:
                    self.logger.error(
                        f"All {self._retry_attempts} attempt(s) exhausted."
                    )

        # All retries failed — propagate the last exception
        raise last_exc  # type: ignore[misc]

    def execute(
        self,
        input_file: Path,
        operation: int,
    ) -> Path:
        """
        Full pipeline execution for a single run.

        Args:
            input_file: Path to the SAP Excel workbook.
            operation:  1=Pivot1, 2=Pivot2, 3=Sheet1, 4=All.

        Returns:
            Path to the generated output workbook.
        """

        total_steps = 6  # validation, clean, money, filter, generate, export
        step = 0

        # ----------------------------------------------------------
        # Stage 1: Validate
        # ----------------------------------------------------------
        step += 1
        self._stage("Validating", step, total_steps)
        raw = self.validator.validate_excel(input_file)

        # ----------------------------------------------------------
        # Stage 2: Detect month blocks
        # ----------------------------------------------------------
        step += 1
        self._stage("Detecting months", step, total_steps)
        self.month_mapper.detect(raw.columns.tolist())

        # ----------------------------------------------------------
        # Stage 3: Clean
        # ----------------------------------------------------------
        step += 1
        self._stage("Cleaning", step, total_steps)
        cleaned = self.cleaner.clean(raw)

        # ----------------------------------------------------------
        # Stage 4: Money engine — compute business_amount & zero-crossing
        # ----------------------------------------------------------
        step += 1
        self._stage("Computing provisions", step, total_steps)
        enriched = self.money_engine.add_business_amount(cleaned)

        # ----------------------------------------------------------
        # Stage 5: Filter active rows (SHARED across all engines)
        #
        # BUG FIX: Previously Pivot1 and Pivot2 ran on the full enriched
        # dataframe, including settled/closed rows.  Now ALL engines
        # receive only the same active rows that Sheet1 would display.
        # ----------------------------------------------------------
        step += 1
        self._stage("Filtering active rows", step, total_steps)
        active = self.sheet1.filter_active(enriched)

        # ----------------------------------------------------------
        # Stage 6: Generate requested sheets
        # ----------------------------------------------------------
        self._stage("Generating sheets", step, total_steps)
        sheets = {}

        if operation in (1, 4):
            sheets["Pivot1"] = self.pivot1.generate(active)

        if operation in (2, 4):
            sheets["Pivot2"] = self.pivot2.generate(active)

        if operation in (3, 4):
            sheets["Sheet1"] = self.sheet1.generate(active)

        # ----------------------------------------------------------
        # Stage 7: Export
        # ----------------------------------------------------------
        step += 1
        self._stage("Exporting workbook", step, total_steps)
        return self.formatter.export(
            self.output_dir,
            sheets,
            self._build_warnings(enriched),
            self._build_metadata(input_file, enriched, active),
        )

    # ------------------------------------------------------------------
    # Dashboard helpers
    # ------------------------------------------------------------------

    def _stage(self, label: str, step: int, total: int) -> None:
        """
        Update the live dashboard with the current stage name and progress.

        Respects the config.ui.enable_live_dashboard flag.
        """

        self.logger.info(f"[{step}/{total}] {label}")

        if not self._dashboard_enabled:
            return

        try:
            self.dashboard.update_stage(label)
            self.dashboard.render(step, total)
        except Exception:
            # Dashboard failures must never abort the pipeline
            pass

    # ------------------------------------------------------------------
    # Warning and metadata helpers
    # ------------------------------------------------------------------

    def _build_warnings(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Return rows flagged by the money engine as having no valid provision.

        BUG FIX: original code used dataframe.get("money_warning", False)
        which is dict-style access — on a DataFrame it returns a Series or
        the scalar False, making boolean indexing unreliable.
        """

        if "money_warning" not in dataframe.columns:
            return pd.DataFrame()

        warned = dataframe[dataframe["money_warning"] == True]  # noqa: E712

        if warned.empty:
            return pd.DataFrame()

        return warned

    def _build_metadata(
        self,
        file: Path,
        enriched: pd.DataFrame,
        active: pd.DataFrame,
    ) -> pd.DataFrame:
        """Build the Run_Metadata sheet content."""

        return pd.DataFrame(
            {
                "Metric": [
                    "RunID",
                    "Input File",
                    "Total Rows (after clean)",
                    "Active Rows (outstanding provision)",
                    "Excluded Rows (settled / closed)",
                ],
                "Value": [
                    self.logger.run_id,
                    file.name,
                    len(enriched),
                    len(active),
                    len(enriched) - len(active),
                ],
            }
        )

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _prepare(self) -> None:
        """Ensure all required directories exist."""

        for folder in (self.input_dir, self.output_dir, self.temp_dir):
            folder.mkdir(parents=True, exist_ok=True)

    def _recover(self, exc: Exception) -> None:
        """Log a fatal error and write a crash report."""

        self.logger.critical("Fatal pipeline error", exc)
        traceback.print_exc()

    def _cleanup(self) -> None:
        """Remove temp files (unless keep_temp_files=true) and free memory."""

        keep = self.config.get("recovery", "keep_temp_files", False)

        if self.temp_dir.exists() and not keep:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir.mkdir(exist_ok=True)

        gc.collect()
        self.logger.shutdown()
