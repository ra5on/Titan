"""Track completed copies of an automatic backup plan, in the NAS local time.

Legacy plans start a fresh observation window. A VM-only or partial manual
backup must never make a configured shares/apps plan appear current.
"""
import datetime
import hashlib
import json
import math
import threading
import time


GRACE_SECONDS = 2 * 60 * 60
_lock = threading.RLock()
_key = "backup-freshness"


def revision(settings):
    fields = ("target", "interval", "window_day", "window_hour", "shares", "apps", "app_data", "include_config")
    selected = {name: sorted(settings.get(name, [])) if name in ("shares", "apps", "app_data")
                else settings.get(name) for name in fields}
    return hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _stamp(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def activate(host, settings, now=None, force=False):
    """Persist activation without resetting unchanged plans on every edit/check."""
    now = time.time() if now is None else now
    with _lock:
        state = host.load(_key, {})
        if not settings.get("auto_backup"):
            if state.get("enabled"):
                state["enabled"] = False
                host.save(_key, state)
            return state
        expected = revision(settings)
        if force or state.get("enabled") is not True or state.get("revision") != expected or not _stamp(state.get("activated")):
            state = {"enabled": True, "revision": expected, "activated": now}
            host.save(_key, state)
        return state


def completed(host, settings, kind, details, now=None):
    """Only a verified archive covering the whole current plan satisfies it."""
    if not settings.get("auto_backup") or kind not in ("shares", "bundle"):
        return
    for field in ("shares", "apps", "app_data"):
        if not set(settings.get(field, [])) <= set(details.get(field, [])):
            return
    if settings.get("include_config") and not details.get("include_config"):
        return
    now = time.time() if now is None else now
    with _lock:
        state = activate(host, settings, now)
        state["last_success"] = now
        host.save(_key, state)


def overdue(host, settings, now=None, running=False):
    """Return the latest missed deadline, or None while a plan is current.

Use calendar dates instead of subtracting 24 hours: NAS time zones may have
23-/25-hour days. An older missed deadline stays visible during today's grace.
"""
    now = time.time() if now is None else now
    with _lock:
        state = activate(host, settings, now)
    if not settings.get("auto_backup") or running:
        return None
    date = datetime.datetime.fromtimestamp(now).date()
    for days in range(9):
        candidate = date - datetime.timedelta(days=days)
        if settings.get("interval") == "weekly" and candidate.weekday() != settings.get("window_day", 6):
            continue
        scheduled = datetime.datetime.combine(candidate, datetime.time(hour=settings.get("window_hour", 3))).timestamp()
        if scheduled < state["activated"] or now < scheduled + GRACE_SECONDS:
            continue
        success = state.get("last_success")
        if _stamp(success) and success >= scheduled:
            return None
        return {"scheduled": scheduled, "last_success": success if _stamp(success) else None,
                "grace_seconds": GRACE_SECONDS}
    return None
