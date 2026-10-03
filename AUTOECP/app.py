#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STAR Cyclic EXP Scheduler
-------------------------
• Har account ka apna "+4000 EXP per cycle" target hai
• Target hit → PAUSE
• Roz 4:00 AM IST → RESUME (target auto +4000 badh jata hai)
• State JSON file me save — restart pe bhi safe
Server: de26.spaceify.eu:26020
"""

import requests
import time
import sys
import json
import os
from datetime import datetime, time as dtime

# India timezone
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")


# ============================================
# ⚙️  CONFIGURATION
# ============================================
BASE_URL         = "http://de26.spaceify.eu:26020"
CYCLE_EXP_GAIN   = 4000              # Har cycle me kitna EXP gain karna hai
POLL_INTERVAL    = 3                 # seconds
TIMEOUT          = 10
RESUME_HOUR      = 4                 # 4 AM IST
RESUME_MINUTE    = 0
STATE_FILE       = "scheduler_state.json"


# ============================================
# 🎨  COLORS
# ============================================
class C:
    R='\033[91m'; G='\033[92m'; Y='\033[93m'; B='\033[94m'
    CY='\033[96m'; M='\033[95m'; W='\033[97m'
    BOLD='\033[1m'; END='\033[0m'

def ts():
    return datetime.now(IST).strftime("%H:%M:%S")

def log(msg, color=C.W):
    print(f"{C.B}[{ts()} IST]{C.END} {color}{msg}{C.END}")

def log_ok(m):    log(f"✔ {m}", C.G)
def log_err(m):   log(f"✖ {m}", C.R)
def log_warn(m):  log(f"⚠ {m}", C.Y)
def log_info(m):  log(f"➜ {m}", C.CY)


# ============================================
# 💾  STATE MANAGEMENT  (persist between restarts)
# ============================================
def load_state():
    """state = { uid: {"next_target": 11000, "last_exp": 7000} }"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            log_err(f"State load failed: {e}")
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log_err(f"State save failed: {e}")


# ============================================
# 🚀  BANNER
# ============================================
def banner():
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"""{C.M}{C.BOLD}
╔══════════════════════════════════════════════════════════╗
║     STAR CYCLIC EXP SCHEDULER  (+{CYCLE_EXP_GAIN} per cycle)          ║
╠══════════════════════════════════════════════════════════╣
║  Server      : de26.spaceify.eu:26020                    ║
║  Cycle Gain  : +{CYCLE_EXP_GAIN} EXP                                    ║
║  Resume Time : {RESUME_HOUR:02d}:{RESUME_MINUTE:02d} AM IST daily (auto target bump)     ║
║  State File  : {STATE_FILE:<40}             ║
║  Now (IST)   : {now_ist}                  ║
╚══════════════════════════════════════════════════════════╝
{C.END}""")


# ============================================
# 📡  API HELPERS
# ============================================
def fetch_stats():
    try:
        r = requests.get(f"{BASE_URL.rstrip('/')}/api/stats", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError as e:
        log_err(f"Connection error: {e}")
    except requests.exceptions.Timeout:
        log_err(f"Timeout ({TIMEOUT}s)")
    except Exception as e:
        log_err(f"Fetch failed: {e}")
    return None


def pause_account(uid):
    try:
        r = requests.post(
            f"{BASE_URL.rstrip('/')}/api/account/pause",
            json={"uid": str(uid)},
            timeout=TIMEOUT,
        )
        data = r.json()
        if data.get("status") == "ok":
            return data.get("is_paused")
        log_err(f"Pause failed for {uid}: {data.get('error')}")
    except Exception as e:
        log_err(f"Pause error for {uid}: {e}")
    return None


def resume_all():
    """Toggle pause_all — since all are paused, this resumes them all."""
    try:
        r = requests.post(
            f"{BASE_URL.rstrip('/')}/api/account/pause_all",
            timeout=TIMEOUT,
        )
        data = r.json()
        if data.get("status") == "ok":
            return data.get("all_paused")     # False = resumed
        log_err(f"Resume-all failed: {data.get('error')}")
    except Exception as e:
        log_err(f"Resume-all error: {e}")
    return None


# ============================================
# 🕒  4 AM IST SCHEDULER
# ============================================
last_resume_date = None

def is_time_to_resume():
    global last_resume_date
    now = datetime.now(IST)
    today = now.date()
    if last_resume_date == today:
        return False
    if now.time() >= dtime(RESUME_HOUR, RESUME_MINUTE):
        last_resume_date = today
        return True
    return False


# ============================================
# 🧠  MAIN LOOP
# ============================================
def main():
    banner()
    log_info(f"Monitoring → {BASE_URL}")
    log_info(f"Har cycle: +{CYCLE_EXP_GAIN} EXP gain hone pe pause")
    log_info(f"Resume: {RESUME_HOUR:02d}:{RESUME_MINUTE:02d} AM IST daily")
    print("-" * 60)

    state = load_state()
    if state:
        log_ok(f"Loaded saved state for {len(state)} account(s)")

    # Connectivity test
    if fetch_stats() is None:
        log_warn("Initial connect failed — will keep retrying...")
    else:
        log_ok("Connection OK. Scheduler live.")
    print("-" * 60)

    poll_count = 0
    total_paused = 0
    resume_cycles = 0

    while True:
        # ── 1. 4 AM IST trigger → resume all + bump targets ──
        if is_time_to_resume():
            now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            log_warn(f"⏰ 4 AM IST REACHED ({now_str}) → Resuming ALL accounts...")

            # Bump every target BEFORE resume
            for uid, st in state.items():
                old_target = st.get("next_target", 0)
                st["next_target"] = old_target + CYCLE_EXP_GAIN
                log_info(
                    f"UID {uid}: new target = {old_target:,} + {CYCLE_EXP_GAIN:,} "
                    f"= {st['next_target']:,}"
                )
            save_state(state)

            result = resume_all()
            if result is False:
                log_ok("✔ All accounts RESUMED. New cycle started.")
                resume_cycles += 1
            elif result is True:
                log_warn("pause_all returned all_paused=True (nothing to resume?)")
            else:
                log_err("Resume call returned no valid state.")

        # ── 2. Poll stats ──
        poll_count += 1
        data = fetch_stats()

        if data:
            accounts = data.get("accounts", [])
            log(f"Poll #{poll_count} — {len(accounts)} account(s)", C.B)

            for acc in accounts:
                uid       = str(acc.get("uid", "?"))
                nick      = acc.get("nickname", "Unknown")
                cur_exp   = int(acc.get("current_exp", 0) or 0)
                level     = acc.get("level", "?")
                is_paused = bool(acc.get("is_paused") or acc.get("status") == "PAUSED")

                # First time seeing this account → set its target
                if uid not in state:
                    state[uid] = {
                        "next_target": cur_exp + CYCLE_EXP_GAIN,
                        "last_exp": cur_exp,
                    }
                    save_state(state)
                    log_info(
                        f"NEW {nick} (UID {uid}) L{level} | {cur_exp:,} EXP "
                        f"→ target set to {state[uid]['next_target']:,}"
                    )

                target = state[uid]["next_target"]
                state[uid]["last_exp"] = cur_exp

                # ── Hit target & not paused → PAUSE ──
                if cur_exp >= target and not is_paused:
                    log_warn(
                        f"🎯 HIT! {nick} (UID {uid}) L{level} | "
                        f"{cur_exp:,} EXP >= {target:,} → PAUSING..."
                    )
                    st = pause_account(uid)
                    if st is True:
                        log_ok(f"PAUSED {nick} @ {cur_exp:,} EXP")
                        total_paused += 1
                        # bump target for NEXT cycle (ready when 4 AM resumes)
                        state[uid]["next_target"] = target + CYCLE_EXP_GAIN
                        save_state(state)
                        log_info(
                            f"Next target for {nick} → "
                            f"{state[uid]['next_target']:,} (after 4 AM resume)"
                        )
                elif is_paused:
                    log_info(
                        f"{nick} (L{level}) | {cur_exp:,} EXP | ⏸ PAUSED "
                        f"(resume at 4 AM → next target {target:,})"
                    )
                else:
                    remaining = target - cur_exp
                    log_info(
                        f"{nick} (L{level}) | {cur_exp:,} / {target:,} EXP | "
                        f"{remaining:,} left to pause"
                    )

            save_state(state)
            log(
                f"Session — Paused: {total_paused} | Resume-cycles: {resume_cycles}",
                C.G,
            )
        else:
            log_warn(f"Fetch failed (poll #{poll_count})")

        print("-" * 60)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.Y}Stopped. State saved to {STATE_FILE}. Bye!{C.END}")
        sys.exit(0)