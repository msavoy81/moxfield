#!/usr/bin/env python3
"""Scan recent decks for a list of commanders and find cards popular in that
theme but missing from a reference deck.
"""
import os
import re
import sys
import time

import requests

from fetch_deck import get_moxfield_deck, search_decks

OUTPUT_DIR = os.path.expanduser("~/Documents/AI Projects/moxfield-exports")

TOP_DECKS_PER_COMMANDER = 5
TOP_CARDS = 60
UPDATED_WITHIN_DAYS = 90
DEFAULT_FORMAT = "commander"

# Matches a card line from export_deck.py/arena_import.py's enriched output,
# e.g. "1x Katara, Waterbending Master — {1}{U} — MV 2 — TLE". Oracle text
# lines are indented, so they never match this.
CARD_LINE_RE = re.compile(r"^(\d+)x\s+(.+?)\s+—\s+")

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


def read_enriched_deck_file(path):
    """Read card names out of an export_deck.py/arena_import.py output file."""
    names = set()
    with open(path) as f:
        for line in f:
            if line.startswith(" "):
                continue  # oracle text / extra faces are indented
            match = CARD_LINE_RE.match(line)
            if match:
                names.add(match.group(2).strip())
    return names


def load_my_cards(my_deck_arg):
    if os.path.isfile(my_deck_arg):
        return read_enriched_deck_file(my_deck_arg)
    return deck_card_names(get_moxfield_deck(my_deck_arg))


def scan_commander(commander_name, fmt, bracket):
    results = search_decks(
        commander_name=commander_name,
        fmt=fmt,
        min_bracket=bracket,
        max_bracket=bracket,
        updated_within_days=UPDATED_WITHIN_DAYS,
    )
    top_decks = results.get("data", [])[:TOP_DECKS_PER_COMMANDER]
    return [get_moxfield_deck(summary["publicId"]) for summary in top_decks]


def parse_args(argv):
    """Split argv into (positional, fmt, bracket)."""
    positional = []
    fmt = DEFAULT_FORMAT
    bracket = None
    i = 0
    while i < len(argv):
        if argv[i] == "--format":
            fmt = argv[i + 1]
            i += 2
        elif argv[i] == "--bracket":
            bracket = int(argv[i + 1])
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    return positional, fmt, bracket


def main():
    positional, fmt, bracket = parse_args(sys.argv[1:])

    if len(positional) < 3:
        print(
            f"Usage: {sys.argv[0]} OUTPUT_FILENAME MY_DECK_ID_OR_PATH "
            "COMMANDER_NAME [COMMANDER_NAME ...] [--format FMT] [--bracket N]"
        )
        sys.exit(1)

    output_filename, my_deck_arg, *commanders = positional
    if not output_filename.endswith(".txt"):
        output_filename += ".txt"

    my_cards = load_my_cards(my_deck_arg)

    card_stats = {}
    commander_deck_counts = []

    for commander in commanders:
        decks = scan_commander(commander, fmt, bracket)
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

    def fmt_row(a, b, c):
        return f"{a:<{w0}}  {b:<{w1}}  {c:<{w2}}"

    lines = []
    for commander, count in commander_deck_counts:
        lines.append(f"{commander}: {count} decks")
    lines.append("")
    lines.append(fmt_row(*header))
    lines.append(fmt_row("-" * w0, "-" * w1, "-" * w2))
    for row in rows:
        lines.append(fmt_row(*row))

    output = "\n".join(lines) + "\n"

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, output_filename)
    with open(out_path, "w") as f:
        f.write(output)

    print(output, end="")


if __name__ == "__main__":
    main()
