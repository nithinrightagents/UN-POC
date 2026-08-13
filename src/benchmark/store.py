"""Benchmark set storage (FR-092).

Provides high-level store interface for labelled benchmark sets and ground truth labels.
Uses isolated BenchmarkRepository to prevent agent imports.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Sequence

from shared.state.entities import BenchmarkSet, GroundTruthAnswer, new_id
from shared.persistence.benchmark_repo import BenchmarkRepository


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
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        b_set = BenchmarkSet(set_id=set_id, name=set_name, labelled_by_class=True)
        labels = []
        for item in data.get("pairs", []):
            truth = GroundTruthAnswer(
                truth_id=new_id("gt"),
                set_id=set_id,
                question_id=item["question_id"],
                country_id=item["country_id"],
                correct_answer=item["correct_answer"],
                label_source=item.get("label_source", "published_survey"),
                assigned_by=item.get("assigned_by", "expert_assessor"),
                question_class=item.get("question_class", "default"),
            )
            labels.append(truth)

        self.save_set(b_set, labels)
        return b_set
