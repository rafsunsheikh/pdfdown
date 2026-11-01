"""Changed spots between two Markdown files, as short before -> after pairs (development helper)."""
import difflib, sys
a, b = (open(p).read() for p in sys.argv[1:3])
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 40
sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
shown = 0
for op, i1, i2, j1, j2 in sm.get_opcodes():
    if op == "equal":
        continue
    print(f"  {a[max(0, i1 - 25):i2 + 10]!r}\n   -> {b[max(0, j1 - 25):j2 + 10]!r}")
    shown += 1
    if shown >= limit:
        break
