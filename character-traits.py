import hashlib
import os
import random
import re
from datetime import datetime, timezone

from utils import read_json, write_json

CHARACTER_MEMORY_FILE = "character-memory.json"
LATEST_LORE_FILE = "latest-lore.json"

ASSETS_ROOT = "assets"

FOLDER_MAIN_BASE = os.path.join(ASSETS_ROOT, "1-main-base")
FOLDER_TATTOOS = os.path.join(ASSETS_ROOT, "1a-tattoos-male-only")
FOLDER_CLOTHING = os.path.join(ASSETS_ROOT, "1b-clothing-reference")
FOLDER_BONNETS = os.path.join(ASSETS_ROOT, "1c-bonnets")
FOLDER_EYES = os.path.join(ASSETS_ROOT, "1d-eyes")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


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


def load_character_memory() -> dict:
    return read_json(
        CHARACTER_MEMORY_FILE,
        {
            "updated_at": None,
            "characters": {},
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


def stable_index(seed_text: str, size: int) -> int:
    if size <= 0:
        return 0
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def stable_pick(seed_text: str, paths: list[str]) -> str:
    if not paths:
        return ""
    idx = stable_index(seed_text, len(paths))
    return paths[idx]


def build_trait_pool(gender: str) -> dict:
    main_base_files = list_files_recursive(FOLDER_MAIN_BASE)
    tattoo_files = list_files_recursive(FOLDER_TATTOOS)
    bonnet_files = list_files_recursive(FOLDER_BONNETS)

    clothing_root = os.path.join(FOLDER_CLOTHING, gender)
    clothing_files = list_files_recursive(clothing_root)

    eyes_root = os.path.join(FOLDER_EYES, gender)
    eyes_files = list_files_recursive(eyes_root)

    return {
        "main_base_files": main_base_files,
        "tattoo_files": tattoo_files,
        "clothing_files": clothing_files,
        "bonnet_files": bonnet_files,
        "eyes_files": eyes_files,
    }


def assign_traits(character_name: str, gender: str) -> dict:
    pool = build_trait_pool(gender)
    seed_base = f"{slugify(character_name)}|{gender}"

    main_base_ref = stable_pick(seed_base + "|main-base", pool["main_base_files"])
    bonnet_ref = stable_pick(seed_base + "|bonnet", pool["bonnet_files"])
    eyes_ref = stable_pick(seed_base + "|eyes", pool["eyes_files"])
    clothing_ref = stable_pick(seed_base + "|clothing", pool["clothing_files"])

    tattoos_ref = ""
    if gender == "male":
        tattoos_ref = stable_pick(seed_base + "|tattoos", pool["tattoo_files"])

    visual_hash = hashlib.md5(
        "|".join(
            [
                character_name,
                gender,
                main_base_ref,
                bonnet_ref,
                eyes_ref,
                tattoos_ref,
                clothing_ref,
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "character_name": character_name,
        "character_slug": slugify(character_name),
        "gender": gender,
        "visual_hash": visual_hash,
        "main_base_ref": main_base_ref,
        "bonnet_ref": bonnet_ref,
        "eyes_ref": eyes_ref,
        "tattoos_ref": tattoos_ref,
        "clothing_ref": clothing_ref,
        "traits_locked": True,
        "traits_created_at": now_iso(),
    }


def merge_traits(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)

    merged["character_name"] = existing.get("character_name") or incoming.get("character_name", "GraffPUNKS Character")
    merged["character_slug"] = existing.get("character_slug") or incoming.get("character_slug", "graffpunks-character")
    merged["gender"] = existing.get("gender") or incoming.get("gender", "male")

    for field in [
        "main_base_ref",
        "bonnet_ref",
        "eyes_ref",
        "tattoos_ref",
        "clothing_ref",
        "visual_hash",
        "traits_locked",
        "traits_created_at",
    ]:
        if not merged.get(field):
            merged[field] = incoming.get(field)

    merged["last_traits_check_at"] = now_iso()
    return merged


def main() -> None:
    latest = load_latest_lore()
    part1 = latest.get("part1", "").strip()
    part2 = latest.get("part2", "").strip()
    combined = f"{part1}\n\n{part2}".strip()

    if not combined:
        print("[character-traits] no latest lore found")
        return

    character_name = extract_character_name(combined)
    gender = infer_gender(combined)
    slug = slugify(character_name)

    memory = load_character_memory()
    characters = memory.get("characters", {})

    existing = characters.get(slug, {})
    incoming_traits = assign_traits(character_name, gender)
    merged = merge_traits(existing, incoming_traits)

    merged["last_seen_at"] = now_iso()
    merged["appearances"] = int(merged.get("appearances", 0) or 0) + 1

    lore_snippets = merged.get("lore_snippets", [])
    snippet = re.sub(r"\s+", " ", combined).strip()[:500]
    if snippet and snippet not in lore_snippets:
        lore_snippets.append(snippet)
    merged["lore_snippets"] = lore_snippets[-12:]

    characters[slug] = merged
    memory["characters"] = characters

    save_character_memory(memory)

    print(
        f"[character-traits] locked traits for {merged['character_name']} "
        f"(slug={slug}, gender={merged['gender']}, visual_hash={merged['visual_hash']})"
    )
    print(f"[character-traits] main_base_ref={merged.get('main_base_ref', '')}")
    print(f"[character-traits] bonnet_ref={merged.get('bonnet_ref', '')}")
    print(f"[character-traits] eyes_ref={merged.get('eyes_ref', '')}")
    print(f"[character-traits] tattoos_ref={merged.get('tattoos_ref', '')}")
    print(f"[character-traits] clothing_ref={merged.get('clothing_ref', '')}")


if __name__ == "__main__":
    main()
