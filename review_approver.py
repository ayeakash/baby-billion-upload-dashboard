"""
review_approver.py — Bulk-approve videos in the CMS **Video Review** dashboard.

Given one or more CMS batch IDs, this logs into the review console (which uses
DIFFERENT credentials from the uploader), selects each batch in the "Batch"
dropdown, and approves every video still in **Pending**.

    # See what WOULD be approved (safe, default):
    python review_approver.py 858de1f6-4bac-4b5c-baec-86f3070dad07

    # Actually approve:
    python review_approver.py --approve 858de1f6-... 21476a7e-...

    # Many ids from a file (one per line, blank lines/# comments ok):
    python review_approver.py --approve --file batch_ids.txt

    # Debug selectors (browser is visible by default):
    python review_approver.py --recon 858de1f6-...

Safety properties
-----------------
* **Dry-run by default.** Nothing is clicked unless you pass ``--approve``.
* **Only 'Pending' videos are touched.** Already-Approved videos are left
  alone and Rejected ones are never flipped.
* Each video is verified to still read "Pending" on its detail panel before
  the Approve button is clicked.

Credentials
-----------
Put the review-console login in ``pipeline/credentials.py`` (gitignored)::

    REVIEW_USERNAME = "..."
    REVIEW_PASSWORD = "..."

Environment variables of the same names also work. If they're absent the
uploader's BB_USERNAME/BB_PASSWORD are NOT used as a fallback, because that
account cannot reach the review page.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))

import config as cfg
import uploader  # reuse build_driver / _safe_quit_driver / lazy selenium import

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger("review_approver")

REVIEW_URL = f"{cfg.ADMIN_BASE_URL}/dashboard/cms/video-review"

PAGE_WAIT = 20      # the review page is slow to first paint
SETTLE = 2.5        # generic pause after a UI interaction
ROW_CAP = 2000      # safety cap on approvals per batch


# ── credentials ───────────────────────────────────────────────────────────────

def review_credentials() -> tuple[str, str]:
    user = getattr(cfg, "REVIEW_USERNAME", "") or os.environ.get("REVIEW_USERNAME", "")
    pw = getattr(cfg, "REVIEW_PASSWORD", "") or os.environ.get("REVIEW_PASSWORD", "")
    if not user or not pw:
        raise SystemExit(
            "Review-console credentials not found.\n"
            "Add to pipeline/credentials.py (gitignored):\n"
            '    REVIEW_USERNAME = "you@example.com"\n'
            '    REVIEW_PASSWORD = "..."\n'
            "(or export them as environment variables)."
        )
    return user, pw


def login_review(driver) -> bool:
    """Log into the CMS with the REVIEW account and land on the review page."""
    _, _, _, By, WebDriverWait, EC, _, _, _ = uploader._get_selenium()
    user, pw = review_credentials()

    driver.get(cfg.ADMIN_LOGIN_URL)
    time.sleep(2)

    if "/login" in driver.current_url:
        try:
            f = WebDriverWait(driver, cfg.SELENIUM_WAIT_SEC).until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "input[type='text'], input[name='username'], input[name='email']",
                ))
            )
            f.clear()
            f.send_keys(user)
            p = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
            p.clear()
            p.send_keys(pw)
            driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        except Exception as e:
            log.error(f"Login form error: {e}")
            return False

        for _ in range(20):
            time.sleep(1)
            if "/login" not in driver.current_url:
                break
        else:
            log.error("Login failed — still on /login. Check REVIEW_USERNAME/REVIEW_PASSWORD.")
            return False

    log.info(f"Logged in as review user. URL: {driver.current_url}")
    return open_review_page(driver)


def open_review_page(driver) -> bool:
    """Navigate to Video Review and wait for the approval table to render."""
    driver.get(REVIEW_URL)
    for _ in range(PAGE_WAIT):
        time.sleep(1)
        ready = driver.execute_script(
            "return (document.body.innerText||'').includes('Approval Queue') "
            "&& document.querySelectorAll('table').length > 0;"
        )
        if ready:
            time.sleep(SETTLE)
            return True
    if "/video-review" not in driver.current_url:
        log.error(f"Redirected away from review page → {driver.current_url}. "
                  f"Does this account have review access?")
    else:
        log.error("Review page did not finish loading (no Approval Queue table).")
    return False


# ── generic DOM helpers ───────────────────────────────────────────────────────

_CLICK_BY_TEXT = r"""
const want = arguments[0].toLowerCase(), exact = arguments[1];
for (const el of document.querySelectorAll('button, a, div[role=option], li, [role=button]')) {
  const t = (el.innerText || '').trim().toLowerCase();
  if (!t) continue;
  if (exact ? t === want : t.includes(want)) { el.click(); return true; }
}
return false;
"""


def click_text(driver, text: str, exact: bool = True) -> bool:
    try:
        return bool(driver.execute_script(_CLICK_BY_TEXT, text, exact))
    except Exception:
        return False


def page_stats(driver) -> str:
    """The footer line: 'N pending · N approved · N rejected · ...'."""
    try:
        return driver.execute_script(
            "const m=(document.body.innerText||'').match(/\\d+ pending[^\\n]*/); return m?m[0]:'';"
        ) or ""
    except Exception:
        return ""


# ── batch selection ───────────────────────────────────────────────────────────

def select_batch(driver, batch_id: str) -> bool:
    """Open the Batch dropdown, search for this id, and pick it."""
    _, _, _, By, _, _, _, _, _ = uploader._get_selenium()

    # Open the combobox. Its label is "All batches ▼" (or the current batch id),
    # so match loosely and click the *smallest* matching element — the button
    # itself rather than a wrapping container.
    opened = driver.execute_script(r"""
      const want = arguments[0];
      let best = null, bestLen = 1e9;
      for (const el of document.querySelectorAll('button, [role=combobox]')) {
        const t = (el.innerText || '').trim();
        if (!t) continue;
        if (t.includes('All batches') || (want && t.includes(want))) {
          if (t.length < bestLen) { best = el; bestLen = t.length; }
        }
      }
      if (best) { best.click(); return true; }
      return false;
    """, batch_id)
    if not opened:
        log.error("  Could not open the Batch dropdown.")
        return False
    time.sleep(1.5)

    # Type the id into the dropdown's search box ("Search batch id…").
    box = None
    for el in driver.find_elements(By.CSS_SELECTOR, "input"):
        ph = (el.get_attribute("placeholder") or "").lower()
        if "batch" in ph and "search" in ph:
            box = el
            break
    if box is None:
        log.error("  Could not find the 'Search batch id…' box.")
        return False
    box.clear()
    box.send_keys(batch_id)
    time.sleep(SETTLE)

    # Click the option whose text is this batch id.
    if not click_text(driver, batch_id, exact=True):
        if not click_text(driver, batch_id[:13], exact=False):
            log.error(f"  Batch {batch_id} not found in the dropdown.")
            return False
    time.sleep(SETTLE + 1)
    return True


def set_pending_filter(driver) -> bool:
    """Click the 'Pending' status chip so only unapproved videos are listed."""
    ok = click_text(driver, "Pending", exact=True)
    time.sleep(SETTLE)
    return ok


# ── row reading ───────────────────────────────────────────────────────────────

_READ_ROWS = r"""
for (const t of document.querySelectorAll('table')) {
  const hd=[...t.querySelectorAll('th')].map(x=>x.innerText.trim().toUpperCase());
  if (!hd.includes('VIDEO ID')) continue;
  const iV=hd.indexOf('VIDEO ID'), iT=hd.indexOf('TITLE'), iS=hd.indexOf('STATUS'), iB=hd.indexOf('BATCH');
  const out=[];
  t.querySelectorAll('tbody tr').forEach(tr=>{
    const c=[...tr.querySelectorAll('td')].map(td=>(td.innerText||'').trim());
    if (!c.length) return;
    out.push({
      batch:  iB>=0 ? c[iB] : '',
      video_id: iV>=0 ? c[iV].replace(/\s+/g,'') : '',
      title:  iT>=0 ? c[iT] : '',
      status: iS>=0 ? c[iS] : '',
    });
  });
  return out;
}
return [];
"""


def read_rows(driver) -> list[dict]:
    try:
        return driver.execute_script(_READ_ROWS) or []
    except Exception as e:
        log.debug(f"  read_rows error: {e}")
        return []


def _next_page(driver) -> bool:
    """Click 'Next' if it exists and isn't disabled. Returns True if we moved."""
    moved = driver.execute_script(r"""
      for (const b of document.querySelectorAll('button')) {
        if ((b.innerText || '').trim().toLowerCase() === 'next') {
          if (b.disabled || b.getAttribute('aria-disabled') === 'true') return false;
          b.click(); return true;
        }
      }
      return false;
    """)
    if moved:
        time.sleep(SETTLE)
    return bool(moved)


def _first_page(driver, max_pages: int = 60) -> None:
    """Walk back to page 1 by clicking 'Prev' until it stops moving."""
    for _ in range(max_pages):
        moved = driver.execute_script(r"""
          for (const b of document.querySelectorAll('button')) {
            if ((b.innerText || '').trim().toLowerCase() === 'prev') {
              if (b.disabled || b.getAttribute('aria-disabled') === 'true') return false;
              b.click(); return true;
            }
          }
          return false;
        """)
        if not moved:
            return
        time.sleep(1)


def read_all_rows(driver, max_pages: int = 60) -> list[dict]:
    """Read every row of the current filter, walking pagination (20/page)."""
    seen: dict[str, dict] = {}
    for _ in range(max_pages):
        for r in read_rows(driver):
            if r.get("video_id"):
                seen[r["video_id"]] = r
        if not _next_page(driver):
            break
    return list(seen.values())


def open_first_pending(driver, batch_id: str) -> str | None:
    """Click into the first Pending row **belonging to this batch**.

    Every row carries its batch id in the BATCH column, so we check it on the
    row itself rather than trusting that the dropdown filter is still applied.
    That makes approving something outside the requested batch impossible.
    """
    return driver.execute_script(r"""
      const target = (arguments[0]||'').replace(/\s+/g,'').toLowerCase();
      for (const t of document.querySelectorAll('table')) {
        const hd=[...t.querySelectorAll('th')].map(x=>x.innerText.trim().toUpperCase());
        if (!hd.includes('VIDEO ID')) continue;
        const iV=hd.indexOf('VIDEO ID'), iS=hd.indexOf('STATUS'), iB=hd.indexOf('BATCH');
        for (const tr of t.querySelectorAll('tbody tr')) {
          const c=[...tr.querySelectorAll('td')];
          if (!c.length) continue;
          const status=(iS>=0 ? c[iS].innerText : '').trim().toLowerCase();
          if (status !== 'pending') continue;
          // Hard guard: the row's own BATCH cell must match the requested batch.
          const rowBatch=(iB>=0 ? c[iB].innerText : '').replace(/\s+/g,'').toLowerCase();
          if (target && rowBatch && rowBatch !== target) continue;
          const vid=(iV>=0 ? c[iV].innerText : '').replace(/\s+/g,'');
          const cell = c[iV] && (c[iV].querySelector('a,button') || c[iV]);
          const viewBtn = [...tr.querySelectorAll('button,a')]
                            .find(b => /^view$/i.test((b.innerText||'').trim()));
          (viewBtn || cell).click();
          // Hand back the row's own batch id so the caller can re-verify it
          // right before approving.
          return {video_id: vid, batch: rowBatch};
        }
      }
      return null;
    """, batch_id)


# ── detail panel ──────────────────────────────────────────────────────────────

def detail_state(driver) -> dict:
    """Read the open video-detail panel: its status + whether Approve is there."""
    return driver.execute_script(r"""
      const body=document.body.innerText||'';
      const hasApprove=[...document.querySelectorAll('button')]
        .some(b=>/^approve$/i.test((b.innerText||'').trim()));
      let status='';
      const m=body.match(/STATUS\s*\n\s*([A-Za-z]+)/);
      if (m) status=m[1];
      return {has_approve:hasApprove, status:status};
    """) or {}


def click_approve(driver) -> bool:
    clicked = driver.execute_script(r"""
      for (const b of document.querySelectorAll('button')) {
        if (/^approve$/i.test((b.innerText||'').trim())) { b.click(); return true; }
      }
      return false;
    """)
    if not clicked:
        return False
    time.sleep(SETTLE)
    # Some UIs raise a confirm dialog — accept anything that looks like one.
    for label in ("Confirm", "Yes", "Approve"):
        if driver.execute_script(r"""
              const w=arguments[0].toLowerCase();
              const dlg=document.querySelector('[role=dialog],.modal');
              if(!dlg) return false;
              for(const b of dlg.querySelectorAll('button')){
                if((b.innerText||'').trim().toLowerCase()===w){b.click();return true;}
              }
              return false;""", label):
            time.sleep(SETTLE)
            break
    return True


def wait_for_detail(driver, timeout: int = 25) -> bool:
    """Wait for the video detail panel (i.e. its Approve button) to render."""
    for _ in range(timeout):
        if driver.execute_script(
            "return [...document.querySelectorAll('button')]"
            ".some(b=>/^approve$/i.test((b.innerText||'').trim()));"
        ):
            return True
        time.sleep(1)
    return False


def list_is_empty(driver) -> bool:
    """True when the queue shows its 'nothing matches' state (0 pending)."""
    try:
        return bool(driver.execute_script(
            "return (document.body.innerText||'').includes('No videos match');"
        ))
    except Exception:
        return False


def wait_for_list(driver, timeout: int = 25) -> bool:
    """Wait for the approval table to come back.

    After an approval the dashboard reloads the list itself — we must NOT
    navigate back, or we lose the batch + Pending filters. Just wait.

    An empty result renders a "No videos match…" panel with no table at all,
    so that counts as loaded too — otherwise every finished batch burns the
    whole timeout.
    """
    for _ in range(timeout):
        state = driver.execute_script(r"""
          if ((document.body.innerText||'').includes('No videos match')) return 'empty';
          for (const t of document.querySelectorAll('table')) {
            const hd=[...t.querySelectorAll('th')].map(x=>x.innerText.trim().toUpperCase());
            if (hd.includes('VIDEO ID')) return 'table';
          }
          return '';
        """)
        if state:
            time.sleep(1)      # let the row statuses settle
            return True
        time.sleep(1)
    return False


def reopen_batch(driver, batch_id: str) -> bool:
    """Recovery: reload the page and re-apply the batch + Pending filters."""
    log.warning("    [RECOVER] list lost — reloading and re-selecting batch")
    if not open_review_page(driver):
        return False
    if not select_batch(driver, batch_id):
        return False
    set_pending_filter(driver)
    return True


# ── per-batch driver ──────────────────────────────────────────────────────────

def approve_batch(driver, batch_id: str, do_approve: bool, limit: int | None = None) -> dict:
    res = {"batch": batch_id, "found": 0, "approved": 0, "skipped": 0, "errors": []}

    if not open_review_page(driver):
        res["errors"].append("review page did not load")
        return res
    if not select_batch(driver, batch_id):
        res["errors"].append("batch not selectable")
        return res

    all_rows = read_all_rows(driver)
    res["found"] = len(all_rows)
    by_status: dict[str, int] = {}
    for r in all_rows:
        by_status[r["status"] or "?"] = by_status.get(r["status"] or "?", 0) + 1
    res["by_status"] = by_status
    log.info(f"  {batch_id[:13]}… → {len(all_rows)} videos {by_status}")

    # The 'Pending' filter is what makes this tractable: each approval refreshes
    # the dashboard and the approved video drops out of the filter, so the list
    # re-flows and we can always just take the first Pending row.
    set_pending_filter(driver)
    pending = [r for r in read_all_rows(driver) if r["status"].lower() == "pending"]
    res["pending"] = len(pending)

    if not do_approve:
        log.info(f"  [DRY-RUN] would approve {len(pending)} pending video(s)")
        res["would_approve"] = [r["video_id"] for r in pending]
        return res

    if res["pending"] == 0:
        log.info("  nothing pending — batch already fully approved")
        return res

    _first_page(driver)   # read_all_rows left us on the last page

    done = 0
    approved_ids: set[str] = set()
    empty_reads, rechecked, stale_clicks = 0, False, 0
    while done < ROW_CAP:
        if limit is not None and done >= limit:
            break
        row = open_first_pending(driver, batch_id)
        vid = (row or {}).get("video_id") or ""
        row_batch = (row or {}).get("batch") or ""
        if not row:
            # Nothing pending *right now*. The list refreshes asynchronously
            # after each approval, so an empty read is usually just a stale
            # render — retrying here is what stops stragglers being left behind.
            if list_is_empty(driver):
                break                  # "No videos match" → nothing left
            if _next_page(driver):
                continue
            if empty_reads < 4:
                empty_reads += 1
                time.sleep(3)
                wait_for_list(driver)
                continue
            if not rechecked:          # one full reload before declaring done
                rechecked = True
                empty_reads = 0
                if reopen_batch(driver, batch_id):
                    continue
            break                      # genuinely no Pending rows left
        empty_reads, rechecked = 0, False

        # The detail panel is slow; poll for it instead of a fixed sleep.
        if not wait_for_detail(driver):
            res["errors"].append(f"{vid}: detail panel never rendered")
            if not wait_for_list(driver) and not reopen_batch(driver, batch_id):
                res["errors"].append("lost the list — stopping this batch")
                break
            continue

        # Verify the batch id ON THE ROW we just opened. If it isn't this
        # batch, never click Approve — bail out rather than touch someone
        # else's video.
        want = batch_id.replace("-", "").replace(" ", "").lower()
        got = row_batch.replace("-", "").replace(" ", "").lower()
        if got and got != want:
            res["errors"].append(f"{vid}: row batch {row_batch} != {batch_id} — NOT approved")
            log.error(f"    ✗ batch mismatch, refusing to approve {vid}")
            break

        # Strict: only approve when the panel itself still says Pending. If the
        # list was stale and we re-opened an already-approved video, skip it.
        st = detail_state(driver)
        if st.get("status", "").lower() != "pending":
            res["skipped"] += 1
            wait_for_list(driver)
            continue

        before = len(approved_ids)
        if click_approve(driver):
            done += 1
            approved_ids.add(vid)
            res["approved"] = len(approved_ids)   # unique videos, not clicks
            if len(approved_ids) > before:
                stale_clicks = 0
                log.info(f"    ✓ approved {len(approved_ids)}: {vid}")
            else:
                # Same video again → the row list is stale, not new work.
                stale_clicks += 1
                if stale_clicks >= 4:
                    if rechecked:
                        log.info("    list keeps re-serving approved rows — batch done")
                        break
                    rechecked, stale_clicks = True, 0
                    if not reopen_batch(driver, batch_id):
                        break
                    continue
        else:
            res["errors"].append(f"{vid}: approve click failed")

        # No navigation here — the dashboard returns to the list on its own.
        if not wait_for_list(driver) and not reopen_batch(driver, batch_id):
            res["errors"].append("lost the list — stopping this batch")
            break

    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Bulk-approve CMS videos by batch id.")
    ap.add_argument("batch_ids", nargs="*", help="CMS batch id(s)")
    ap.add_argument("--file", help="file with one batch id per line")
    ap.add_argument("--approve", action="store_true",
                    help="actually click Approve (default is a dry run)")
    ap.add_argument("--limit", type=int, help="max approvals per batch (testing)")
    ap.add_argument("--headless", action="store_true",
                    help="hide the browser (default: visible so you can watch it work)")
    ap.add_argument("--recon", action="store_true", help="dump page structure and exit")
    args = ap.parse_args()

    ids = list(args.batch_ids)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            for ln in f:
                ln = ln.split("#", 1)[0].strip()   # allow trailing "# comment"
                if ln:
                    ids.append(ln)
    if not ids and not args.recon:
        ap.error("give at least one batch id (or --file)")

    driver = uploader.build_driver(headless=args.headless)
    results = []
    try:
        if not login_review(driver):
            return 1
        log.info(f"Review queue: {page_stats(driver)}")

        if args.recon:
            info = driver.execute_script(r"""
              const t=document.querySelector('table');
              return {
                headers: t?[...t.querySelectorAll('th')].map(x=>x.innerText.trim()):[],
                rows: t?t.querySelectorAll('tbody tr').length:0,
                buttons:[...new Set([...document.querySelectorAll('button')]
                          .map(b=>(b.innerText||'').trim()).filter(Boolean))].slice(0,30),
                inputs:[...document.querySelectorAll('input')].map(i=>i.placeholder||i.type),
              };""")
            print(json.dumps(info, indent=2, ensure_ascii=False))
            return 0

        for i, bid in enumerate(ids, 1):
            log.info(f"[{i}/{len(ids)}] batch {bid}")
            try:
                results.append(approve_batch(driver, bid, args.approve, args.limit))
            except Exception as e:
                log.error(f"  batch {bid} crashed: {e}")
                results.append({"batch": bid, "errors": [str(e)]})

        log.info(f"Review queue after: {page_stats(driver)}")
    finally:
        uploader._safe_quit_driver(driver)

    print("\n" + "=" * 62)
    print("  RESULTS" + ("" if args.approve else "   (DRY RUN — nothing was approved)"))
    print("=" * 62)
    total = 0
    for r in results:
        n = r.get("approved", 0) if args.approve else len(r.get("would_approve", []))
        total += n
        verb = "approved" if args.approve else "to approve"
        print(f"  {r['batch'][:13]}…  {n:>4} {verb}"
              f"   (found {r.get('found', 0)}, pending {r.get('pending', 0)})"
              + (f"  ERRORS: {len(r['errors'])}" if r.get("errors") else ""))
        for e in (r.get("errors") or [])[:5]:
            print(f"       ! {e}")
    print(f"  TOTAL: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
