#!/usr/bin/env python3
"""Normalize OpenClaw cron job delivery fields to safe stack conventions."""
from __future__ import annotations

import json
from pathlib import Path


CONFIG_ROOT = Path("/config")
JOBS_PATH = CONFIG_ROOT / "cron" / "jobs.json"


def _normalize_delivery(job: dict) -> bool:
    delivery = job.get("delivery")
    if not isinstance(delivery, dict):
        return False

    changed = False
    channel = delivery.get("channel")
    to = delivery.get("to")

    if isinstance(channel, str):
        channel = channel.strip()
        if channel and delivery.get("channel") != channel:
            delivery["channel"] = channel
            changed = True
        if channel.isdigit():
            wanted = f"channel:{channel}"
            if to != wanted:
                delivery["to"] = wanted
                changed = True

    if isinstance(to, str):
        trimmed = to.strip()
        if trimmed != to:
            delivery["to"] = trimmed
            changed = True
            to = trimmed
        if trimmed.isdigit():
            delivery["to"] = f"channel:{trimmed}"
            changed = True

    return changed


def main() -> int:
    if not JOBS_PATH.is_file():
        print(f"normalize_cron_jobs: skipped; {JOBS_PATH} not found")
        return 0

    data = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        print("normalize_cron_jobs: skipped; jobs.json has no jobs list")
        return 0

    changed = False
    normalized = 0
    for job in jobs:
        if isinstance(job, dict) and _normalize_delivery(job):
            changed = True
            normalized += 1

    if changed:
        JOBS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"normalize_cron_jobs: normalized {normalized} job(s)")
    else:
        print("normalize_cron_jobs: no changes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
