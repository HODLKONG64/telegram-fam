import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

import mwclient
import requests


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
    return dict(grouped))
