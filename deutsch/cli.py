import argparse
import json
from pathlib import Path

from openai import OpenAIError


def main() -> None:
    parser = argparse.ArgumentParser(description="Deutsch · German vocabulary for Italian speakers")
    sub = parser.add_subparsers(dest="command")
    play = sub.add_parser("play", help="Open the terminal UI (default)")
    play.add_argument("--data", type=Path, default=Path("data/exercises.json"))
    play.add_argument("--log", type=Path, default=Path("data/guesses.jsonl"))
    play.add_argument("--threshold", type=int, default=1, help="Almost-there edit distance (default: 1)")
    play.add_argument("--vocabulary", type=Path, default=Path("data/vocabulary.json"))
    gen = sub.add_parser("generate", help="Generate and cache exercises using gpt-6-luna")
    gen.add_argument("--count", type=int, default=50)
    gen.add_argument("--output", type=Path, default=Path("data/exercises.json"))
    gen.add_argument("--vocabulary", type=Path, default=Path("data/vocabulary.json"))
    check = sub.add_parser("check-vocabulary", help="Check vocabulary/sentence coverage offline (no writes)")
    check.add_argument("--vocabulary", type=Path, default=Path("data/vocabulary.json"))
    check.add_argument("--data", type=Path, default=Path("data/exercises.json"))
    check.add_argument("--json", action="store_true", help="Print the full machine-readable report")
    args = parser.parse_args()
    try:
        if args.command == "check-vocabulary":
            from deutsch.vocabulary import check_vocabulary
            report = check_vocabulary(args.vocabulary, args.data)
            if args.json:
                print(json.dumps(report.model_dump(exclude_none=True), ensure_ascii=False, indent=2))
            else:
                print(f"Vocaboli coperti: {report.covered_word_count}/{report.vocabulary_count} · frasi: {report.sentence_count}")
                print(f"Senza frasi: {len(report.missing_words)} · significati scoperti: {len(report.missing_meanings)} · errori: {len(report.errors)}")
                for entry in report.missing_words[:10]:
                    note = f" [da verificare: {entry.review_note}]" if entry.review_note else ""
                    print(f"  {entry.word_id}: {entry.infinitive}{note}")
                for missing in report.missing_meanings[:10]:
                    print(f"  {missing.word_id}: significato mancante: {missing.meaning}")
                for error in report.errors[:10]:
                    print(f"  Errore: {error}")
                if len(report.missing_words) > 10 or len(report.missing_meanings) > 10 or len(report.errors) > 10:
                    print("Report completo: uv run deutsch check-vocabulary --json")
            if not report.complete:
                parser.exit(2 if report.errors else 1)
        elif args.command == "generate":
            if args.count < 1:
                parser.error("--count must be positive")
            from deutsch.generate import generate
            generate(args.output, args.count, vocabulary=args.vocabulary)
        else:
            from deutsch.core import load_exercises
            from deutsch.tui import DeutschApp
            from deutsch.vocabulary import audit_vocabulary, load_vocabulary
            data = getattr(args, "data", Path("data/exercises.json"))
            log = getattr(args, "log", Path("data/guesses.jsonl"))
            threshold = getattr(args, "threshold", 1)
            if threshold < 0:
                parser.error("--threshold must be nonnegative")
            if not data.exists():
                parser.exit(1, "No exercises yet. Check missing pairs with: uv run deutsch check-vocabulary\n")
            exercises = load_exercises(data)
            entries = load_vocabulary(getattr(args, "vocabulary", Path("data/vocabulary.json")))
            errors = audit_vocabulary(entries, exercises).errors
            if errors:
                raise ValueError("; ".join(errors))
            DeutschApp(exercises, log, threshold).run()
    except (ValueError, OSError, OpenAIError) as error:
        parser.exit(2 if args.command == "check-vocabulary" else 1, f"Error: {error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "\nStopped. Completed generation batches are saved.\n")
