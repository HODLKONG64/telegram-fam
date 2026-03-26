#!/usr/bin/env python3
"""
reset-delivery-state.py
=======================
Clears only delivery state (telegram + fandom) from shared memory.
All facts, bibles, focus plan, and keywords are preserved.

Usage:
    python reset-delivery-state.py            # reset R2 + local
    python reset-delivery-state.py --dry-run  # preview only
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

DELIVERY_CHANNELS = ("telegram", "fandom")


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


def _load_local() -> dict | None:
    if not os.path.exists(MEMORY_FILE):
        return None
    with open(MEMORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_r2(client) -> dict | None:
    try:
        obj = client.get_object(Bucket=R2_BUCKET, Key=R2_KEY)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception as exc:
        print(f"⚠  Could not load R2 memory: {exc}")
        return None


def _wipe_delivery(memory: dict) -> dict:
    delivery = memory.get("delivery", {})
    if not isinstance(delivery, dict):
        delivery = {}
    for channel in DELIVERY_CHANNELS:
        delivery[channel] = {}
    memory["delivery"] = delivery
    memory["delivery_reset_at"] = datetime.now(timezone.utc).isoformat()
    return memory


def reset(dry_run: bool = False) -> None:
    # ── Local ────────────────────────────────────────────────────────────────
    local_memory = _load_local()
    if local_memory is None:
        print(f"⚠  Local {MEMORY_FILE} not found — skipping local reset")
    else:
        updated = _wipe_delivery(local_memory)
        if dry_run:
            print(f"[DRY RUN] Would wipe delivery keys in local {MEMORY_FILE}: {list(DELIVERY_CHANNELS)}")
        else:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(updated, f, indent=2)
            print(f"✓ Local {MEMORY_FILE}: delivery state cleared for {list(DELIVERY_CHANNELS)}")

    # ── R2 ───────────────────────────────────────────────────────────────────
    client = _r2_client()
    if client is None:
        print("⚠  R2 credentials not set — skipping R2 reset")
        return

    r2_memory = _load_r2(client)
    if r2_memory is None:
        print("⚠  R2 memory could not be loaded — skipping R2 reset")
        return

    updated_r2 = _wipe_delivery(r2_memory)
    payload = json.dumps(updated_r2, indent=2)
    if dry_run:
        print(f"[DRY RUN] Would wipe delivery keys in R2 {R2_BUCKET}/{R2_KEY}: {list(DELIVERY_CHANNELS)}")
    else:
        client.put_object(
            Bucket=R2_BUCKET,
            Key=R2_KEY,
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )
        print(f"✓ R2 {R2_BUCKET}/{R2_KEY}: delivery state cleared for {list(DELIVERY_CHANNELS)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clear delivery state from shared SAM memory")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, make no changes")
    args = parser.parse_args()
    reset(dry_run=args.dry_run)
