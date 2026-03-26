import json
import os
from datetime import datetime, timezone

import boto3
from botocore.config import Config


# -----------------------------
# CONFIG
# -----------------------------
R2_BUCKET = os.environ.get("R2_BUCKET", "sam-memory")
R2_KEY = "sam-memory.json"

R2_ENDPOINT = (os.environ.get("R2_ENDPOINT_URL") or "").strip().rstrip("/") or None
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")


# -----------------------------
# TIME
# -----------------------------
def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# -----------------------------
# R2 CLIENT
# -----------------------------
def _r2():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


# -----------------------------
# MEMORY (PRIMARY SOURCE)
# -----------------------------
def load_memory():
    if R2_ENDPOINT and R2_ACCESS_KEY and R2_SECRET_KEY:
        try:
            r2 = _r2()
            obj = r2.get_object(Bucket=R2_BUCKET, Key=R2_KEY)
            return json.loads(obj["Body"].read().decode("utf-8"))
        except Exception as e:
            print(f"[R2 LOAD FAIL] {e}")

    # fallback local
    if os.path.exists("sam-memory.json"):
        with open("sam-memory.json", "r", encoding="utf-8") as f:
            return json.load(f)

    return {}


def save_memory(data):
    if R2_ENDPOINT and R2_ACCESS_KEY and R2_SECRET_KEY:
        try:
            r2 = _r2()
            r2.put_object(
                Bucket=R2_BUCKET,
                Key=R2_KEY,
                Body=json.dumps(data, indent=2).encode("utf-8"),
                ContentType="application/json",
            )
            print("[R2 SAVE OK]")
            return
        except Exception as e:
            print(f"[R2 SAVE FAIL] {e}")

    # fallback local
    with open("sam-memory.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# -----------------------------
# TELEGRAM DELIVERY LAYER
# -----------------------------
def get_telegram_state(memory):
    return memory.setdefault("delivery", {}).setdefault("telegram", {
        "posted_ids": [],
        "last_post_at": None
    })


def mark_telegram_posted(memory, ids):
    tg = get_telegram_state(memory)

    tg["posted_ids"] = list(set(tg["posted_ids"] + list(ids)))
    tg["last_post_at"] = now_iso()

    return memory


def is_posted(memory, item_id):
    tg = get_telegram_state(memory)
    return item_id in tg["posted_ids"]
