import argparse
import json
import random
import sys
from pathlib import Path

from openai import OpenAIError


def _practice_files(parser) -> None:
    parser.add_argument("--data", type=Path, default=Path("data/exercises.json"))
    parser.add_argument("--log", type=Path, default=Path("data/guesses.jsonl"))
    parser.add_argument("--events", type=Path, help="Presentation events (default: next to --log, <stem>.events.jsonl)")
    parser.add_argument("--vocabulary", type=Path, default=Path("data/vocabulary.json"))
    parser.add_argument("--frequencies", type=Path, default=Path("data/frequencies.json"))


def _scheduler_options(parser) -> None:
    parser.add_argument("--new-ratio", type=float, default=0.2, help="Target share of new words (default: 0.2)")
    parser.add_argument("--cooldown", type=int, default=5, help="Avoid the last N words (default: 5)")
    parser.add_argument("--new-window", type=int, default=100, help="Introduce from the N most frequent unseen words (default: 100)")


def _load_practice(data: Path, vocabulary: Path):
    from deutsch.core import load_exercises
    from deutsch.vocabulary import audit_vocabulary, load_vocabulary
    if not data.exists():
        raise ValueError("No exercises yet. Check missing pairs with: uv run deutsch check-vocabulary")
    exercises, entries = load_exercises(data), load_vocabulary(vocabulary)
    errors = audit_vocabulary(entries, exercises).errors
    if errors:
        raise ValueError("; ".join(errors))
    return exercises, entries


def _adaptive_inputs(args, exercises, entries):
    from deutsch.frequencies import load_frequencies
    from deutsch.history import load_history
    if not args.frequencies.exists():
        raise ValueError("No frequency data. Build it with: uv run --extra frequency deutsch build-frequencies")
    frequencies = load_frequencies(args.frequencies)
    history = load_history(args.log, args.events)
    blocked = {entry.word_id for entry in entries if entry.review_note}
    filtered = [exercise for exercise in exercises if exercise.word_id not in blocked]
    excluded = len({exercise.word_id for exercise in exercises} & blocked)
    warnings = list(history.warnings)
    if excluded:
        warnings.append(f"Excluded {excluded} words flagged for lexical review from adaptive selection.")
    stale = {exercise.word_id for exercise in filtered
             if exercise.word_id not in frequencies.words or
             frequencies.words[exercise.word_id].infinitive != exercise.infinitive}
    if stale:
        warnings.append(f"{len(stale)} eligible words have absent/stale frequency records; using minimum weight. Rebuild frequencies after vocabulary edits.")
    return filtered, frequencies, history, warnings, excluded


def _show_warnings(warnings) -> None:
    for warning in warnings[:5]:
        print(f"Warning: {warning}", file=sys.stderr)
    if len(warnings) > 5:
        print(f"Warning: {len(warnings) - 5} additional warnings (see recommend --json).", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deutsch · German vocabulary for Italian speakers")
    sub = parser.add_subparsers(dest="command")
    play = sub.add_parser("play", help="Inline vocabulary practice (default; random mode)")
    web = sub.add_parser("web", help="Open the simple localhost browser UI")
    for practice in (play, web):
        _practice_files(practice)
        _scheduler_options(practice)
        practice.add_argument("--mode", choices=["random", "adaptive"], default="random")
        practice.add_argument("--threshold", type=int, default=1, help="Almost-there edit distance (default: 1)")
        practice.add_argument("--explain", action="store_true", help="Explain adaptive choices without revealing the answer")
        practice.add_argument("--seed", type=int, help="Reproducible adaptive selection")
        practice.add_argument("--alternative-log", type=Path, help="Private review flags (default: next to --log, <stem>.alternatives.jsonl)")
    web.add_argument("--port", type=int, default=8765, help="Local port (default: 8765; 0 picks a free port)")
    web.add_argument("--open", action="store_true", help="Open the local page in your browser")
    recommend = sub.add_parser("recommend", help="Inspect adaptive recommendations offline (no writes)")
    _practice_files(recommend)
    _scheduler_options(recommend)
    recommend.add_argument("--limit", type=int, default=20)
    recommend.add_argument("--simulate", type=int, default=0, help="Sample N selections against frozen history (no invented answers)")
    recommend.add_argument("--seed", type=int, default=42)
    recommend.add_argument("--json", action="store_true")
    frequency = sub.add_parser("build-frequencies", help="Build local frequency metadata from public corpora (one-time downloads)")
    frequency.add_argument("--vocabulary", type=Path, default=Path("data/vocabulary.json"))
    frequency.add_argument("--output", type=Path, default=Path("data/frequencies.json"))
    frequency.add_argument("--cache", type=Path, default=Path(".cache/deutsch-frequency"))
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
        elif args.command == "build-frequencies":
            if args.output.resolve() == args.vocabulary.resolve():
                parser.error("Frequency output must not overwrite the canonical vocabulary")
            from collections import Counter
            from deutsch.frequencies import build_frequencies
            from deutsch.vocabulary import load_vocabulary
            table = build_frequencies(load_vocabulary(args.vocabulary), args.output, args.cache)
            print(f"Saved {len(table.words)} frequency records to {args.output} ({table.corpus_tokens} corpus word tokens)")
            print(json.dumps(dict(Counter(item.method for item in table.words.values()))))
        else:
            from deutsch.tui import DeutschApp
            from deutsch.frequencies import load_frequencies
            if args.command is None:
                # No subcommand keeps the existing default random interaction.
                exercises, _ = _load_practice(Path("data/exercises.json"), Path("data/vocabulary.json"))
                frequency_path = Path("data/frequencies.json")
                frequencies = load_frequencies(frequency_path) if frequency_path.exists() else None
                DeutschApp(exercises, Path("data/guesses.jsonl"), frequencies=frequencies).run()
                return
            if args.events is not None and args.events.resolve() == args.log.resolve():
                parser.error("--events and --log must use different paths")
            if not 0 <= args.new_ratio <= 1 or args.cooldown < 0 or args.new_window < 1:
                parser.error("--new-ratio must be between 0 and 1, --cooldown nonnegative, --new-window positive")
            if args.command in {"play", "web"} and args.threshold < 0:
                parser.error("--threshold must be nonnegative")
            if args.command in {"play", "web"} and args.explain and args.mode != "adaptive":
                parser.error("--explain requires --mode adaptive")
            if args.command == "recommend" and (args.limit < 1 or args.simulate < 0):
                parser.error("--limit must be positive and --simulate nonnegative")
            if args.command == "web" and not 0 <= args.port <= 65535:
                parser.error("--port must be between 0 and 65535")
            exercises, entries = _load_practice(args.data, args.vocabulary)
            options = dict(new_ratio=args.new_ratio, cooldown=args.cooldown, new_window=args.new_window)
            if args.command == "web":
                from deutsch.web import WebConfig, serve
                frequencies = load_frequencies(args.frequencies) if args.frequencies.exists() else None
                config = WebConfig(exercises, entries, args.log, frequencies=frequencies,
                                   events_path=args.events, alternative_log=args.alternative_log,
                                   default_mode=args.mode, threshold=args.threshold, seed=args.seed,
                                   explain=args.explain, **options)
                serve(config, port=args.port, open_browser=args.open)
                return
            if args.command == "recommend" or args.mode == "adaptive":
                from deutsch.scheduler import AdaptiveDeck, offline_report
                exercises, frequencies, history, warnings, excluded = _adaptive_inputs(args, exercises, entries)
                if args.command == "recommend":
                    report = offline_report(exercises, frequencies, history, limit=args.limit,
                                            samples=args.simulate, seed=args.seed, **options)
                    report["warnings"], report["excluded_review_words"] = warnings, excluded
                    report["frequency_built_at"] = frequencies.built_at
                    if args.json:
                        print(json.dumps(report, ensure_ascii=False, indent=2))
                    else:
                        _show_warnings(warnings)
                        print(f"Adaptive preview · {report['seen_words']} seen / {report['eligible_words']} eligible words")
                        print("Approximate mastery, not a calibrated probability. Legacy retries are grouped, not counted as new successes.")
                        for row in report["recommendations"]:
                            print(f"{row['infinitive']:20} {row['bucket']:6} next {row['next_probability']:6.2%} · mastery {row['mastery_estimate']:.0%} · Zipf {row['zipf']:.2f}")
                            print(f"  {row['reason']}")
                        if args.simulate:
                            print(f"Frozen-history simulation ({args.simulate} selections): {report['simulation']['buckets']}")
                            print(report['simulation']['note'])
                    return
                _show_warnings(warnings)
                deck = AdaptiveDeck(exercises, frequencies, history, rng=random.Random(args.seed), **options)
            else:
                deck = None
                frequencies = load_frequencies(args.frequencies) if args.frequencies.exists() else None
            DeutschApp(exercises, args.log, args.threshold, deck=deck, frequencies=frequencies,
                       events_path=args.events, explain=args.explain, alternative_log=args.alternative_log).run()
    except (ValueError, OSError, OpenAIError) as error:
        parser.exit(2 if args.command == "check-vocabulary" else 1, f"Error: {error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "\nStopped. Completed generation batches are saved.\n")
