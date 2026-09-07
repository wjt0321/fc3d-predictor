#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""福彩3D预测器优化后的回归测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from fc3d_predictor import (
    DEFAULT_EXPERT_WEIGHTS,
    FC3DRecord,
    backtest,
    generate_joint_scores,
    predict,
)


class TestJointProbability(unittest.TestCase):
    def setUp(self):
        self.records = [
            FC3DRecord(str(2026000 - i), f"2026-01-{(20 - i % 20):02d}", [i % 10, (i + 2) % 10, (i + 4) % 10])
            for i in range(60)
        ]

    def test_joint_scores_cover_all_numbers_with_positive_finite_probability(self):
        scores = generate_joint_scores(self.records)
        self.assertEqual(len(scores), 1000)
        self.assertTrue(all(value > 0 for value in scores.values()))
        self.assertTrue(all(value < float("inf") for value in scores.values()))
        self.assertAlmostEqual(sum(scores.values()), 1.0, places=8)


class TestModes(unittest.TestCase):
    def setUp(self):
        data_path = Path("fc3d_data.json")
        raw = json.loads(data_path.read_text(encoding="utf-8"))
        self.records = [
            FC3DRecord(str(r["period"]), str(r["date"]), list(r["digits"]))
            for r in raw["records"][:550]
        ]

    def test_default_random_expert_is_disabled(self):
        self.assertEqual(DEFAULT_EXPERT_WEIGHTS["random"], 0.0)

    def test_exact_and_coverage_return_unique_requested_tickets(self):
        for mode in ("exact", "coverage"):
            results, _, _ = predict(self.records, num=5, seed=42, mode=mode)
            self.assertEqual(len(results), 5)
            self.assertEqual(len({r.number for r in results}), 5)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            predict(self.records, num=5, mode="unknown")


class TestBacktest(unittest.TestCase):
    def setUp(self):
        data_path = Path("fc3d_data.json")
        raw = json.loads(data_path.read_text(encoding="utf-8"))
        self.records = [
            FC3DRecord(str(r["period"]), str(r["date"]), list(r["digits"]))
            for r in raw["records"][:80]
        ]

    def test_backtest_accepts_weights_and_mode_and_reports_honest_metrics(self):
        result = backtest(
            self.records,
            cycles=3,
            num=2,
            seed=42,
            weights={"random": 0.0},
            mode="exact",
        )
        self.assertEqual(result["cycles"], 3)
        self.assertIn("position_hit_rate", result)
        self.assertIn("avg_coverage_size", result)
        self.assertIn("position_hits", result["details"][0])
        self.assertIn("coverage_size", result["details"][0])
        self.assertIn("random_baseline", result)
        self.assertAlmostEqual(result["random_baseline"]["exact_match_rate"], 0.002, places=8)
        self.assertGreater(result["random_baseline"]["avg_coverage_size"], 4.0)
        self.assertLess(result["random_baseline"]["avg_coverage_size"], 7.0)

    def test_partial_weight_patch_keeps_unspecified_defaults(self):
        default_result = backtest(self.records, cycles=3, num=2, seed=42, mode="exact")
        explicit_result = backtest(
            self.records, cycles=3, num=2, seed=42,
            weights={"random": 0.0}, mode="exact"
        )
        self.assertEqual(
            default_result["details"][0]["predictions"],
            explicit_result["details"][0]["predictions"],
        )


if __name__ == "__main__":
    unittest.main()
