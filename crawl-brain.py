import time
from utils import (
    extract_summary,
    fetch_page_text,
    fingerprint,
    now_iso,
    read_json,
    write_json,
)

SOURCES_FILE = "sources.json"
FINGERPRINTS_FILE = "crawl-fingerprints.json"
RESULTS_FILE = "crawl-results.json"


def main() -> None:
    sources = read_json(SOURCES_FILE, [])
    known = set(read_json(FINGERPRINTS_FILE, []))
    state = read_json(RESULTS_FILE, {"last_crawl": None, "items": []})
    items = state.get("items", [])

    new_count = 0
    checked = 0

    for source in sources:
        url = source["url"]
        checked += 1

        try:
            title, text = fetch_page_text(url)
            summary = extract_summary(text, 700)
            fp = fingerprint(url, title, summary)

            if fp in known:
                print(f"[crawl] no change: {url}")
            else:
                print(f"[crawl] new update: {url}")
                known.add(fp)
                new_count += 1

                items.append(
                    {
                        "id": fp,
                        "source_name": source.get("name", title or url),
                        "source_url": url,
                        "title": title or source.get("name", url),
                        "summary": summary,
                        "category": source.get("category", "general"),
                        "wiki_page": source.get("wiki_page", title or "GK Brain Updates"),
                        "detected_at": now_iso(),
                        "used_in_lore": False,
                        "used_in_wiki": False,
                    }
                )

            time.sleep(1.2)

        except Exception as exc:
            print(f"[crawl] failed {url}: {exc}")

    write_json(FINGERPRINTS_FILE, sorted(list(known))[-10000:])
    write_json(
        RESULTS_FILE,
        {
            "last_crawl": now_iso(),
            "checked_urls": checked,
            "new_items": new_count,
            "items": items[-2000:],
        },
    )

    print(f"[crawl] done. checked={checked} new={new_count}")


if __name__ == "__main__":
    main()
