#!/usr/bin/env python3
"""
reset-delivery-state.py
=======================
Wipes delivery.telegram and delivery.fandom from shared R2 memory.
Use this after a full memory reset or when you want a clean delivery slate
without wiping all brain facts.

Usage:
    python reset-delivery-state.py              # wipe R2 + local
    python reset-delivery-state.py --dry-run    # preview only
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


def _load_from_r2(client) -> dict:
    try:
        obj = client.get_object(Bucket=R2_BUCKET, Key=R2_KEY)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception as exc:
        print(f"⚠  Could not load R2 memory: {exc}")
        return {}


def _load_local() -> dict:
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def reset_delivery(dry_run: bool = False) -> None:
    client = _r2_client()

    # Load from R2 if available, else local
    if client:
        memory = _load_from_r2(client)
        source = "R2"
    else:
        memory = _load_local()
        source = "local"

    if not memory:
        print("⚠  No memory found — nothing to reset")
        return

    print(f"Loaded memory from {source}")

    # Wipe delivery keys
    delivery = memory.get("delivery", {})
    before_telegram = len(delivery.get("telegram", {}))
    before_fandom = len(delivery.get("fandom", {}))

    if dry_run:
        print(f"[DRY RUN] Would wipe delivery.telegram ({before_telegram} entries)")
        print(f"[DRY RUN] Would wipe delivery.fandom ({before_fandom} entries)")
        return

    memory.setdefault("delivery", {})
    memory["delivery"]["telegram"] = {}
    memory["delivery"]["fandom"] = {}
    memory["delivery_reset_at"] = datetime.now(timezone.utc).isoformat()

    payload = json.dumps(memory, indent=2)

    # Write back to R2
    if client:
        client.put_object(
            Bucket=R2_BUCKET,
            Key=R2_KEY,
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )
        print(f"✓ R2 delivery state wiped (telegram: {before_telegram} → 0, fandom: {before_fandom} → 0)")

    # Write back to local
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(payload)
    print(f"✓ Local {MEMORY_FILE} delivery state wiped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset delivery state in shared SAM memory")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, make no changes")
    args = parser.parse_args()
    reset_delivery(dry_run=args.dry_run)
