import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

import boto3
from botocore.config import Config
import mwclient
import requests


R2_BUCKET = os.environ.get("R2_BUCKET", "sam-memory")
R2_KEY = os.environ.get("R2_KEY", "sam-memory.json")
R2_ENDPOINT = (os.environ.get("R2_ENDPOINT_URL") or "").strip().rstrip("/") or None
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")


def _r2_enabled() -> bool:
    return all([R2_ENDPOINT, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET])


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def read_text(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return default


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def append_text(path: str, content: str) -> None:
    current = read_text(path, "")
    write_text(path, current + content)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def build_ref(url: str, label: str | None = None) -> str:
    safe_url = str(url).strip()
    safe_label = str(label or safe_url).strip()
    return f"<ref>[{safe_url} {safe_label}], accessed {today_utc()}</ref>"


def short_history_append(path: str, title: str, body: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = f"\n\n---\n## {stamp} — {title}\n\n{body.strip()}\n"
    combined = (read_text(path, "") + block)[-50000:]
    write_text(path, combined)


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        uid = item.get("id")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        out.append(item)
    return out


# -----------------------------
# SHARED SAM MEMORY (R2 FIRST)
# -----------------------------
def _empty_memory() -> dict:
    return {
        "last_update": "",
        "cycle_count": 0,
        "facts": {
            "characters": {},
            "real_people": {},
            "factions": {},
            "armies": {},
            "lore_locations": {},
            "mechanics": {},
            "tokens": {},
            "games": {},
            "events": {},
            "brands": {},
        },
        "external_facts": {
            "CONFIRMED": {},
            "UNVERIFIED": {},
            "rejected_count": 0,
        },
        "web_discovered": {
            "WEB_CONFIRMED": {},
            "WEB_UNVERIFIED": {},
        },
        "keyword_bank": {},
        "bibles": {},
        "latest_focus_plan": {},
        "delivery": {
            "telegram": {
                "posted_ids": [],
                "last_post_at": None,
                "latest_lore": {},
            },
            "fandom": {
                "posted_ids": [],
                "last_post_at": None,
            },
        },
    }


def load_memory() -> dict:
    empty = _empty_memory()

    if _r2_enabled():
        try:
            client = _r2_client()
            obj = client.get_object(Bucket=R2_BUCKET, Key=R2_KEY)
            memory = json.loads(obj["Body"].read().decode("utf-8"))
            for key, val in empty.items():
                if key not in memory:
                    memory[key] = val
                elif isinstance(val, dict):
                    for sub_key, sub_val in val.items():
                        if sub_key not in memory[key]:
                            memory[key][sub_key] = sub_val
                        elif isinstance(sub_val, dict):
                            for sub_sub_key, sub_sub_val in sub_val.items():
                                if sub_sub_key not in memory[key][sub_key]:
                                    memory[key][sub_key][sub_sub_key] = sub_sub_val
            return memory
        except Exception as exc:
            print(f"[utils] R2 load failed: {exc}")

    if os.path.exists("sam-memory.json"):
        try:
            with open("sam-memory.json", "r", encoding="utf-8") as fh:
                memory = json.load(fh)
            for key, val in empty.items():
                if key not in memory:
                    memory[key] = val
            return memory
        except Exception:
            pass

    return empty


def save_memory(memory: dict) -> None:
    payload = json.dumps(memory, indent=2, ensure_ascii=False).encode("utf-8")

    if _r2_enabled():
        try:
            client = _r2_client()
            client.put_object(
                Bucket=R2_BUCKET,
                Key=R2_KEY,
                Body=payload,
                ContentType="application/json",
            )
        except Exception as exc:
            print(f"[utils] R2 save failed: {exc}")

    with open("sam-memory.json", "wb") as fh:
        fh.write(payload)


def get_delivery_state(memory: dict, channel: str) -> dict:
    delivery = memory.setdefault("delivery", {})
    if channel == "telegram":
        return delivery.setdefault("telegram", {
            "posted_ids": [],
            "last_post_at": None,
            "latest_lore": {},
        })
    if channel == "fandom":
        return delivery.setdefault("fandom", {
            "posted_ids": [],
            "last_post_at": None,
        })
    return delivery.setdefault(channel, {})


def is_delivered(memory: dict, channel: str, item_id: str) -> bool:
    state = get_delivery_state(memory, channel)
    return item_id in state.get("posted_ids", [])


def mark_delivered(memory: dict, channel: str, item_ids: list[str]) -> dict:
    state = get_delivery_state(memory, channel)
    merged = list(set(state.get("posted_ids", []) + list(item_ids)))
    state["posted_ids"] = merged[-8000:]
    state["last_post_at"] = now_iso()
    return memory


def save_latest_lore_to_memory(
    memory: dict,
    title: str,
    part1: str,
    part2: str,
    notes: str,
    used_items: list[dict],
) -> dict:
    state = get_delivery_state(memory, "telegram")
    state["latest_lore"] = {
        "title": title,
        "part1": part1,
        "part2": part2,
        "notes": notes,
        "generated_at": now_iso(),
        "used_item_ids": [i["id"] for i in used_items],
        "used_item_titles": [i.get("title", "") for i in used_items],
    }
    return memory


def get_latest_lore_from_memory(memory: dict) -> dict:
    state = get_delivery_state(memory, "telegram")
    return state.get("latest_lore", {}) or {}


# -----------------------------
# EXISTING FANDOM / TELEGRAM HELPERS
# -----------------------------
def fandom_connect():
    wiki_url = os.environ.get("FANDOM_WIKI_URL", "").strip()
    user = os.environ.get("FANDOM_BOT_USER", "").strip()
    password = os.environ.get("FANDOM_BOT_PASSWORD", "").strip()

    if not wiki_url or not user or not password:
        raise RuntimeError("Missing FANDOM_WIKI_URL, FANDOM_BOT_USER, or FANDOM_BOT_PASSWORD")

    parsed = urlparse(wiki_url)
    host = parsed.netloc
    path = parsed.path.strip("/")

    site = mwclient.Site(host, path="/" if not path else f"/{path}/", scheme="https")
    site.login(user, password)
    return site


def fandom_get_page_text(site, title: str) -> str:
    page = site.pages[title]
    try:
        return page.text()
    except Exception:
        return ""


def fandom_save_page(site, title: str, content: str, summary: str) -> None:
    page = site.pages[title]
    page.save(content, summary=summary)


def ensure_heading(text: str, heading: str) -> str:
    marker = f"== {heading} =="
    if marker in text:
        return text
    return text.rstrip() + f"\n\n{marker}\n\n"


def has_marker(text: str, uid: str) -> bool:
    return f"<!-- GK-TF-BOT:{uid} -->" in text


def build_update_block(item: dict) -> str:
    uid = item["id"]
    date = item.get("published_at") or item.get("updated_at") or item.get("detected_at") or today_utc()
    date = str(date)[:10]
    title = item.get("title") or "Untitled update"
    summary = normalize_text(item.get("summary") or item.get("description") or "")
    source_url = item.get("source_url") or item.get("url") or ""
    source_name = item.get("source_name") or domain_of(source_url) or "Source"
    ref = build_ref(source_url, source_name) if source_url else ""
    return (
        f"<!-- GK-TF-BOT:{uid} -->\n"
        f"* {date} — '''{title}''': {summary} {ref}"
    ).strip()


def append_under_latest_updates(text: str, block: str) -> str:
    marker = "== Latest Updates =="
    text = ensure_heading(text, "Latest Updates")
    pos = text.find(marker)
    if pos == -1:
        return text.rstrip() + "\n\n" + block + "\n"
    insert_at = pos + len(marker)
    return text[:insert_at] + "\n\n" + block + text[insert_at:]


def build_recovery_page(page_title: str, items: list[dict]) -> str:
    overview_parts = []
    sources = []

    for item in items[:5]:
        title = item.get("title") or "Update"
        summary = normalize_text(item.get("summary") or item.get("description") or "")
        if summary:
            overview_parts.append(f"{title}: {summary}")
        src = item.get("source_url") or item.get("url")
        if src:
            sources.append(src)

    overview = " ".join(overview_parts)[:1400].strip()
    if not overview:
        overview = f"{page_title} is being rebuilt from approved source data."

    unique_sources = []
    seen = set()
    for src in sources:
        if src in seen:
            continue
        seen.add(src)
        unique_sources.append(src)

    source_lines = "\n".join(f"* [{src} {domain_of(src) or src}]" for src in unique_sources)
    latest_blocks = "\n".join(build_update_block(i) for i in items)

    return f"""= {page_title} =

== Overview ==

{overview}

== Details ==

This page was rebuilt automatically because it was empty or near-empty. It is populated only from approved source data from the main brain pipeline.

== Latest Updates ==

{latest_blocks}

== Sources ==

{source_lines}
""".strip() + "\n"


def telegram_send_message(bot_token: str, chat_id: str, text: str) -> dict:
    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4096]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def group_by_page(items: list[dict]) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for item in items:
        page = item.get("wiki_page") or "GK Brain Updates"
        grouped[page].append(item)
    return dict(grouped)
