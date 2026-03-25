import base64
import os
import random
import re
from datetime import datetime, timezone

import requests

from utils import read_json, write_json

IMAGE_STATE_FILE = "image-state.json"
LATEST_LORE_FILE = "latest-lore.json"

ASSETS_ROOT = "assets"

FOLDER_MAIN_BASE = os.path.join(ASSETS_ROOT, "1-main-base")
FOLDER_TATTOOS = os.path.join(ASSETS_ROOT, "1a-tattoos-male-only")
FOLDER_CLOTHING = os.path.join(ASSETS_ROOT, "1b-clothing-reference")
FOLDER_BONNETS = os.path.join(ASSETS_ROOT, "1c-bonnets")
FOLDER_EYES = os.path.join(ASSETS_ROOT, "1d-eyes")

OUTPUT_DIR = "output"
OUTPUT_IMAGE = os.path.join(OUTPUT_DIR, "latest-character-scene.png")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def list_files_recursive(root: str) -> list[str]:
    out = []
    if not os.path.exists(root):
        return out
    for base, _, files in os.walk(root):
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                out.append(os.path.join(base, f))
    return sorted(out)


def choose_random_file(paths: list[str]) -> str:
    return random.choice(paths) if paths else ""


def infer_gender_from_text(text: str) -> str:
    lower = " " + text.lower().replace("-", " ") + " "
    female_hits = 0
    male_hits = 0

    female_terms = [
        " she ", " her ", " hers ", " herself ",
        " lady ", " queen ", " princess ", " female ",
        " jodie ", " lady ink ", " moongirl ",
    ]
    male_terms = [
        " he ", " his ", " himself ",
        " male ", " boy ", " bloke ",
        " charlie ", " alfie ",
    ]

    for term in female_terms:
        if term in lower:
            female_hits += 1

    for term in male_terms:
        if term in lower:
            male_hits += 1

    return "female" if female_hits > male_hits else "male"


def extract_character_name(text: str) -> str:
    candidates = [
        "Charlie Buster",
        "Lady Ink",
        "Jodie Zoom",
        "Alfie",
        "Queen Sarah P-fly",
        "Null The Prophet",
        "GraffPUNK",
        "Moonboy",
    ]
    lower = text.lower()
    for candidate in candidates:
        if candidate.lower() in lower:
            return candidate
    return "GraffPUNKS Character"


def pick_reference_set(gender: str) -> dict:
    main_base_files = list_files_recursive(FOLDER_MAIN_BASE)
    tattoo_files = list_files_recursive(FOLDER_TATTOOS)
    bonnet_files = list_files_recursive(FOLDER_BONNETS)

    clothing_root = os.path.join(FOLDER_CLOTHING, gender)
    clothing_files = list_files_recursive(clothing_root)

    eyes_root = os.path.join(FOLDER_EYES, gender)
    eyes_files = list_files_recursive(eyes_root)

    tattoos = ""
    if gender == "male":
        tattoos = choose_random_file(tattoo_files)

    return {
        "main_base": choose_random_file(main_base_files),
        "tattoos": tattoos,
        "clothing": choose_random_file(clothing_files),
        "bonnet": choose_random_file(bonnet_files),
        "eyes": choose_random_file(eyes_files),
    }


def build_visual_prompt(lore_part_2: str, lore_part_1: str = "") -> tuple[str, dict]:
    combined = f"{lore_part_1}\n\n{lore_part_2}".strip()
    gender = infer_gender_from_text(combined)
    character_name = extract_character_name(combined)
    refs = pick_reference_set(gender)

    tattoo_rule = (
        "Use tattoo styling influence from the male tattoo reference only if the character is male. "
        if gender == "male" and refs["tattoos"]
        else "Do not add male tattoo styling unless the character is male. "
    )

    prompt = f"""
Create one finished premium character scene image for the current Telegram lore continuation.

HARD CHARACTER RULES:
- Build the character from a strong main base/body structure influence.
- Folder 1A tattoos are male-only influence.
- Folder 1B clothing examples are reference only, never copied exactly.
- Folder 1C bonnet references are mandatory influence because every lore character must have a unique bonnet/head structure.
- Folder 1D eye references are style influence only, never copied exactly.
- The final character must feel like part of the same GraffPUNKS / Crypto Moonboys world but still be visually distinct.
- Do not create a collage, character sheet, moodboard, or multiple characters unless the lore clearly needs it.
- One finished scene image only.
- No generic AI fantasy look.
- No copying reference images.
- References are influence only.

STYLE RULES:
- premium character art
- dark stylish graffiti-cyberpunk energy
- dystopian London / underground / signal-network mood
- cinematic lighting
- gritty textures
- highly readable face
- strong bonnet silhouette
- collectible visual identity
- detailed but clean

{tattoo_rule}

CHARACTER:
- Name focus: {character_name}
- Gender style: {gender}

CURRENT LORE TO VISUALISE:
{combined[:5000]}

REFERENCE FILES SELECTED:
- Main Base: {refs['main_base'] or 'none found'}
- Tattoos: {refs['tattoos'] or 'none used'}
- Clothing: {refs['clothing'] or 'none found'}
- Bonnet: {refs['bonnet'] or 'none found'}
- Eyes: {refs['eyes'] or 'none found'}

OUTPUT GOAL:
A single finished scene showing the current lore moment, with the character wearing a unique bonnet, using the house visual language, and looking like a real recurring lore character from the same universe.
""".strip()

    return prompt, {
        "gender": gender,
        "character_name": character_name,
        "references": refs,
    }


def generate_image_openai(prompt: str) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "gpt-image-1",
        "prompt": prompt,
        "size": "1024x1024",
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        image_b64 = data["data"][0]["b64_json"]

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        image_bytes = base64.b64decode(image_b64)
        with open(OUTPUT_IMAGE, "wb") as fh:
            fh.write(image_bytes)
        return OUTPUT_IMAGE
    except Exception as exc:
        print(f"[image-arm] OpenAI image generation failed: {exc}")
        return None


def generate_image_grok(prompt: str) -> str | None:
    grok_key = os.environ.get("GROK_API_KEY", "").strip()
    if not grok_key:
        return None

    headers = {
        "Authorization": f"Bearer {grok_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "grok-imagine-image",
        "prompt": prompt,
        "n": 1,
        "response_format": "url",
    }

    try:
        resp = requests.post(
            "https://api.x.ai/v1/images/generations",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        image_url = resp.json()["data"][0]["url"]

        img = requests.get(image_url, timeout=60)
        img.raise_for_status()

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(OUTPUT_IMAGE, "wb") as fh:
            fh.write(img.content)
        return OUTPUT_IMAGE
    except Exception as exc:
        print(f"[image-arm] Grok image generation failed: {exc}")
        return None


def load_latest_lore() -> dict:
    return read_json(
        LATEST_LORE_FILE,
        {
            "title": "",
            "part1": "",
            "part2": "",
            "notes": "",
            "generated_at": None,
        },
    )


def save_image_state(payload: dict) -> None:
    write_json(IMAGE_STATE_FILE, payload)


def main() -> None:
    latest = load_latest_lore()
    lore_part_1 = latest.get("part1", "").strip()
    lore_part_2 = latest.get("part2", "").strip()

    if not lore_part_1 and not lore_part_2:
        print("[image-arm] No latest lore found.")
        return

    prompt, meta = build_visual_prompt(
        lore_part_2=lore_part_2,
        lore_part_1=lore_part_1,
    )

    image_path = generate_image_openai(prompt)
    if image_path is None:
        image_path = generate_image_grok(prompt)

    payload = {
        "generated_at": now_iso(),
        "image_path": image_path,
        "prompt": prompt,
        "meta": meta,
    }

    save_image_state(payload)

    if image_path:
        print(f"[image-arm] image created: {image_path}")
    else:
        print("[image-arm] image generation failed")


if __name__ == "__main__":
    main()
