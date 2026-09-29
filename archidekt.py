#!/usr/bin/env python3
import re
import sys

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# https://archidekt.com/api/decks/formats/
ARCHIDEKT_FORMATS = {
    1: "Standard",
    2: "Modern",
    3: "Commander",
    4: "Legacy",
    5: "Vintage",
    6: "Pauper",
    7: "Custom",
    8: "Frontier",
    9: "Future Standard",
    10: "Penny",
    11: "1v1 Commander",
    12: "Duel Commander",
    13: "Brawl",
    14: "Oathbreaker",
    15: "Pioneer",
    16: "Historic",
    17: "Pauper EDH",
    18: "Alchemy",
    19: "Explorer",
    20: "Historic Brawl",
    21: "Gladiator",
    22: "Premodern",
    23: "PreDH",
    24: "Timeless",
    25: "Canadian Highlander",
    26: "Competitive Brawl",
    27: "Tiny Leaders Reborn",
}


def extract_archidekt_deck_id(deck_id_or_url):
    match = re.search(r"archidekt\.com/decks/(\d+)", deck_id_or_url)
    if match:
        return match.group(1)
    return deck_id_or_url


def get_archidekt_deck(deck_id_or_url):
    deck_id = extract_archidekt_deck_id(deck_id_or_url)
    url = f"https://archidekt.com/api/decks/{deck_id}/"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to reach Archidekt: {e}")

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch deck {deck_id!r}: "
            f"HTTP {response.status_code} - {response.text}"
        )

    return response.json()


def search_archidekt_decks(commander_name=None, deck_name=None, page=1):
    url = "https://archidekt.com/api/decks/v3/"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    params = {
        "orderBy": "-viewCount",
        "page": page,
    }
    if commander_name is not None:
        params["commanderName"] = commander_name
    if deck_name is not None:
        params["name"] = deck_name

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to reach Archidekt: {e}")

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to search decks: "
            f"HTTP {response.status_code} - {response.text}"
        )

    return response.json()


def print_archidekt_deck(deck):
    print(f"Name: {deck.get('name')}")
    print(f"Format: {ARCHIDEKT_FORMATS.get(deck.get('deckFormat'), deck.get('deckFormat'))}")

    category_flags = {
        category.get("name"): category.get("includedInDeck", True)
        for category in deck.get("categories") or []
    }

    commanders = []
    mainboard = []
    for entry in deck.get("cards") or []:
        categories = entry.get("categories") or []
        name = entry.get("card", {}).get("oracleCard", {}).get("name", "Unknown")
        quantity = entry.get("quantity", 0)

        if "Commander" in categories:
            commanders.append(name)
            continue
        if categories and all(not category_flags.get(c, True) for c in categories):
            continue
        mainboard.append((quantity, name))

    if commanders:
        print(f"Commander(s): {', '.join(commanders)}")
    else:
        print("Commander(s): None")

    print("\nMainboard:")
    for quantity, name in mainboard:
        print(f"{quantity}x {name}")


def print_archidekt_search_results(results):
    for deck in results.get("results", []):
        print(f"Name: {deck.get('name')}")
        print(f"Format: {ARCHIDEKT_FORMATS.get(deck.get('deckFormat'), deck.get('deckFormat'))}")
        print(f"Views: {deck.get('viewCount')}")
        print(f"URL: https://archidekt.com/decks/{deck.get('id')}")
        print()


def main():
    commander_name = sys.argv[1] if len(sys.argv) > 1 else "Elenda, the Dusk Rose"

    print(f"=== Searching Archidekt for commander: {commander_name} ===")
    results = search_archidekt_decks(commander_name=commander_name)
    print_archidekt_search_results(results)

    first = results.get("results", [None])[0]
    if not first:
        print("No results found.")
        return

    print(f"=== Fetching first result: {first.get('name')} (id {first.get('id')}) ===")
    deck = get_archidekt_deck(str(first["id"]))
    print_archidekt_deck(deck)


if __name__ == "__main__":
    main()
