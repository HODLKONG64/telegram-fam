import hashlib
import os
import re
from datetime import datetime, timezone

from utils import read_json, write_json

CHARACTER_MEMORY_FILE = "character-memory.json"
LATEST_LORE_FILE = "latest-lore.json"
IMAGE_STATE_FILE = "image-state.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def load_character_memory() -> dict:
    return read_json(
        CHARACTER_MEMORY_FILE,
        {
            "updated_at": None,
            "characters": {}
        },
    )


def save_character_memory(data: dict) -> None:
    data["updated_at"] = now_iso()
    write_json(CHARACTER_MEMORY_FILE, data)


def load_latest_lore() -> dict:
    return read_json(
        LATEST_LORE_FILE,
        {
            "title": "",
            "part1": "",
            "part2": "",
            "notes": "",
            "generated_at": None,
            "used_item_ids": [],
            "used_item_titles": [],
        },
    )


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


def infer_gender(text: str) -> str:
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


def build_visual_dna(lore: str, image_meta: dict) -> dict:
    refs = image_meta.get("references", {}) if isinstance(image_meta, dict) else {}
    gender = image_meta.get("gender") or infer_gender(lore)
    character_name = image_meta.get("character_name") or extract_character_name(lore)

    base_key = "|".join(
        [
            character_name,
            gender,
            refs.get("main_base", ""),
            refs.get("bonnet", ""),
            refs.get("eyes", ""),
            refs.get("tattoos", ""),
            refs.get("clothing", ""),
        ]
    )
    visual_hash = hashlib.md5(base_key.encode("utf-8")).hexdigest()[:16]

    return {
        "character_name": character_name,
        "character_slug": slugify(character_name),
        "gender": gender,
        "visual_hash": visual_hash,
        "main_base_ref": refs.get("main_base", ""),
        "bonnet_ref": refs.get("bonnet", ""),
        "eyes_ref": refs.get("eyes", ""),
        "tattoos_ref": refs.get("tattoos", ""),
        "clothing_ref": refs.get("clothing", ""),
    }


def merge_character(existing: dict, incoming: dict, lore: str, image_path: str | None) -> dict:
    merged = dict(existing)

    merged["character_name"] = incoming.get("character_name", merged.get("character_name", "GraffPUNKS Character"))
    merged["character_slug"] = incoming.get("character_slug", merged.get("character_slug", "graffpunks-character"))
    merged["gender"] = incoming.get("gender", merged.get("gender", "male"))

    # Lock strong visual anchors once first found
    for field in [
        "main_base_ref",
        "bonnet_ref",
        "eyes_ref",
        "tattoos_ref",
        "clothing_ref",
    ]:
        if not merged.get(field) and incoming.get(field):
            merged[field] = incoming[field]

    if not merged.get("visual_hash"):
        merged["visual_hash"] = incoming.get("visual_hash", "")

    merged["last_seen_at"] = now_iso()
    merged["appearances"] = int(merged.get("appearances", 0) or 0) + 1

    if image_path:
        gallery = merged.get("image_gallery", [])
        if image_path not in gallery:
            gallery.append(image_path)
        merged["image_gallery"] = gallery[-20:]
        merged["latest_image_path"] = image_path

    lore_snippets = merged.get("lore_snippets", [])
    snippet = re.sub(r"\s+", " ", lore).strip()[:500]
    if snippet and snippet not in lore_snippets:
        lore_snippets.append(snippet)
    merged["lore_snippets"] = lore_snippets[-12:]

    merged["updated_at"] = now_iso()
    return merged


def main() -> None:
    latest_lore = load_latest_lore()
    image_state = load_image_state()
    memory = load_character_memory()

    part1 = latest_lore.get("part1", "").strip()
    part2 = latest_lore.get("part2", "").strip()
    combined_lore = f"{part1}\n\n{part2}".strip()

    if not combined_lore:
        print("[character-memory] no latest lore found")
        return

    image_meta = image_state.get("meta", {}) if isinstance(image_state, dict) else {}
    image_path = image_state.get("image_path") if isinstance(image_state, dict) else None

    visual_dna = build_visual_dna(combined_lore, image_meta)
    slug = visual_dna["character_slug"]

    characters = memory.get("characters", {})
    existing = characters.get(
        slug,
        {
            "created_at": now_iso(),
            "appearances": 0,
            "image_gallery": [],
            "lore_snippets": [],
        },
    )

    merged = merge_character(existing, visual_dna, combined_lore, image_path)
    characters[slug] = merged
    memory["characters"] = characters

    save_character_memory(memory)

    print(
        f"[character-memory] saved {merged['character_name']} "
        f"(slug={slug}, appearances={merged['appearances']})"
    )


if __name__ == "__main__":
    main()
