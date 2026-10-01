#!/usr/bin/env python3
"""Import an MTG Arena export text file and write it out in the same
enriched, grouped format as export_deck.py.

Reuses fetch_scryfall_card() from card_lookup.py for the Scryfall fuzzy
lookup and throttling, and categorize()/format_card_block()/TYPE_ORDER from
export_deck.py for the shared card formatting, instead of duplicating either.
"""
import os
import re
import sys

import requests

from card_lookup import fetch_scryfall_card
from export_deck import OUTPUT_DIR, TYPE_ORDER, categorize, format_card_block

LINE_RE = re.compile(r"^(\d+)\s+(.+?)\s+\(([A-Za-z0-9]+)\)\s+(\S+)\s*$")
SECTIONS_TO_KEEP = {"commander", "deck"}
SECTIONS_TO_SKIP = {"sideboard", "companion"}


def parse_arena_export(path):
    """Return (commander_entries, deck_entries), each a list of (qty, name)."""
    sections = {"commander": [], "deck": []}
    current = None

    with open(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            lowered = line.lower()
            if lowered in SECTIONS_TO_KEEP:
                current = lowered
                continue
            if lowered in SECTIONS_TO_SKIP:
                current = None
                continue
            if current is None:
                continue

            match = LINE_RE.match(line)
            if not match:
                continue
            qty, name = int(match.group(1)), match.group(2).strip()
            sections[current].append((qty, name))

    return sections["commander"], sections["deck"]


def lookup_cards(entries, failed):
    """Look up each (qty, name) on Scryfall; collect failures instead of raising."""
    looked_up = []
    for qty, name in entries:
        try:
            card = fetch_scryfall_card(name)
        except (RuntimeError, requests.exceptions.RequestException) as e:
            failed.append((qty, name, str(e)))
            continue
        looked_up.append((qty, card))
    return looked_up


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} INPUT_FILE OUTPUT_FILENAME")
        sys.exit(1)

    input_path = sys.argv[1]
    output_filename = sys.argv[2]
    if not output_filename.endswith(".txt"):
        output_filename += ".txt"

    commander_entries, deck_entries = parse_arena_export(input_path)

    failed = []
    commander_cards = lookup_cards(commander_entries, failed)
    deck_cards = lookup_cards(deck_entries, failed)

    groups = {t: [] for t in TYPE_ORDER}
    groups["Other"] = []
    for qty, card in deck_cards:
        groups[categorize(card.get("type_line", ""))].append((qty, card))

    deck_name = (
        os.path.splitext(os.path.basename(output_filename))[0]
        .replace("_", " ")
        .title()
    )

    lines = [deck_name, ""]

    lines.append("Commander:")
    for qty, card in commander_cards:
        lines.extend(format_card_block(qty, card))
        lines.append("")

    for t in TYPE_ORDER + ["Other"]:
        entries = groups[t]
        if not entries:
            continue
        label = {"Land": "Lands", "Sorcery": "Sorceries"}.get(t, t if t.endswith("s") else t + "s")
        lines.append(f"{label}:")
        for qty, card in sorted(entries, key=lambda x: x[1].get("name", "").lower()):
            lines.extend(format_card_block(qty, card))
            lines.append("")

    total = sum(qty for qty, _ in commander_entries) + sum(qty for qty, _ in deck_entries)
    lines.append(f"Total: {total} cards")

    if failed:
        lines.append("")
        lines.append("Cards that failed lookup:")
        for qty, name, error in failed:
            lines.append(f"{qty}x {name} — {error}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, output_filename)
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    summary = f"{out_path}: {total} cards"
    if failed:
        summary += f", {len(failed)} failed lookups"
    print(summary)


if __name__ == "__main__":
    main()
