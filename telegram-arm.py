import os
import re
import argparse
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


def choose_fresh_items(state: dict, batch_size: int) -> list[dict]:
    items = state.get("items", [])
    fresh = [i for i in items if not i.get("telegram_done")]
    fresh.sort(
        key=lambda x: (
            int(x.get("mention_count", 0) or 0),
            x.get("published_at") or "",
        ),
        reverse=True,
    )
    return fresh[:batch_size]


def llm_generate(prompt: str) -> str:
    grok_key = os.environ.get("GROK_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

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

    raise RuntimeError("No LLM keys found")


def build_title() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"GK Network Log Entry — {stamp}"


def post_to_telegram(title: str, part1: str, part2: str, image_path: str | None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [c.strip() for c in os.environ.get("CHANNEL_CHAT_IDS", "").split(",") if c.strip()]

    if not token or not chat_ids:
        print("[telegram] missing config")
        return

    for chat_id in chat_ids:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"{title}\n\n{part1}"},
        )

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": part2},
        )

        print(f"[telegram] sent to {chat_id}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["generate", "send"], default="generate")
    args = parser.parse_args()

    config = load_config()
    state = read_json(STATE_FILE, {})

    # -----------------------------
    # GENERATE MODE
    # -----------------------------
    if args.mode == "generate":
        fresh_items = choose_fresh_items(state, config["batch_size"])

        if not fresh_items:
            print("[telegram] nothing to generate")
            return

        prompt = "Continue the GraffPUNKS story using these updates:\n\n"
        for i in fresh_items:
            prompt += f"- {i.get('title')} :: {i.get('summary')}\n"

        text = llm_generate(prompt)

        title = build_title()

        write_json("latest-lore.json", {
            "title": title,
            "part1": text[:3000],
            "part2": text[3000:3800],
            "used_item_ids": [i["id"] for i in fresh_items]
        })

        print("[telegram] generated")
        return

    # -----------------------------
    # SEND MODE
    # -----------------------------
    if args.mode == "send":
        latest = read_json("latest-lore.json", {})

        if not latest:
            print("[telegram] no lore")
            return

        post_to_telegram(
            latest.get("title"),
            latest.get("part1"),
            latest.get("part2"),
            None
        )

        used_ids = set(latest.get("used_item_ids", []))

        for item in state.get("items", []):
            if item.get("id") in used_ids:
                item["telegram_done"] = True

        write_json(STATE_FILE, state)

        print("[telegram] sent + marked")
