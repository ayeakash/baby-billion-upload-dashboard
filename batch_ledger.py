"""
batch_ledger.py — A durable record of every uploaded batch and its CMS id.

`batches.json` is working state: batches get pruned from it when files are
deleted or cleared, so the CMS batch ids that came back from an upload can be
lost. This keeps a permanent, append-only ledger (`batch_ledger.csv`) built
from both `batches.json` and the append-only `upload_history.jsonl`.

    python batch_ledger.py sync                 # record anything new
    python batch_ledger.py list                 # show the whole ledger
    python batch_ledger.py list --date 2026-08-20
    python batch_ledger.py list --channel mikkutales
    python batch_ledger.py ids --date 2026-08-20 -o today_batch_ids.txt

The `ids` command writes exactly the format `review_approver.py --file` wants,
so approving a day's uploads is:

    python batch_ledger.py ids --date 2026-08-20 -o ids.txt
    python review_approver.py --approve --file ids.txt
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

LEDGER = os.path.join(BASE_DIR, "batch_ledger.csv")
BATCHES_JSON = os.path.join(BASE_DIR, "batches.json")
HISTORY = os.path.join(BASE_DIR, "upload_history.jsonl")

FIELDS = ["upload_date", "batch_name", "cms_batch_id", "video_count",
          "channel", "source", "status"]

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def load_ledger() -> dict[str, dict]:
    """Existing rows, keyed by batch_name."""
    rows: dict[str, dict] = {}
    if os.path.isfile(LEDGER):
        with open(LEDGER, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("batch_name"):
                    rows[r["batch_name"]] = r
    return rows


def save_ledger(rows: dict[str, dict]) -> None:
    ordered = sorted(rows.values(),
                     key=lambda r: (r.get("upload_date") or "", r.get("batch_name") or ""))
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in ordered:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    os.replace(tmp, LEDGER)


def _from_batches_json() -> list[dict]:
    if not os.path.isfile(BATCHES_JSON):
        return []
    try:
        data = json.load(open(BATCHES_JSON, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for name, b in data.items():
        vids = b.get("videos", []) or []
        out.append({
            "upload_date": b.get("upload_date") or "",
            "batch_name": name,
            "cms_batch_id": (b.get("upload_job_id") or "").strip(),
            "video_count": str(b.get("video_count") or len(vids)),
            "channel": (vids[0].get("channel") if vids else "") or "",
            "source": b.get("source", ""),
            "status": b.get("status", ""),
        })
    return out


def _from_history() -> list[dict]:
    """Recover batches that batches.json no longer knows about."""
    if not os.path.isfile(HISTORY):
        return []
    agg: dict[tuple, dict] = {}
    with open(HISTORY, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            bn, job = rec.get("batch_name", ""), (rec.get("job_id") or "").strip()
            if not bn:
                continue
            key = (bn, job)
            e = agg.setdefault(key, {
                "upload_date": (rec.get("timestamp") or "")[:10],
                "batch_name": bn,
                "cms_batch_id": job,
                "video_count": 0,
                "channel": rec.get("channel", ""),
                "source": rec.get("source", ""),
                "status": rec.get("status", ""),
            })
            e["video_count"] += 1
    for e in agg.values():
        e["video_count"] = str(e["video_count"])
    return list(agg.values())


def cmd_sync(_args) -> int:
    rows = load_ledger()
    before = len(rows)
    updated = 0
    for rec in _from_history() + _from_batches_json():   # batches.json wins
        name = rec["batch_name"]
        cur = rows.get(name)
        if cur is None:
            rows[name] = rec
        else:
            # Fill blanks / refresh; never blank out a known CMS id.
            for k, v in rec.items():
                if v and v != cur.get(k):
                    if k == "cms_batch_id" and cur.get(k) and not UUID_RE.match(v):
                        continue
                    cur[k] = v
                    updated += 1
    save_ledger(rows)
    print(f"ledger: {len(rows)} batches ({len(rows) - before} new, {updated} fields updated)")
    print(f"        {LEDGER}")
    return 0


def _select(args) -> list[dict]:
    rows = list(load_ledger().values())
    if getattr(args, "date", None):
        rows = [r for r in rows if (r.get("upload_date") or "").startswith(args.date)]
    if getattr(args, "channel", None):
        rows = [r for r in rows if args.channel.lower() in (r.get("channel") or "").lower()]
    if getattr(args, "batch", None):
        rows = [r for r in rows if args.batch.lower() in (r.get("batch_name") or "").lower()]
    return sorted(rows, key=lambda r: (r.get("upload_date") or "", r.get("batch_name") or ""))


def cmd_list(args) -> int:
    rows = _select(args)
    if not rows:
        print("no matching batches")
        return 0
    total = 0
    print(f"{'DATE':<12}{'BATCH':<20}{'VIDEOS':>7}  {'CHANNEL':<22}CMS BATCH ID")
    print("-" * 100)
    for r in rows:
        n = int(r.get("video_count") or 0)
        total += n
        print(f"{r.get('upload_date',''):<12}{r.get('batch_name',''):<20}{n:>7}  "
              f"{(r.get('channel') or '')[:20]:<22}{r.get('cms_batch_id','') or '(none)'}")
    print("-" * 100)
    print(f"{len(rows)} batches, {total} videos")
    return 0


def cmd_ids(args) -> int:
    rows = [r for r in _select(args) if UUID_RE.match((r.get("cms_batch_id") or "").strip())]
    skipped = [r for r in _select(args) if not UUID_RE.match((r.get("cms_batch_id") or "").strip())]
    lines = [f"# {len(rows)} batches"
             + (f" uploaded {args.date}" if args.date else "")
             + f", {sum(int(r.get('video_count') or 0) for r in rows)} videos"]
    for r in rows:
        lines.append(f"{r['cms_batch_id']}   # {r['batch_name']} ({r.get('video_count')} videos)")
    text = "\n".join(lines) + "\n"
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
        print(f"wrote {len(rows)} batch id(s) → {args.out}")
    else:
        print(text, end="")
    if skipped:
        print(f"note: {len(skipped)} batch(es) have no CMS id and were left out "
              f"(e.g. {', '.join(r['batch_name'] for r in skipped[:3])})", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Durable ledger of uploaded batches + CMS ids.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync", help="record new batches from batches.json + upload_history.jsonl")

    for name, help_ in (("list", "show ledger rows"), ("ids", "print/write CMS ids only")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--date", help="filter by upload date, e.g. 2026-08-20")
        p.add_argument("--channel", help="filter by channel substring")
        p.add_argument("--batch", help="filter by batch-name substring, e.g. Batch_LWF")
        if name == "ids":
            p.add_argument("-o", "--out", help="write to this file (for review_approver --file)")

    args = ap.parse_args()
    return {"sync": cmd_sync, "list": cmd_list, "ids": cmd_ids}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
