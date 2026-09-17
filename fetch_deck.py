#!/usr/bin/env python3
import re
import sys

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_DECK_ID = "rAHH2XeO2USKMlAf2xxGJA"


def extract_deck_id(deck_id_or_url):
    match = re.search(r"moxfield\.com/decks/([^/?#]+)", deck_id_or_url)
    if match:
        return match.group(1)
    return deck_id_or_url


def get_moxfield_deck(deck_id_or_url):
    deck_id = extract_deck_id(deck_id_or_url)
    url = f"https://api.moxfield.com/v2/decks/all/{deck_id}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to reach Moxfield: {e}")

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch deck {deck_id!r}: "
            f"HTTP {response.status_code} - {response.text}"
        )

    return response.json()


def print_deck(deck):
    print(f"Name: {deck.get('name')}")
    print(f"Format: {deck.get('format')}")

    commanders = deck.get("commanders") or {}
    if commanders:
        commander_names = ", ".join(
            card_entry.get("card", {}).get("name", "Unknown")
            for card_entry in commanders.values()
        )
        print(f"Commander(s): {commander_names}")
    else:
        print("Commander(s): None")

    print("\nMainboard:")
    mainboard = deck.get("mainboard") or {}
    for card_entry in mainboard.values():
        quantity = card_entry.get("quantity", 0)
        name = card_entry.get("card", {}).get("name", "Unknown")
        print(f"{quantity}x {name}")


def main():
    deck_id_or_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DECK_ID
    deck = get_moxfield_deck(deck_id_or_url)
    print_deck(deck)


if __name__ == "__main__":
    main()
