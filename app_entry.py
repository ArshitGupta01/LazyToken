"""Entry point for the optional self-contained Windows build."""

import sys
import kn

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("--help")
    kn.main()
