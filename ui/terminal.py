"""
terminal.py

User interaction layer.

Responsibilities:

- Main menu
- File selection
- Confirmation prompts
"""

from __future__ import annotations

from pathlib import Path

from core.logger import (
    AppLogger,
)


class TerminalUI:
    """
    Interactive CLI.
    """

    def __init__(
        self,
        logger: AppLogger,
    ) -> None:

        self.logger = logger

    def select_operation(
        self,
    ) -> int:
        """
        Main menu.
        """

        print()

        print("=" * 40)

        print("SAP AUTOMATION")

        print("=" * 40)

        print()

        print("1 Generate Pivot1")

        print("2 Generate Pivot2")

        print("3 Generate Sheet1")

        print("4 Generate All")

        print("5 Exit")

        while True:

            try:

                selected = int(input("\nSelect: "))

                if 1 <= selected <= 5:

                    return selected

            except ValueError:

                pass

            print("Invalid selection")

    def choose_input_file(
        self,
        input_dir: Path,
    ) -> Path:
        """
        File picker.
        """

        files = sorted(input_dir.glob("*.xlsx"))

        if not files:

            raise FileNotFoundError(("No Excel files " "found"))

        print()

        print("Detected Files")

        print()

        for index, file in enumerate(
            files,
            1,
        ):

            print(f"{index}. " f"{file.name}")

        while True:

            try:

                choice = int(input("\nSelect: "))

                if 1 <= choice <= len(files):

                    selected = files[choice - 1]

                    self.logger.info(("Selected " f"{selected.name}"))

                    return selected

            except ValueError:

                pass

            print("Invalid choice")

    def confirm(
        self,
        message: str,
    ) -> bool:
        """
        Confirmation input.
        """

        answer = input(f"{message} " "(Y/N): ")

        return answer.strip().upper() == "Y"
