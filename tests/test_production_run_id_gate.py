from __future__ import annotations

import json
import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from production_run_id_gate import check_unique_production_run_id, check_unique_run_id, collect_prior_production_run_ids


PREFIX = "TR-E2E-WP1-PROD-"


class ProductionRunIdGateTests(unittest.TestCase):
  def test_new_run_id_passes_without_network_or_write(self):
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
      tmp_path = Path(directory)
      (tmp_path / "production-acceptance-old.json").write_text(
        json.dumps({"run_id": PREFIX + "old", "production_touched": True}), encoding="utf-8"
      )
      result = check_unique_production_run_id(PREFIX + "new", tmp_path)
      self.assertEqual(result["run_id_uniqueness_gate"], "PASS")
      self.assertFalse(result["network_or_write_started"])

  def test_reused_production_run_id_fails_closed(self):
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
      tmp_path = Path(directory)
      (tmp_path / "production-acceptance-old.json").write_text(
        json.dumps({"run_id": PREFIX + "reused", "production_touched": True}), encoding="utf-8"
      )
      with self.assertRaisesRegex(ValueError, "FAIL"):
        check_unique_production_run_id(PREFIX + "reused", tmp_path)

  def test_isolated_evidence_is_not_counted_as_production(self):
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
      tmp_path = Path(directory)
      (tmp_path / "isolated.json").write_text(
        json.dumps({"run_id": PREFIX + "isolated", "production_touched": False}), encoding="utf-8"
      )
      self.assertEqual(collect_prior_production_run_ids(tmp_path), set())

  def test_invalid_run_id_fails_before_scan(self):
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
      with self.assertRaisesRegex(ValueError, "format"):
        check_unique_production_run_id("stale-run", Path(directory))

  def test_isolated_run_id_passes_only_in_isolated_mode(self):
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
      isolated = "TR-E2E-WP1-GATEB-ISOLATED-new"
      result = check_unique_run_id(isolated, Path(directory), "isolated")
      self.assertEqual(result["run_id_uniqueness_gate"], "PASS")
      with self.assertRaisesRegex(ValueError, "production E2E format"):
        check_unique_run_id(isolated, Path(directory), "production")

  def test_production_run_id_rejected_in_isolated_mode(self):
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
      with self.assertRaisesRegex(ValueError, "isolated E2E format"):
        check_unique_run_id(PREFIX + "wrong-mode", Path(directory), "isolated")

  def test_reused_isolated_run_id_fails_closed(self):
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
      tmp_path = Path(directory)
      run_id = "TR-E2E-WP1-GATEB-ISOLATED-reused"
      (tmp_path / "isolated-result.json").write_text(json.dumps({"run_id": run_id, "production_touched": False}), encoding="utf-8")
      with self.assertRaisesRegex(ValueError, "FAIL"):
        check_unique_run_id(run_id, tmp_path, "isolated")


if __name__ == "__main__":
  unittest.main()
