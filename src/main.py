from __future__ import annotations

from pipeline import configure_logging
from ui import run_ui


def main() -> None:
    configure_logging()
    run_ui()


if __name__ == "__main__":
    main()

