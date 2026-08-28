# WP1 Isolated Ingest Failure Reproduction & Failure-Window Capture Review

This isolated harness deliberately raised a synthetic parser failure. It is not connected to production and contains no user content or credentials.

The evidence chronology proves that worker receipt, exception details, terminal state, and failure capture occur before cleanup. Celery, ledger, and registry terminal states reconcile to failure, and cleanup returns residual count `0`.

This validates the diagnostic capture mechanism. It does not claim that the 2026-08-27 production ingest failure had the same parser cause.
