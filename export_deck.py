#!/usr/bin/env python3
"""Export Moxfield decks to grouped, human-readable plain text files.

Reuses get_moxfield_deck() from fetch_deck.py for all deck fetching.
"""
import os
import re
import sys
import time
from urllib.parse import quote

import requests

from fetch_deck import USER_AGENT, extract_deck_id, get_moxfield_deck

OUTPUT_DIR = os.path.expanduser("~/Documents/AI Projects/moxfield-exports")

TYPE_ORDER = [
    "Creature",
    "Planeswalker",
    "Battle",
    "Instant",
    "Sorcery",
    "Artifact",
    "Enchantment",
    "Land",
]

SCRYFALL_MIN_INTERVAL = 0.1
_last_scryfall_call = 0.0


def categorize(type_line):
    for t in TYPE_ORDER:
        if t in type_line:
            return t
    return "Other"


def slugify(name):
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return slug or "deck"


def format_mana_value(cmc):
    if cmc is None:
        return "?"
    if float(cmc).is_integer():
        return str(int(cmc))
    return str(cmc)


def fetch_scryfall_card(name):
    global _last_scryfall_call

    search_name = name.split(" // ")[0].strip()
    elapsed = time.monotonic() - _last_scryfall_call
    if elapsed < SCRYFALL_MIN_INTERVAL:
        time.sleep(SCRYFALL_MIN_INTERVAL - elapsed)

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    params = {"exact": search_name}
    try:
        response = requests.get(
            "https://api.scryfall.com/cards/named",
            headers=headers,
            params=params,
            timeout=15,
        )
    finally:
        _last_scryfall_call = time.monotonic()

    if response.status_code != 200:
        raise RuntimeError(
            f"Scryfall lookup failed for {name!r}: "
            f"HTTP {response.status_code} - {response.text}"
        )
    return response.json()


def has_complete_data(card):
    if "set" not in card or not card.get("set"):
        return False
    faces = card.get("card_faces")
    if faces:
        return all(
            "mana_cost" in f and "oracle_text" in f and f.get("oracle_text")
            for f in faces
        )
    return "mana_cost" in card and bool(card.get("oracle_text"))


def get_card_faces(card):
    """Return (set_code, [(face_name, mana_cost, oracle_text), ...])."""
    if not has_complete_data(card):
        scry = fetch_scryfall_card(card.get("name", ""))
        set_code = scry.get("set", card.get("set", "")).upper()
        if scry.get("card_faces"):
            faces = [
                (f.get("name", ""), f.get("mana_cost", ""), f.get("oracle_text", ""))
                for f in scry["card_faces"]
            ]
        else:
            faces = [
                (
                    scry.get("name", card.get("name", "")),
                    scry.get("mana_cost", ""),
                    scry.get("oracle_text", ""),
                )
            ]
        return set_code, faces

    set_code = card.get("set", "").upper()
    raw_faces = card.get("card_faces")
    if raw_faces:
        faces = [
            (f.get("name", ""), f.get("mana_cost", ""), f.get("oracle_text", ""))
            for f in raw_faces
        ]
    else:
        faces = [
            (card.get("name", ""), card.get("mana_cost", ""), card.get("oracle_text", ""))
        ]
    return set_code, faces


def format_card_block(quantity, card):
    name = card.get("name", "Unknown")
    cmc = card.get("cmc")
    set_code, faces = get_card_faces(card)

    header_mana_cost = card.get("mana_cost") or faces[0][1] or ""
    header = (
        f"{quantity}x {name} — {header_mana_cost or '—'} — "
        f"MV {format_mana_value(cmc)} — {set_code or '???'}"
    )

    lines = [header]
    for face_name, face_mana_cost, face_oracle_text in faces:
        if len(faces) > 1:
            face_label = f"{face_name}" + (f" {face_mana_cost}" if face_mana_cost else "")
            lines.append(f"  {face_label}")
        for text_line in (face_oracle_text or "").splitlines() or [""]:
            lines.append(f"  {text_line}")
        if len(faces) > 1:
            lines.append("")

    if lines and lines[-1] == "":
        lines.pop()

    return lines


def export_deck(deck_id_or_url, filename=None):
    deck = get_moxfield_deck(deck_id_or_url)

    name = deck.get("name", "Unknown Deck")
    fmt = deck.get("format", "")
    last_updated = (deck.get("lastUpdatedAtUtc") or "")[:10]

    commanders = deck.get("commanders") or {}
    commander_entries = list(commanders.values())
    commander_qty_total = sum(e.get("quantity", 0) for e in commander_entries)

    mainboard = list((deck.get("mainboard") or {}).values())
    groups = {t: [] for t in TYPE_ORDER}
    groups["Other"] = []
    mainboard_qty_total = 0

    for entry in mainboard:
        qty = entry.get("quantity", 0)
        card = entry.get("card", {})
        category = categorize(card.get("type_line", ""))
        groups[category].append((qty, card))
        mainboard_qty_total += qty

    lines = [name]
    if fmt:
        lines.append(f"Format: {fmt}")
    if last_updated:
        lines.append(f"Last updated: {last_updated}")
    lines.append("")

    lines.append("Commander:")
    for entry in commander_entries:
        lines.extend(format_card_block(entry.get("quantity", 1), entry.get("card", {})))
        lines.append("")

    for t in TYPE_ORDER + ["Other"]:
        entries = groups[t]
        if not entries:
            continue
        label = "Lands" if t == "Land" else (t if t.endswith("s") else t + "s")
        lines.append(f"{label}:")
        for qty, card in sorted(entries, key=lambda x: x[1].get("name", "").lower()):
            lines.extend(format_card_block(qty, card))
            lines.append("")

    total = commander_qty_total + mainboard_qty_total
    lines.append(f"Total: {total} cards")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not filename:
        filename = slugify(name) + ".txt"
    if not filename.endswith(".txt"):
        filename += ".txt"
    out_path = os.path.join(OUTPUT_DIR, filename)

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return out_path, total


def parse_args(argv):
    """Each arg is DECK_ID_OR_URL or DECK_ID_OR_URL=filename.txt."""
    specs = []
    for arg in argv:
        if "=" in arg and not arg.startswith("http"):
            deck_part, filename = arg.split("=", 1)
        elif "=" in arg:
            # URL case: split only on the last "=" if it looks like a filename suffix.
            deck_part, _, maybe_filename = arg.rpartition("=")
            if maybe_filename.endswith(".txt"):
                deck_part, filename = deck_part, maybe_filename
            else:
                deck_part, filename = arg, None
        else:
            deck_part, filename = arg, None
        specs.append((extract_deck_id(deck_part), filename))
    return specs


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} DECK_ID_OR_URL[=filename.txt] [...]")
        sys.exit(1)

    for deck_id, filename in parse_args(sys.argv[1:]):
        out_path, total = export_deck(deck_id, filename)
        print(f"{quote(out_path, safe='/')}: {total} cards")


if __name__ == "__main__":
    main()
