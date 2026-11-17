"""Usage: uv run python scripts/import_authored.py data/authored*.tsv"""
import argparse
from pathlib import Path

from deutsch.content import import_authored

parser = argparse.ArgumentParser(description="Import directly authored exercises, offline")
parser.add_argument("sources", type=Path, nargs="+")
parser.add_argument("--vocabulary", "--verbs", dest="vocabulary", type=Path,
                    default=Path("data/vocabulary.json"), help="Canonical JSON list (legacy CSV also accepted)")
parser.add_argument("--output", type=Path, default=Path("data/exercises.json"))
args = parser.parse_args()
try:
    count = import_authored(args.sources, args.vocabulary, args.output)
except (ValueError, OSError) as error:
    parser.exit(1, f"Error: {error}\n")
print(f"Imported {count} exercises into {args.output}. No API calls.")
