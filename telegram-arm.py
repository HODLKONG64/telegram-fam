import os
import re
from datetime import datetime, timezone

import requests
from anthropic import Anthropic
from openai import OpenAI

from utils import now_iso, read_json, read_text, short_history_append, write_json

STATE_FILE = "bot-state.json"
EXPORT_FILE = "main-brain-export.json"
HISTORY_FILE = "lore-history.md"
STORY_BIBLE_FILE = "story-bible.md"
CHARACTER_BIBLE_FILE = "character-bible.md"
LORE_PLANNER_FILE = "lore-planner.md"
LORE_CONFIG_FILE = "lore-config.json"
LATEST_LORE_FILE = "latest-lore.json"
IMAGE_STATE_FILE = "image-state.json"


def load_config() -> dict:
    return read_json(
        LORE_CONFIG_FILE,
        {
            "update_blend_min": 0.05,
            "update_blend_max": 0.10,
            "brain_signal_max": 0.20,
            "history_chars": 12000,
            "story_first": True,
            "batch_size": 5,
        },
    )


def load_story_bible() -> str:
    return read_text(STORY_BIBLE_FILE, "").strip()


def load_character_bible() -> str:
    return read_text(CHARACTER_BIBLE_FILE, "").strip()


def load_lore_planner() -> str:
    return read_text(LORE_PLANNER_FILE, "").strip()


def load_lore_history(history_chars: int) -> str:
    raw = read_text(HISTORY_FILE, "").strip()
    if not raw:
        return "(No previous lore yet.)"
    return raw[-history_chars:]


def get_current_utc_block() -> dict:
    now = datetime.now(timezone.utc)
    weekday = now.strftime("%A").upper()
    start_hour = (now.hour // 2) * 2
    end_hour = start_hour + 2
    return {
        "weekday": weekday,
        "start_hour": start_hour,
        "end_hour": end_hour,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M UTC"),
    }


def extract_planner_context(planner_text: str, block: dict) -> dict:
    result = {
        "activity": "The network is moving through another live block of story time.",
        "rules": [],
        "task_points": [],
    }
    if not planner_text.strip():
        return result

    in_day = False
    weekday = block["weekday"]
    start_hour = block["start_hour"]
    end_hour = block["end_hour"]

    for line in planner_text.splitlines():
        if re.match(rf"^##\s+{weekday}\b", line, re.IGNORECASE):
            in_day = True
            continue
        if in_day and re.match(r"^##\s+[A-Z]+", line):
            break
        if not in_day:
            continue

        m = re.match(
            r"\|\s*(\d{2}):(\d{2})[–\-](\d{2}):(\d{2})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|(?:\s*(.*?)\s*\|)?",
            line,
        )
        if not m:
            continue

        row_start = int(m.group(1))
        row_end = int(m.group(3))
        if row_start != start_hour or row_end != end_hour:
            continue

        activity = (m.group(5) or "").strip()
        rules_text = (m.group(6) or "").strip()
        task_text = (m.group(7) or "").strip()

        rules = re.findall(r"\([a-z0-9_-]+\)", rules_text.lower())
        task_points = [
            re.sub(r"\*+", "", p).strip()
            for p in re.split(r"\s*\\\|\s*", task_text)
            if p.strip()
        ]

        if activity:
            result["activity"] = activity
        result["rules"] = rules
        result["task_points"] = task_points
        break

    return result


def choose_fresh_items(state: dict, batch_size: int) -> list[dict]:
    items = state.get("items", [])
    fresh = [i for i in items if not i.get("telegram_done")]
    fresh.sort(
        key=lambda x: (
            int(x.get("mention_count", 0) or 0),
            x.get("published_at") or x.get("updated_at") or x.get("detected_at") or "",
        ),
        reverse=True,
    )
    return fresh[:batch_size]


def build_updates_block(items: list[dict]) -> str:
    if not items:
        return "No fresh updates this cycle."

    lines = []
    for i, item in enumerate(items, start=1):
        title = item.get("title", "Untitled")
        summary = re.sub(r"\s+", " ", str(item.get("summary", "")).strip())
        source_name = item.get("source_name", "Source")
        source_url = item.get("source_url", "")
        wiki_page = item.get("wiki_page", "")
        mention_count = item.get("mention_count", 0)

        lines.append(
            f"{i}. TITLE: {title}\n"
            f"   SUMMARY: {summary}\n"
            f"   SOURCE_NAME: {source_name}\n"
            f"   SOURCE_URL: {source_url}\n"
            f"   TARGET_PAGE: {wiki_page}\n"
            f"   MENTION_COUNT: {mention_count}"
        )
    return "\n\n".join(lines)


def build_prompt(
    story_bible: str,
    character_bible: str,
    planner_text: str,
    lore_history: str,
    fresh_items: list[dict],
    config: dict,
) -> str:
    block = get_current_utc_block()
    planner_ctx = extract_planner_context(planner_text, block)

    update_min = int(float(config.get("update_blend_min", 0.05)) * 100)
    update_max = int(float(config.get("update_blend_max", 0.10)) * 100)

    prompt = f"""
You are the Telegram story engine for GraffPUNKS / Crypto Moonboys / GKniftyHEADS.

Your job is to continue a living story world, not write a news report.

HARD RULES:
- Story core must be 90–95% of the post.
- Fresh updates must be only {update_min}–{update_max}% of the post.
- Use the updates as pressure, atmosphere, consequences, whispers, sightings, movement, or escalation inside the world.
- Do NOT turn the post into a dry update summary.
- Do NOT invent fake concrete facts beyond the supplied fresh updates.
- Keep names, titles, and project terms exact when used.
- Tone: cinematic, raw, urgent, rebellious, mythic, streetwise.
- No hashtags.
- No markdown tables.
- This output is for two Telegram messages sent back-to-back.
- Message 1 is text only.
- Message 2 continues the lore and is paired with an image.

TELEGRAM LENGTH RULES:
- PART 1 must fit under 3800 characters.
- PART 2 must fit under 900 characters.
- PART 2 must feel like a continuation, not a restart.

TIME BLOCK:
- Date: {block['date']}
- Time: {block['time']}
- Weekday: {block['weekday']}
- Block: {block['start_hour']:02d}:00–{block['end_hour']:02d}:00 UTC

PLANNER ACTIVITY:
{planner_ctx['activity']}

PLANNER RULE TOKENS:
{", ".join(planner_ctx['rules']) if planner_ctx['rules'] else "(none)"}

TASK POINTS:
{chr(10).join(f"- {p}" for p in planner_ctx['task_points']) if planner_ctx['task_points'] else "- keep the scene alive and continuous"}

STORY BIBLE:
{story_bible[:16000]}

CHARACTER BIBLE:
{character_bible[:10000]}

RECENT LORE HISTORY:
{lore_history}

FRESH VERIFIED UPDATES:
{build_updates_block(fresh_items)}

OUTPUT FORMAT:
PART 1:
[main post, under 3800 chars]

PART 2:
[continuation post, under 900 chars]

LORE NOTES:
[2-6 short bullet notes explaining which updates were woven in and how subtly]

Make it feel like one living entry from an expanding world.
""".strip()

    return prompt


def llm_generate(prompt: str) -> str:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    grok_key = os.environ.get("GROK_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if anthropic_key:
        client = Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()

    if grok_key:
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {grok_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-3-latest",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1800,
                "temperature": 0.9,
            },
            timeout=90,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    if openai_key:
        client = OpenAI(api_key=openai_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1800,
        )
        return resp.choices[0].message.content.strip()

    raise RuntimeError("No ANTHROPIC_API_KEY, GROK_API_KEY, or OPENAI_API_KEY found")


def parse_sections(text: str) -> tuple[str, str, str]:
    def grab(label: str, end_labels: list[str]) -> str:
        joined = "|".join(re.escape(x) for x in end_labels)
        if joined:
            pattern = rf"{re.escape(label)}\s*:\s*(.*?)(?=\n(?:{joined})\s*:|$)"
        else:
            pattern = rf"{re.escape(label)}\s*:\s*(.*)$"
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    part1 = grab("PART 1", ["PART 2", "LORE NOTES"])
    part2 = grab("PART 2", ["LORE NOTES"])
    notes = grab("LORE NOTES", [])

    if not part1 and not part2:
        part1 = text[:3200].strip()
        part2 = text[3200:4000].strip() or "The network keeps moving."
        notes = "- Fallback parse used."

    return part1[:3800], part2[:900], notes[:2000]


def build_title() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"GK Network Log Entry — {stamp}"


def save_latest_lore(title: str, part1: str, part2: str, notes: str, used_items: list[dict]) -> None:
    payload = {
        "title": title,
        "part1": part1,
        "part2": part2,
        "notes": notes,
        "generated_at": now_iso(),
        "used_item_ids": [i["id"] for i in used_items],
        "used_item_titles": [i.get("title", "") for i in used_items],
    }
    write_json(LATEST_LORE_FILE, payload)


def load_image_state() -> dict:
    return read_json(
        IMAGE_STATE_FILE,
        {
            "generated_at": None,
            "image_path": None,
            "prompt": "",
            "meta": {},
        },
    )


def telegram_send_text(bot_token: str, chat_id: str, text: str) -> dict:
    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4096]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def telegram_send_photo(bot_token: str, chat_id: str, image_path: str, caption: str) -> dict:
    with open(image_path, "rb") as fh:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"photo": fh},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()


def post_to_telegram(title: str, part1: str, part2: str, image_path: str | None) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.environ.get("CHANNEL_CHAT_IDS", "").split(",") if c.strip()]

    msg1 = f"{title}\n\n{part1}"
    msg2 = part2

    if token and chat_ids:
        for chat_id in chat_ids:
            telegram_send_text(token, chat_id, msg1)
            if image_path and os.path.exists(image_path):
                telegram_send_photo(token, chat_id, image_path, msg2)
                print(f"[telegram] sent text + image to {chat_id}")
            else:
                telegram_send_text(token, chat_id, msg2)
                print(f"[telegram] sent text-only fallback to {chat_id}")
    else:
        print("[telegram] missing config, output below")
        print("=== MESSAGE 1 ===")
        print(msg1)
        print()
        print("=== MESSAGE 2 ===")
        print(msg2)
        if image_path:
            print(f"[telegram] image path: {image_path}")


def mark_items_done(state: dict, used_items: list[dict]) -> dict:
    used_ids = {i["id"] for i in used_items}
    for item in state.get("items", []):
        if item.get("id") in used_ids:
            item["telegram_done"] = True

    state["last_telegram_post_at"] = now_iso()
    state["posted_to_telegram_ids"] = list(
        set(state.get("posted_to_telegram_ids", []) + list(used_ids))
    )[-8000:]
    return state


def append_lore_history(title: str, part1: str, part2: str, notes: str) -> None:
    block = f"{title}\n\n{part1}\n\n{part2}\n\nLORE NOTES:\n{notes}".strip()
    short_history_append(HISTORY_FILE, title, block)


def main() -> None:
    config = load_config()
    state = read_json(STATE_FILE, {})
    _export = read_json(EXPORT_FILE, {"items": []})

    fresh_items = choose_fresh_items(state, int(config.get("batch_size", 5)))
    if not fresh_items:
        print("[telegram] nothing new")
        return

    story_bible = load_story_bible()
    character_bible = load_character_bible()
    lore_planner = load_lore_planner()
    lore_history = load_lore_history(int(config.get("history_chars", 12000)))

    prompt = build_prompt(
        story_bible=story_bible,
        character_bible=character_bible,
        planner_text=lore_planner,
        lore_history=lore_history,
        fresh_items=fresh_items,
        config=config,
    )

    raw = llm_generate(prompt)
    part1, part2, notes = parse_sections(raw)
    title = build_title()

    save_latest_lore(title, part1, part2, notes, fresh_items)

    image_state = load_image_state()
    image_path = image_state.get("image_path")
    if image_path and not os.path.exists(image_path):
        image_path = None

    post_to_telegram(title, part1, part2, image_path)
    append_lore_history(title, part1, part2, notes)

    state = mark_items_done(state, fresh_items)
    write_json(STATE_FILE, state)

    print(f"[telegram] posted {len(fresh_items)} update-backed story items")


if __name__ == "__main__":
    main()
