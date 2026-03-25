import os
from datetime import datetime, timezone

import requests
from anthropic import Anthropic
from openai import OpenAI

from utils import now_iso, read_json, short_history_append, telegram_send_message, write_json

STATE_FILE = "bot-state.json"
HISTORY_FILE = "lore-history.md"


def build_prompt(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append(
            f"{i}. {item['title']} | {item['summary']} | source: {item['source_name']} | page: {item['wiki_page']}"
        )

    return f"""
You are the Telegram voice arm for GraffPUNKS / Crypto Moonboys / GKniftyHEADS.

Write a 2-part Telegram post based only on the verified update items below.

Rules:
- Use only the supplied update data.
- Do not invent fake facts.
- Tone: raw, urgent, cinematic, rebellious, streetwise.
- Part 1 = main update.
- Part 2 = shorter closer / punch.
- No hashtags.
- No tables.

Return exactly:

PART 1:
[text]

PART 2:
[text]

UPDATES:
{chr(10).join(lines)}
""".strip()


def llm_generate(prompt: str) -> str:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    grok_key = os.environ.get("GROK_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if anthropic_key:
        client = Anthropic(api_key=anthropic_key)
        resp = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1200,
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
                "max_tokens": 1200,
                "temperature": 0.8,
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
            max_tokens=1200,
        )
        return resp.choices[0].message.content.strip()

    raise RuntimeError("No ANTHROPIC_API_KEY, GROK_API_KEY, or OPENAI_API_KEY found")


def parse_parts(text: str) -> tuple[str, str]:
    if "PART 1:" in text and "PART 2:" in text:
        a = text.split("PART 1:", 1)[1]
        b = a.split("PART 2:", 1)
        return b[0].strip()[:3800], b[1].strip()[:1200]
    return text[:3800].strip(), "More soon."


def main() -> None:
    state = read_json(STATE_FILE, {})
    items = state.get("items", [])
    fresh = [i for i in items if not i.get("telegram_done")]

    if not fresh:
        print("[telegram] nothing new")
        return

    batch = fresh[:5]
    prompt = build_prompt(batch)
    raw = llm_generate(prompt)
    part1, part2 = parse_parts(raw)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = f"GK Network Update — {stamp}"
    msg1 = f"{title}\n\n{part1}"
    msg2 = part2

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.environ.get("CHANNEL_CHAT_IDS", "").split(",") if c.strip()]

    if token and chat_ids:
        for chat_id in chat_ids:
            try:
                telegram_send_message(token, chat_id, msg1)
                telegram_send_message(token, chat_id, msg2)
                print(f"[telegram] sent to {chat_id}")
            except Exception as exc:
                print(f"[telegram] failed for {chat_id}: {exc}")
    else:
        print(msg1)
        print()
        print(msg2)

    ids = {i["id"] for i in batch}
    for item in items:
        if item["id"] in ids:
            item["telegram_done"] = True

    state["items"] = items
    state["last_telegram_post_at"] = now_iso()
    state["posted_to_telegram_ids"] = list(set(state.get("posted_to_telegram_ids", []) + list(ids)))[-8000:]

    write_json(STATE_FILE, state)
    short_history_append(HISTORY_FILE, title, msg1 + "\n\n" + msg2)
    print(f"[telegram] posted {len(batch)} updates")


if __name__ == "__main__":
    main()
