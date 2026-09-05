"""Benchmark set storage (FR-092).

Provides high-level store interface for labelled benchmark sets and ground truth labels.
Uses isolated BenchmarkRepository to prevent agent imports.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from shared.persistence.benchmark_repo import BenchmarkRepository
from shared.state.entities import BenchmarkSet, GroundTruthAnswer, new_id


class BenchmarkStore:
    def __init__(self, conn: sqlite3.Connection):
        self.repo = BenchmarkRepository(conn)

    def save_set(self, benchmark_set: BenchmarkSet, labels: Sequence[GroundTruthAnswer]) -> None:
        """Save a benchmark set and all its ground truth answers."""
        if not self.repo.get_set(benchmark_set.set_id):
            self.repo.insert_set(benchmark_set)
        for label in labels:
            if not label.truth_id:
                label.truth_id = new_id("gt")
            self.repo.insert_ground_truth(label)

    def get_set(self, set_id: str) -> BenchmarkSet | None:
        return self.repo.get_set(set_id)

    def get_ground_truth(self, set_id: str, question_id: str, country_id: str) -> GroundTruthAnswer | None:
        return self.repo.get_ground_truth(set_id, question_id, country_id)

    def list_ground_truth(self, set_id: str) -> list[GroundTruthAnswer]:
        return self.repo.list_ground_truth(set_id)

    def load_from_json(self, json_path: str | Path, set_id: str, set_name: str) -> BenchmarkSet:
        """Load benchmark set from a JSON file."""
        path = Path(json_path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        b_set = BenchmarkSet(set_id=set_id, name=set_name, labelled_by_class=True)
        labels = []
        raw_items = data.get("entries") or data.get("pairs", [])
        for item in raw_items:
            correct_ans = item.get("expected_answer") if "expected_answer" in item else item.get("correct_answer")
            truth = GroundTruthAnswer(
                truth_id=new_id("gt"),
                set_id=set_id,
                question_id=item["question_id"],
                country_id=item["country_id"],
                correct_answer=correct_ans,
                label_source=item.get("label_source", item.get("origin", "published_survey")),
                assigned_by=item.get("assigned_by", "expert_assessor"),
                question_class=item.get("question_class", "default"),
                reference_url=item.get("reference_url"),
                no_valid_link=item.get("no_valid_link", False),
                accepted_alternatives=item.get("accepted_alternatives", []),
                confidence=item.get("confidence", "authoritative"),
                verified_on=item.get("verified_on"),
                origin=item.get("origin"),
                note=item.get("note"),
            )
            labels.append(truth)

        self.save_set(b_set, labels)
        return b_set
