import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import mwclient
import requests
from bs4 import BeautifulSoup


USER_AGENT = "GK-Brain-Lite/1.0"


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
    existing = read_text(path, "")
    write_text(path, existing + content)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fingerprint(*parts: str) -> str:
    base = " | ".join(normalize_text(p) for p in parts if p)
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:16]


def fetch_page_text(url: str, timeout: int = 20) -> tuple[str, str]:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "footer", "nav", "header"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.text:
        title = normalize_text(soup.title.text)[:180]

    text = normalize_text(soup.get_text(" ", strip=True))
    return title, text


def extract_summary(text: str, max_len: int = 500) -> str:
    text = normalize_text(text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    if ". " in cut:
        cut = cut.rsplit(". ", 1)[0] + "."
    return cut


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def telegram_send_message(bot_token: str, chat_id: str, text: str) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": chat_id, "text": text[:4096]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fandom_connect():
    wiki_url = os.environ.get("FANDOM_WIKI_URL", "").strip()
    user = os.environ.get("FANDOM_BOT_USER", "").strip()
    password = os.environ.get("FANDOM_BOT_PASSWORD", "").strip()

    if not wiki_url or not user or not password:
        raise RuntimeError("Missing FANDOM_WIKI_URL, FANDOM_BOT_USER, or FANDOM_BOT_PASSWORD")

    parsed = urlparse(wiki_url)
    host = parsed.netloc
    path = parsed.path.strip("/") or "/"

    site = mwclient.Site(host, path="/" if path == "/" else f"/{path}/", scheme="https")
    site.login(user, password)
    return site


def fandom_get_page_text(site, page_title: str) -> str:
    page = site.pages[page_title]
    try:
        return page.text()
    except Exception:
        return ""


def fandom_save_page(site, page_title: str, content: str, summary: str) -> None:
    page = site.pages[page_title]
    page.save(content, summary=summary)


def build_ref(url: str, label: str | None = None) -> str:
    access = today_utc()
    shown = label or url
    return f"<ref>[{url} {shown}], accessed {access}</ref>"


def ensure_section(text: str, heading: str) -> str:
    heading_markup = f"== {heading} =="
    if heading_markup in text:
        return text
    if text.strip() and not text.endswith("\n"):
        text += "\n"
    return text + f"\n{heading_markup}\n\n"


def safe_append_under_section(text: str, heading: str, block: str) -> str:
    heading_markup = f"== {heading} =="
    if heading_markup not in text:
        text = ensure_section(text, heading)

    marker = heading_markup
    start = text.find(marker)
    if start == -1:
        return text + f"\n{block}\n"

    after_heading = text.find("\n", start)
    if after_heading == -1:
        return text + f"\n{block}\n"

    next_section_match = re.search(r"\n== [^=].*? ==\n", text[after_heading + 1 :])
    if next_section_match:
        insert_at = after_heading + 1 + next_section_match.start()
        return text[:insert_at] + "\n" + block.strip() + "\n" + text[insert_at:]
    return text.rstrip() + "\n\n" + block.strip() + "\n"


def build_update_block(item: dict) -> str:
    uid = item["id"]
    title = item.get("title") or "Untitled update"
    source_name = item.get("source_name") or domain_of(item.get("source_url", ""))
    source_url = item.get("source_url", "")
    summary = item.get("summary", "").strip()
    date = item.get("detected_at", now_iso())[:10]
    ref = build_ref(source_url, source_name)

    return (
        f"<!-- GK-BRAIN-LITE:{uid} -->\n"
        f"* {date} — '''{title}''': {summary} {ref}"
    )


def has_update_marker(text: str, update_id: str) -> bool:
    return f"<!-- GK-BRAIN-LITE:{update_id} -->" in text


def build_recovery_page(page_title: str, items: list[dict]) -> str:
    top = items[:5]
    overview_bits = []
    source_lines = []

    for item in top:
        source_url = item.get("source_url", "")
        source_name = item.get("source_name") or domain_of(source_url)
        source_lines.append(f"* [{source_url} {source_name}]")
        overview_bits.append(item.get("summary", "").strip())

    overview = " ".join(overview_bits)[:1200].strip()
    if not overview:
        overview = f"{page_title} is being rebuilt from official source updates."

    latest_blocks = "\n".join(build_update_block(i) for i in items)

    return f"""= {page_title} =

== Overview ==

{overview}

== Details ==

This page was rebuilt automatically because the previous page content was empty or near-empty. It is now being repopulated from approved official sources only.

== Latest Updates ==

{latest_blocks}

== Sources ==

{chr(10).join(source_lines)}
""".strip() + "\n"


def short_lore_history_append(path: str, title: str, lore: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = f"\n\n---\n## {stamp} — {title}\n\n{lore.strip()}\n"
    existing = read_text(path, "")
    combined = (existing + block)[-50000:]
    write_text(path, combined)
