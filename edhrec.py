#!/usr/bin/env python3
import re
import sys

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

API_BASE_URL = "https://json.edhrec.com/pages"


def _slugify(name):
    # Matches the slug format used by json.edhrec.com's own frontend
    # (see edhrec-mcp by Raunak1571): lowercase, strip apostrophes/commas,
    # collapse any other run of non-alphanumeric characters to a hyphen.
    s = name.lower().strip()
    s = s.replace("'", "").replace("’", "").replace(",", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _get_edhrec_json(path):
    url = f"{API_BASE_URL}/{path}.json"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to reach EDHREC: {e}")

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch {path!r}: "
            f"HTTP {response.status_code} - {response.text}"
        )

    return response.json()


def get_edhrec_average_decklist(commander_name):
    slug = _slugify(commander_name)
    return _get_edhrec_json(f"average-decks/{slug}")


def get_edhrec_recommendations(commander_name):
    slug = _slugify(commander_name)
    return _get_edhrec_json(f"commanders/{slug}")


def print_edhrec_average_decklist(commander_name, data):
    deck = data.get("deck") or {}
    commanders = [name for name, _ in deck.get("commander_v2") or []]

    print(f"Average decklist for {commander_name}")
    print(f"Commander(s): {', '.join(commanders) if commanders else 'None'}")

    cards = deck.get("cards") or {}
    print("\nMainboard:")
    for category, card_list in cards.items():
        print(f"\n{category}:")
        for name, quantity in card_list:
            print(f"{quantity}x {name}")


def print_edhrec_recommendations(commander_name, data):
    cardlists = data.get("container", {}).get("json_dict", {}).get("cardlists", [])

    print(f"Recommendations for {commander_name}")
    for section in cardlists:
        header = section.get("header", "Cards")
        cards = section.get("cardviews", [])
        if not cards:
            continue
        print(f"\n{header}:")
        for card in cards:
            name = card.get("name", "Unknown")
            inclusion = card.get("inclusion")
            potential = card.get("num_decks")
            if inclusion and potential:
                print(f"{name} ({inclusion}/{potential} decks)")
            else:
                print(name)


def main():
    commander_name = sys.argv[1] if len(sys.argv) > 1 else "Elenda, the Dusk Rose"

    print(f"=== Average decklist ===")
    decklist_data = get_edhrec_average_decklist(commander_name)
    print_edhrec_average_decklist(commander_name, decklist_data)

    print(f"\n=== Recommendations ===")
    recs_data = get_edhrec_recommendations(commander_name)
    print_edhrec_recommendations(commander_name, recs_data)


if __name__ == "__main__":
    main()
