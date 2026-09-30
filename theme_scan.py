#!/usr/bin/env python3
"""Scan recent decks for a list of commanders and find cards popular in that
theme but missing from a reference deck.
"""
import os
import sys
import time

import requests

from fetch_deck import get_moxfield_deck, search_decks

OUTPUT_PATH = os.path.expanduser(
    "~/Documents/AI Projects/moxfield-exports/theme_scan_elenda.txt"
)

TOP_DECKS_PER_COMMANDER = 5
TOP_CARDS = 60
BRACKET = 4
UPDATED_WITHIN_DAYS = 90

MOXFIELD_MIN_INTERVAL = 1.0
_last_moxfield_call = 0.0
_original_requests_get = requests.get


def _rate_limited_get(url, *args, **kwargs):
    """Throttle only Moxfield API calls, wherever they originate (including
    the internal pagination inside fetch_deck.search_decks)."""
    global _last_moxfield_call
    if "moxfield.com" not in url:
        return _original_requests_get(url, *args, **kwargs)

    elapsed = time.monotonic() - _last_moxfield_call
    if elapsed < MOXFIELD_MIN_INTERVAL:
        time.sleep(MOXFIELD_MIN_INTERVAL - elapsed)
    try:
        return _original_requests_get(url, *args, **kwargs)
    finally:
        _last_moxfield_call = time.monotonic()


requests.get = _rate_limited_get


def is_basic_land(type_line):
    return "Basic Land" in (type_line or "")


def deck_card_names(deck):
    names = {
        entry.get("card", {}).get("name", "")
        for entry in (deck.get("mainboard") or {}).values()
    }
    names |= {
        entry.get("card", {}).get("name", "")
        for entry in (deck.get("commanders") or {}).values()
    }
    names.discard("")
    return names


def scan_commander(commander_name):
    results = search_decks(
        commander_name=commander_name,
        min_bracket=BRACKET,
        max_bracket=BRACKET,
        updated_within_days=UPDATED_WITHIN_DAYS,
    )
    top_decks = results.get("data", [])[:TOP_DECKS_PER_COMMANDER]
    return [get_moxfield_deck(summary["publicId"]) for summary in top_decks]


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} MY_DECK_ID_OR_URL COMMANDER_NAME [COMMANDER_NAME ...]")
        sys.exit(1)

    my_deck_id = sys.argv[1]
    commanders = sys.argv[2:]

    my_deck = get_moxfield_deck(my_deck_id)
    my_cards = deck_card_names(my_deck)

    card_stats = {}
    commander_deck_counts = []

    for commander in commanders:
        decks = scan_commander(commander)
        commander_deck_counts.append((commander, len(decks)))

        for deck in decks:
            seen_in_this_deck = set()
            for entry in (deck.get("mainboard") or {}).values():
                card = entry.get("card", {})
                name = card.get("name", "")
                if not name or name in seen_in_this_deck:
                    continue
                seen_in_this_deck.add(name)
                if is_basic_land(card.get("type_line", "")):
                    continue
                if name in my_cards:
                    continue
                stats = card_stats.setdefault(name, {"count": 0, "commanders": set()})
                stats["count"] += 1
                stats["commanders"].add(commander)

    ranked = sorted(
        card_stats.items(),
        key=lambda item: (-item[1]["count"], item[0].lower()),
    )[:TOP_CARDS]

    rows = [
        (name, str(stats["count"]), ", ".join(sorted(stats["commanders"])))
        for name, stats in ranked
    ]

    header = ("Card Name", "Deck Count", "Commanders")
    w0 = max(len(r[0]) for r in rows + [header])
    w1 = max(len(r[1]) for r in rows + [header])
    w2 = max(len(r[2]) for r in rows + [header])

    def fmt(a, b, c):
        return f"{a:<{w0}}  {b:<{w1}}  {c:<{w2}}"

    lines = []
    for commander, count in commander_deck_counts:
        lines.append(f"{commander}: {count} decks")
    lines.append("")
    lines.append(fmt(*header))
    lines.append(fmt("-" * w0, "-" * w1, "-" * w2))
    for row in rows:
        lines.append(fmt(*row))

    output = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write(output)

    print(output, end="")


if __name__ == "__main__":
    main()
