#!/usr/bin/env python3
"""Look up one or more card names on Scryfall and print full card details."""
import os
import sys
import time

import requests

from fetch_deck import USER_AGENT

OUTPUT_PATH = os.path.expanduser(
    "~/Documents/AI Projects/moxfield-exports/card_lookup.txt"
)

SCRYFALL_MIN_INTERVAL = 0.2
_last_scryfall_call = 0.0

MAX_RATE_LIMIT_RETRIES = 3


def fetch_scryfall_card(name):
    global _last_scryfall_call

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    params = {"fuzzy": name}

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        elapsed = time.monotonic() - _last_scryfall_call
        if elapsed < SCRYFALL_MIN_INTERVAL:
            time.sleep(SCRYFALL_MIN_INTERVAL - elapsed)

        try:
            response = requests.get(
                "https://api.scryfall.com/cards/named",
                headers=headers,
                params=params,
                timeout=15,
            )
        finally:
            _last_scryfall_call = time.monotonic()

        if response.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
            # Honor Scryfall's cooldown instead of hammering it with the next
            # card's request, which would just extend the block further.
            retry_after = int(response.headers.get("Retry-After", 60))
            time.sleep(retry_after + 1)
            _last_scryfall_call = time.monotonic()
            continue

        if response.status_code != 200:
            raise RuntimeError(
                f"Scryfall lookup failed for {name!r}: "
                f"HTTP {response.status_code} - {response.text}"
            )
        return response.json()


def format_mana_value(cmc):
    if cmc is None:
        return "?"
    if float(cmc).is_integer():
        return str(int(cmc))
    return str(cmc)


def format_card(card):
    name = card.get("name", "Unknown")
    mana_cost = card.get("mana_cost") or ""
    mana_value = format_mana_value(card.get("cmc"))
    type_line = card.get("type_line", "")
    set_code = (card.get("set") or "").upper()

    lines = [
        name,
        f"Mana Cost: {mana_cost or '—'}",
        f"Mana Value: {mana_value}",
        f"Type: {type_line}",
        f"Set: {set_code or '???'}",
    ]

    faces = card.get("card_faces")
    if faces:
        lines.append("Oracle Text:")
        for i, face in enumerate(faces):
            if i > 0:
                lines.append("")
            face_name = face.get("name", "")
            face_mana_cost = face.get("mana_cost") or ""
            face_type_line = face.get("type_line", "")
            lines.append(f"  {face_name} — {face_mana_cost or '—'} — {face_type_line}")
            for text_line in (face.get("oracle_text") or "").splitlines():
                lines.append(f"  {text_line}")
    else:
        lines.append("Oracle Text:")
        for text_line in (card.get("oracle_text") or "").splitlines():
            lines.append(f"  {text_line}")

    return lines


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} CARD_NAME [CARD_NAME ...]")
        sys.exit(1)

    all_lines = []
    for i, name in enumerate(sys.argv[1:]):
        if i > 0:
            all_lines.append("")
        card = fetch_scryfall_card(name)
        all_lines.extend(format_card(card))

    output = "\n".join(all_lines) + "\n"

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write(output)

    print(output, end="")


if __name__ == "__main__":
    main()
