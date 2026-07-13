"""CLI entry point for the Turnstile solver API."""

import sys

from src.main import run_api, run_dev


def main() -> None:
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "api":
            run_api()
            return
        if command == "dev":
            run_dev()
            return
        print(f"Unknown command: {command}")
        print("Usage: python main.py [api|dev]")
        sys.exit(1)

    print("Turnstile Solver API")
    print()
    print("Usage:")
    print("  python main.py api   - Run API server")
    print("  python main.py dev   - Run API in dev mode (reload)")


if __name__ == "__main__":
    main()
