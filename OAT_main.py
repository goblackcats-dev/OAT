import sys
import traceback
from datetime import datetime
from pathlib import Path

from oat.run import main


def _pause():
    try:
        input("\nPress Enter to close this window...")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print("\nStopped:", e.code)
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception:
        tb = traceback.format_exc()
        print("\nSomething went wrong:\n")
        print(tb)
        log = Path("OAT_error_log.txt")
        log.write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S}\n{tb}")
        print(f"(This was also saved to {log.resolve()})")
    _pause()
