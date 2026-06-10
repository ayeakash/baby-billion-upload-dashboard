import json, shutil
from datetime import datetime

src = "state.json"

raw = open(src, encoding="utf-8").read()
lines = raw.splitlines(keepends=True)
print(f"Total lines: {len(lines)}")
print(f"Line 535-540:")
for i in range(534, min(541, len(lines))):
    print(f"  [{i+1}]: {repr(lines[i])}")

# The error is at line 537 col 15 — find the last complete entry BEFORE line 537
# Walk backwards from line 536 to find a line ending with '},'  or '}'
cut_line = 536  # 0-indexed line 536 = line 537 in 1-indexed

# Find the last clean entry boundary (a line that ends an object: ends with },)
for i in range(cut_line, max(0, cut_line - 30), -1):
    stripped = lines[i].rstrip()
    if stripped in ("  },", "  }"):
        print(f"Found clean cut at line {i+1}: {repr(lines[i])}")
        # Reconstruct: everything up to and including this line, then close the root object
        portion = "".join(lines[:i+1])
        # Remove trailing comma if present
        portion = portion.rstrip()
        if portion.endswith(","):
            portion = portion[:-1]
        candidate = portion + "\n}"
        try:
            state = json.loads(candidate)
            print(f"Successfully recovered {len(state)} entries")
            bak = f"state.json.bak_{datetime.now().strftime('%H%M%S')}"
            shutil.copy(src, bak)
            with open(src, "w") as f:
                json.dump(state, f, indent=2)
            print("state.json fixed!")
            counts = {}
            for pid, rec in state.items():
                s = rec.get("pipeline_status", "unknown")
                counts[s] = counts.get(s, 0) + 1
            for s, n in sorted(counts.items()):
                print(f"  {s}: {n}")
        except Exception as e:
            print(f"  Still failed: {e}")
        break
