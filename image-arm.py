import base64
import os
import re
from datetime import datetime, timezone

import requests

from utils import read_json, write_json

IMAGE_STATE_FILE = "image-state.json"
LATEST_LORE_FILE = "latest-lore.json"
CHARACTER_MEMORY_FILE = "character-memory.json"

ASSETS_ROOT = "assets"

OUTPUT_DIR = "output"
OUTPUT_IMAGE = os.path.join(OUTPUT_DIR, "latest-character-scene.png")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


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


def load_character_memory() -> dict:
    return read_json(
        CHARACTER_MEMORY_FILE,
        {
            "updated_at": None,
            "characters": {},
        },
    )


def get_locked_character_traits(lore_text: str) -> dict:
    memory = load_character_memory()
    characters = memory.get("characters", {})

    character_name = extract_character_name(lore_text)
    character_slug = slugify(character_name)

    locked = characters.get(character_slug, {})
    if locked:
        return locked

    return {
        "character_name": character_name,
        "character_slug": character_slug,
        "gender": infer_gender_from_text(lore_text),
        "visual_hash": "",
        "main_base_ref": "",
        "bonnet_ref": "",
        "eyes_ref": "",
        "tattoos_ref": "",
        "clothing_ref": "",
        "traits_locked": False,
    }


def build_visual_prompt(lore_part_2: str, lore_part_1: str = "") -> tuple[str, dict]:
    combined = f"{lore_part_1}\n\n{lore_part_2}".strip()

    locked = get_locked_character_traits(combined)

    gender = locked.get("gender") or infer_gender_from_text(combined)
    character_name = locked.get("character_name") or extract_character_name(combined)

    main_base_ref = locked.get("main_base_ref", "")
    bonnet_ref = locked.get("bonnet_ref", "")
    eyes_ref = locked.get("eyes_ref", "")
    tattoos_ref = locked.get("tattoos_ref", "")
    clothing_ref = locked.get("clothing_ref", "")
    visual_hash = locked.get("visual_hash", "")

    tattoo_rule = (
        "Use tattoo styling influence from the locked male tattoo reference only if the character is male. "
        if gender == "male" and tattoos_ref
        else "Do not add male tattoo styling unless the character is male. "
    )

    trait_lock_rule = (
        "This character already has locked traits. Reuse the locked main body structure, locked bonnet family, "
        "locked face/eye language, locked clothing direction, and locked tattoo influence if present. "
        "Do not drift into a different character design. Keep this as the same recurring person."
        if locked.get("traits_locked")
        else "No locked trait identity was found, so create a strong first-pass identity that still follows the house rules."
    )

    prompt = f"""
Create one finished premium character scene image for the current Telegram lore continuation.

HARD CHARACTER RULES:
- Build the character from a strong main base/body structure influence.
- Tattoos are male-only influence.
- Clothing references are direction only, never copied exactly.
- Every lore character must have a unique bonnet/head structure.
- Eye references are style influence only, never copied exactly.
- The final character must feel like part of the same GraffPUNKS / Crypto Moonboys world but still be visually distinct.
- One finished scene image only.
- No collage.
- No sheet layout.
- No generic AI fantasy look.
- No copying reference images.
- References are influence only.

TRAIT LOCK RULE:
{trait_lock_rule}

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
- Locked visual hash: {visual_hash or "none yet"}

CURRENT LORE TO VISUALISE:
{combined[:5000]}

LOCKED REFERENCE FILES:
- Main Base: {main_base_ref or "none found"}
- Tattoos: {tattoos_ref or "none used"}
- Clothing: {clothing_ref or "none found"}
- Bonnet: {bonnet_ref or "none found"}
- Eyes: {eyes_ref or "none found"}

OUTPUT GOAL:
A single finished scene showing the current lore moment, with the character wearing a unique bonnet, using the house visual language, and looking like a real recurring lore character from the same universe.

DO NOT redesign the character from scratch if locked traits already exist.
""".strip()

    return prompt, {
        "gender": gender,
        "character_name": character_name,
        "visual_hash": visual_hash,
        "references": {
            "main_base": main_base_ref,
            "tattoos": tattoos_ref,
            "clothing": clothing_ref,
            "bonnet": bonnet_ref,
            "eyes": eyes_ref,
        },
        "traits_locked": bool(locked.get("traits_locked")),
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
