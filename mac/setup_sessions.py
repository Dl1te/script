from __future__ import annotations

import sys

import pipeline


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return pipeline.run(do_homework=True)


if __name__ == "__main__":
    raise SystemExit(main())
