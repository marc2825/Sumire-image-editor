"""PyInstaller entry point (absolute imports work inside a frozen executable)."""
from sumire.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())

