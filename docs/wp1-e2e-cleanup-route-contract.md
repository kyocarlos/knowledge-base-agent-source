# WP1 E2E Cleanup Route Contract

The cleanup API is a separately scoped, disabled-by-default endpoint for
temporary E2E data. It is enabled only by the protected runtime overlay and
requires the cleanup identity plus bearer credential.

Cleanup is restricted to the configured E2E run-ID prefix. The implementation
removes only records, task state, files, vector points, and graph nodes owned by
that run. Production identities and historical runs are outside the contract.

The route and its registry helpers are shipped together with the candidate
image. Missing route registration or missing run-scoped registry operations is
a candidate packaging failure, not a reason to bypass cleanup.
