import os
from datetime import datetime, timezone

from utils import (
    get_latest_lore_from_memory,
    is_delivered,
    load_memory,
    mark_delivered,
    normalize_text,
    save_latest_lore_to_memory,
    save_memory,
    telegram_send_message,
    write_json,
)

LATEST_LORE_FILE = "latest-lore.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fact_text(fact) -> str:
    if isinstance(fact, dict):
        return normalize_text(fact.get("fact", ""))
    return normalize_text(fact)


def _build_item(category: str, name: str, data: dict) -> dict:
    source_urls = list(dict.fromkeys(data.get("source_urls", [])))[:3]
    facts = [_fact_text(f) for f in data.get("all_facts", [])]
    facts = [f for f in facts if f][:4]

    summary = normalize_text(
        data.get("lore_details")
        or data.get("role_description")
        or (facts[0] if facts else "")
        or f"{name} is active inside the SAM memory graph."
    )

    return {
        "id": f"{category}:{name}",
        "entity_name": name,
        "title": name,
        "category": category,
        "summary": summary,
        "facts": facts,
        "source_urls": source_urls,
        "mention_count": int(data.get("mention_count", 0)),
        "faction_allegiance": data.get("faction_allegiance", ""),
        "type": data.get("type", category),
        "wiki_page": f"wiki/{name.lower().replace(' ', '-').replace('_', '-')}.html",
        "detected_at": now_iso(),
    }


def build_items_from_memory(memory: dict) -> list[dict]:
    items = []
    for category, entities in memory.get("facts", {}).items():
        if not isinstance(entities, dict):
            continue
        for name, data in entities.items():
            if not isinstance(data, dict):
                continue
            items.append(_build_item(category, name, data))

    items.sort(
        key=lambda x: (x.get("mention_count", 0), len(x.get("summary", ""))),
        reverse=True,
    )
    return items


def pick_items(memory: dict, limit: int = 3) -> list[dict]:
    items = build_items_from_memory(memory)
    selected = []

    for item in items:
        if is_delivered(memory, "telegram", item["id"]):
            continue
        selected.append(item)
        if len(selected) >= limit:
            break

    if not selected:
        selected = items[:limit]

    return selected


def compose_lore(items: list[dict]) -> tuple[str, str, str, str]:
    if not items:
        title = "SAM Memory Pulse"
        part1 = "The shared SAM memory is live, but no fresh entity slice was available for Telegram this cycle."
        part2 = "The delivery layer is now wired to the real entity graph instead of the old export pipeline."
        notes = "No entity items were available."
        return title, part1, part2, notes

    lead = items[0]
    title = f"SAM SIGNAL: {lead['title']}"

    intro_lines = []
    detail_lines = []
    note_lines = []

    for item in items:
        intro_lines.append(
            f"{item['title']} is active in the shared SAM memory under {item['category'].replace('_', ' ')}."
        )

        block = item["summary"]
        if item.get("faction_allegiance"):
            block += f" Faction link: {item['faction_allegiance']}."
        if item.get("facts"):
            extra = " ".join(item["facts"][:2])
            if extra and extra not in block:
                block += f" {extra}"
        detail_lines.append(block.strip())

        if item.get("source_urls"):
            note_lines.append(f"{item['title']} → {', '.join(item['source_urls'])}")

    part1 = "\n\n".join(intro_lines)[:3500]
    part2 = "\n\n".join(detail_lines)[:3500]
    notes = "\n".join(note_lines)[:1500]

    return title, part1, part2, notes


def save_latest_lore_file(title: str, part1: str, part2: str, notes: str) -> None:
    write_json(
        LATEST_LORE_FILE,
        {
            "title": title,
            "part1": part1,
            "part2": part2,
            "notes": notes,
            "generated_at": now_iso(),
        },
    )


def generate_mode() -> None:
    memory = load_memory()

    # Guard: abort if memory has no entity facts yet (blank/reset state).
    # This prevents posting the stale fallback "SAM Memory Pulse" string
    # to Telegram when memory has been freshly wiped.
    facts = memory.get("facts", {})
    if not isinstance(facts, dict) or not any(
        isinstance(v, dict) and v for v in facts.values()
    ):
        print("[telegram-arm] SKIP: shared memory is empty or blank — no entities to post. "
              "Run the brain pipeline first.")
        return

    used_items = pick_items(memory, limit=3)
    title, part1, part2, notes = compose_lore(used_items)

    save_latest_lore_file(title, part1, part2, notes)
    memory = save_latest_lore_to_memory(memory, title, part1, part2, notes, used_items)
    save_memory(memory)

    print(f"[telegram-arm] generated lore from R2/shared memory using {len(used_items)} entities")
    print(f"[telegram-arm] latest title: {title}")


def build_send_text(latest: dict) -> str:
    title = (latest.get("title") or "SAM SIGNAL").strip()
    part1 = (latest.get("part1") or "").strip()
    part2 = (latest.get("part2") or "").strip()

    text = f"{title}\n\n{part1}\n\n{part2}".strip()
    return text[:4096]


def send_mode() -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.environ.get("CHANNEL_CHAT_IDS", "").split(",") if c.strip()]

    if not bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    if not chat_ids:
        raise RuntimeError("CHANNEL_CHAT_IDS missing")

    memory = load_memory()
    latest = get_latest_lore_from_memory(memory)
    if not latest:
        raise RuntimeError("No latest lore found in shared memory. Run generate mode first.")

    text = build_send_text(latest)
    for chat_id in chat_ids:
        telegram_send_message(bot_token, chat_id, text)
        print(f"[telegram-arm] sent latest lore to {chat_id}")

    used_ids = latest.get("used_item_ids", [])
    if used_ids:
        memory = mark_delivered(memory, "telegram", used_ids)
        save_memory(memory)
        print(f"[telegram-arm] marked {len(used_ids)} entity ids as delivered")


def main() -> None:
    generate_only = os.environ.get("GENERATE_ONLY", "").strip() == "1"
    send_only = os.environ.get("SEND_ONLY", "").strip() == "1"

    if generate_only and not send_only:
        generate_mode()
        return

    if send_only and not generate_only:
        send_mode()
        return

    generate_mode()
    send_mode()


if __name__ == "__main__":
    main()
