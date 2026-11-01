"""Short unified diff of two Markdown files, lines cut to 150 characters (development helper)."""
import difflib, sys
a, b = (open(p).read().splitlines() for p in sys.argv[1:3])
for line in difflib.unified_diff(a, b, n=0, lineterm=""):
    if not line.startswith(("---", "+++")):
        print(line[:150])
