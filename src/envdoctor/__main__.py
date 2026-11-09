"""Allow ``python -m envdoctor``."""

import sys

from envdoctor.cli import main

if __name__ == "__main__":
    sys.exit(main())
