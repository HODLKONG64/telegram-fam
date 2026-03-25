import hashlib
import os

import requests

from utils import dedupe_items, now_iso, read_json, write_json

STATE_FILE = "bot-state.json"
EXPORT_FILE = "main-brain-export.json"
SOURCES_FILE = "sources.json"


def make_id(item: dict) -> str:
    raw = " | ".join(
        [
            str(item.get("title", "")),
            str(item.get("summary", "")),
            str(item.get("source_url", "")),
            str(item.get("published_at", "")),
        ]
    )
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def fetch_main_brain_export() -> dict:
    export_url = os.environ.get("MAIN_BRAIN_EXPORT_URL", "").strip()
    if not export_url:
        raise RuntimeError("MAIN_BRAIN_EXPORT_URL is not set")

    resp = requests.get(export_url, timeout=60)
    resp.raise_for_status()
    return resp.json()


def normalize_export(raw: dict, sources: list[dict]) -> dict:
    source_map = {s["url"]: s for s in sources}
    out = []

    raw_items = raw.get("items", [])
    for item in raw_items:
        source_url = item.get("source_url") or item.get("url") or ""
        matched = source_map.get(source_url, {})

        clean = {
            "id": item.get("id") or make_id(item),
            "title": item.get("title") or item.get("name") or "Untitled update",
            "summary": item.get("summary") or item.get("description") or item.get("content") or "",
            "source_url": source_url,
            "source_name": item.get("source_name") or matched.get("name") or "Main Brain",
            "wiki_page": item.get("wiki_page") or matched.get("wiki_page") or "GK Brain Updates",
            "category": item.get("category") or matched.get("category") or "general",
            "published_at": item.get("published_at"),
            "updated_at": item.get("updated_at"),
            "detected_at": now_iso(),
        }
        out.append(clean)

    return {"generated_at": now_iso(), "items": dedupe_items(out)}


def merge_state(state: dict, export: dict) -> dict:
    existing = {i["id"]: i for i in state.get("items", [])}
    for item in export.get("items", []):
        if item["id"] not in existing:
            existing[item["id"]] = {
                **item,
                "telegram_done": False,
                "fandom_done": False,
            }
        else:
            existing[item["id"]].update(item)

    state["items"] = list(existing.values())[-4000:]
    state["last_ingest_at"] = now_iso()
    return state


def main() -> None:
    state = read_json(STATE_FILE, {
        "last_ingest_at": None,
        "last_telegram_post_at": None,
        "last_fandom_update_at": None,
        "items": [],
        "posted_to_telegram_ids": [],
        "posted_to_fandom_ids": []
    })
    sources = read_json(SOURCES_FILE, [])

    raw = fetch_main_brain_export()
    export = normalize_export(raw, sources)

    write_json(EXPORT_FILE, export)
    state = merge_state(state, export)
    write_json(STATE_FILE, state)

    print(f"[ingest] pulled {len(export['items'])} items from main brain")


if __name__ == "__main__":
    main()
