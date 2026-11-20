"""Rebuild the sentence difficulty ranking from saved pairwise votes (offline)."""

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import deque
from pathlib import Path

from deutsch.core import load_exercises


def compare(path, indices):
    matches = []
    pairs = set()
    with path.open(encoding="utf-8", newline="") as source:
        for line, row in enumerate(csv.DictReader(source, delimiter="\t"), 2):
            try:
                a, b = indices[row["sentence_a"]], indices[row["sentence_b"]]
                y = {"A": 1, "B": 0}[row["easier"]]
            except KeyError as exc:
                raise ValueError(f"{path}:{line}: unknown sentence ID or choice") from exc
            pair = (min(a, b), max(a, b))
            if a == b or pair in pairs:
                raise ValueError(f"{path}:{line}: self-comparison or repeated pair")
            pairs.add(pair)
            matches.append((a, b, y))
    return matches


def fit(matches, n):
    neighbors = [[] for _ in range(n)]
    for a, b, _ in matches:
        neighbors[a].append(b)
        neighbors[b].append(a)
    visited = {0}
    remaining = deque([0])
    while remaining:
        for other in neighbors[remaining.popleft()]:
            if other not in visited:
                visited.add(other)
                remaining.append(other)
    if not matches or len(visited) != n:
        raise ValueError("Comparison graph does not connect every sentence")

    # Bradley–Terry for ease, with an intercept for occupying position A.
    # A ridge penalty keeps the scores finite for unbeaten/unwinning sentences.
    ratings = [0.0] * n
    position_bias = 0.0
    for _ in range(450):
        gradient = [-0.75 * rating for rating in ratings]
        bias_gradient = 0.0
        for a, b, y in matches:
            z = ratings[a] - ratings[b] + position_bias
            residual = y - 1 / (1 + math.exp(-z))
            gradient[a] += residual
            gradient[b] -= residual
            bias_gradient += residual
        for i, delta in enumerate(gradient):
            ratings[i] += 0.17 * delta
        position_bias += 2.0 * bias_gradient / len(matches)
    return ratings, [len(group) for group in neighbors]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/exercises.json"))
    parser.add_argument("--comparisons", type=Path, default=Path("data/difficulty/comparisons.tsv"))
    parser.add_argument("--run", type=Path, default=Path("data/difficulty/run.json"))
    args = parser.parse_args()
    try:
        metadata = json.loads(args.run.read_text(encoding="utf-8"))
        if hashlib.sha256(args.data.read_bytes()).hexdigest() != metadata["deck_sha256"]:
            raise ValueError("Exercise file differs from the snapshot judged in this run")
        exercises = load_exercises(args.data)
        indices = {exercise.sentence_id: i for i, exercise in enumerate(exercises)}
        matches = compare(args.comparisons, indices)
        if len(matches) != metadata["primary_comparisons"]:
            raise ValueError("Comparison count does not match the run metadata")
        ratings, counts = fit(matches, len(exercises))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Error: {exc}\n")

    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(("hardest_rank", "sentence_id", "difficulty", "comparisons", "infinitive", "meaning", "italian"))
    order = sorted(range(len(exercises)), key=lambda i: (ratings[i], exercises[i].sentence_id))
    for rank, i in enumerate(order, 1):
        exercise = exercises[i]
        writer.writerow((rank, exercise.sentence_id, round(-ratings[i], 6), counts[i],
                         exercise.infinitive, exercise.meaning or "", exercise.italian))


if __name__ == "__main__":
    main()
