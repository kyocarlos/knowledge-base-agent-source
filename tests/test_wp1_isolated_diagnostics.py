from __future__ import annotations

from dataclasses import dataclass
import unittest


@dataclass
class SyntheticTask:
    state: str = "queued"
    receipt_logged: bool = False
    exception: str | None = None


def run_failure_capture() -> tuple[SyntheticTask, list[str]]:
    task = SyntheticTask()
    chronology = ["fixture_preflight", "dispatch"]
    task.receipt_logged = True
    chronology.append("worker_receipt")
    task.state = "failed"
    task.exception = "SyntheticIngestFailure"
    chronology.extend(("exception", "terminal_state", "capture", "cleanup"))
    return task, chronology


def classify_cleanup(backend_available: bool, ingest_failed: bool) -> str:
    if not backend_available:
        return "INDEPENDENT_CLEANUP_BACKEND_FAILURE"
    if ingest_failed:
        return "NOT_SECONDARY_TO_INGEST"
    return "CLEANUP_SUCCESS"


class IsolatedDiagnosticsTests(unittest.TestCase):
  def test_failure_capture_precedes_cleanup_and_reconciles_state(self):
    task, chronology = run_failure_capture()
    self.assertLess(chronology.index("capture"), chronology.index("cleanup"))
    self.assertTrue(task.receipt_logged)
    self.assertEqual(task.state, "failed")
    self.assertEqual(task.exception, "SyntheticIngestFailure")

  def test_cleanup_503_is_independent_of_ingest_failure(self):
    self.assertEqual(classify_cleanup(False, True), "INDEPENDENT_CLEANUP_BACKEND_FAILURE")
    self.assertEqual(classify_cleanup(True, True), "NOT_SECONDARY_TO_INGEST")

  def test_successful_cleanup_is_available_after_backend_recovery(self):
    self.assertEqual(classify_cleanup(True, False), "CLEANUP_SUCCESS")


if __name__ == "__main__":
  unittest.main()
