#!/usr/bin/env python3
"""
reset-delivery-state.py
=======================
Wipes delivery.telegram and delivery.fandom from shared R2 memory.
Does NOT touch facts, bibles, keywords, or the focus plan.
Use this after resetting shared memory so telegram-arm starts fresh
without assuming any entities have already been delivered.

Usage:
    python reset-delivery-state.py           # reset R2 + local
    python reset-delivery-state.py --dry-run # preview only
"""

import argparse
import json
import os
from datetime import datetime, timezone

import boto3
from botocore.config import Config

MEMORY_FILE = "sam-memory.json"
R2_BUCKET = os.environ.get("R2_BUCKET", "sam-memory")
R2_KEY = "sam-memory.json"
R2_ENDPOINT = (os.environ.get("R2_ENDPOINT_URL") or "").strip().rstrip("/") or None
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")


def _r2_client():
    if not (R2_ENDPOINT and R2_ACCESS_KEY and R2_SECRET_KEY):
        return None
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _load_r2(client) -> dict:
    try:
        resp = client.get_object(Bucket=R2_BUCKET, Key=R2_KEY)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as exc:
        print(f"⚠  Could not load R2 memory: {exc}")
        return {}


def _save_r2(client, memory: dict, dry_run: bool) -> None:
    payload = json.dumps(memory, indent=2)
    if dry_run:
        print(f"[DRY RUN] Would write updated memory to R2 {R2_BUCKET}/{R2_KEY}")
        return
    client.put_object(
        Bucket=R2_BUCKET,
        Key=R2_KEY,
        Body=payload.encode("utf-8"),
        ContentType="application/json",
    )
    print(f"✓ R2 delivery state reset in {R2_BUCKET}/{R2_KEY}")


def _reset_delivery(memory: dict) -> dict:
    """Set delivery.telegram and delivery.fandom to empty dicts."""
    if "delivery" not in memory or not isinstance(memory["delivery"], dict):
        memory["delivery"] = {}
    memory["delivery"]["telegram"] = {}
    memory["delivery"]["fandom"] = {}
    memory["last_update"] = datetime.now(timezone.utc).isoformat()
    return memory


def reset(dry_run: bool = False) -> None:
    client = _r2_client()

    # ── R2 ───────────────────────────────────────────────────────────────────
    if client:
        memory = _load_r2(client)
        if memory:
            memory = _reset_delivery(memory)
            _save_r2(client, memory, dry_run)
        else:
            print("⚠  R2 memory empty or unreadable — skipping R2 delivery reset")
    else:
        print("⚠  R2 credentials not set — skipping R2 reset")

    # ── Local file ───────────────────────────────────────────────────────────
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                local = json.load(f)
            local = _reset_delivery(local)
            if dry_run:
                print(f"[DRY RUN] Would reset delivery state in local {MEMORY_FILE}")
            else:
                with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                    json.dump(local, f, indent=2)
                print(f"✓ Local {MEMORY_FILE} delivery state reset")
        except Exception as exc:
            print(f"⚠  Could not update local {MEMORY_FILE}: {exc}")
    else:
        print(f"⚠  No local {MEMORY_FILE} found — skipping local reset")

    print("reset-delivery-state: done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset delivery.telegram and delivery.fandom in shared memory")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, make no writes")
    args = parser.parse_args()
    reset(dry_run=args.dry_run)
