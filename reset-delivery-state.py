import json
import os

import boto3
from botocore.config import Config

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "").strip()
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "").strip()

MEMORY_KEY = "shared-memory.json"


def _r2_client():
    endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def reset_delivery_state() -> None:
    if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        raise RuntimeError(
            "Missing required env vars: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME"
        )

    client = _r2_client()
    obj = client.get_object(Bucket=R2_BUCKET_NAME, Key=MEMORY_KEY)
    memory = json.loads(obj["Body"].read().decode("utf-8"))

    if "delivery" not in memory:
        memory["delivery"] = {"telegram": {}, "fandom": {}}
        print("[reset-delivery] 'delivery' key was missing — created fresh.")
    else:
        memory["delivery"]["telegram"] = {}
        memory["delivery"]["fandom"] = {}

    payload = json.dumps(memory, indent=2, ensure_ascii=False).encode("utf-8")
    client.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=MEMORY_KEY,
        Body=payload,
        ContentType="application/json",
    )

    print("[reset-delivery] Wiped delivery.telegram → {}")
    print("[reset-delivery] Wiped delivery.fandom → {}")
    print(f"[reset-delivery] Saved to {R2_BUCKET_NAME}/{MEMORY_KEY}")


if __name__ == "__main__":
    reset_delivery_state()
