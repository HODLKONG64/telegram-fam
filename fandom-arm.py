from utils import (
    append_under_latest_updates,
    build_recovery_page,
    build_update_block,
    fandom_connect,
    fandom_get_page_text,
    fandom_save_page,
    group_by_page,
    has_marker,
    load_memory,
    now_iso,
    read_json,
    write_json,
)

STATE_FILE = "bot-state.json"
MIN_EXISTING_PAGE_LEN = 300


def main() -> None:
    # Guard: abort if memory has no entity facts yet (blank/reset state).
    # This prevents posting stale or empty content to Fandom when memory
    # has been freshly wiped.
    memory = load_memory()
    facts = memory.get("facts", {})
    if not isinstance(facts, dict) or not any(
        isinstance(v, dict) and v for v in facts.values()
    ):
        print("[fandom] SKIP: shared memory is empty or blank — no entities to post. "
              "Run the brain pipeline first.")
        return

    state = read_json(STATE_FILE, {})
    items = state.get("items", [])
    fresh = [i for i in items if not i.get("fandom_done")]

    if not fresh:
        print("[fandom] nothing new")
        return

    site = fandom_connect()
    grouped = group_by_page(fresh)
    processed = set()

    for page_title, page_items in grouped.items():
        print(f"[fandom] processing {page_title} ({len(page_items)} items)")
        existing = fandom_get_page_text(site, page_title) or ""

        if len(existing.strip()) < MIN_EXISTING_PAGE_LEN:
            rebuilt = build_recovery_page(page_title, page_items)
            fandom_save_page(
                site,
                page_title,
                rebuilt,
                summary="GK Telegram Fandom Bot: rebuild empty page from approved main-brain updates",
            )
            for item in page_items:
                processed.add(item["id"])
            continue

        updated = existing
        changed = False

        for item in page_items:
            if has_marker(updated, item["id"]):
                processed.add(item["id"])
                continue

            block = build_update_block(item)
            updated = append_under_latest_updates(updated, block)
            processed.add(item["id"])
            changed = True

        if changed:
            fandom_save_page(
                site,
                page_title,
                updated,
                summary="GK Telegram Fandom Bot: append approved main-brain updates safely",
            )

    for item in items:
        if item["id"] in processed:
            item["fandom_done"] = True

    state["items"] = items
    state["last_fandom_update_at"] = now_iso()
    state["posted_to_fandom_ids"] = list(set(state.get("posted_to_fandom_ids", []) + list(processed)))[-8000:]
    write_json(STATE_FILE, state)

    print(f"[fandom] processed {len(processed)} items")


if __name__ == "__main__":
    main()
