# Integration of the DA40 runtime code into main (2026-11-16)

Base: origin/main at 47daf4d. Source of the production side: the code files running in kb-web, km-da40-web-1, kb-celery-search, kb-celery-ingest and km-da40-celery_ingest_worker-1
(see branch agent/runtime-snapshot-20261116, runtime-snapshot/20261116/manifest.json). Nothing was deployed; no container or setting was changed.

Method: for every production file, the nearest git version is the common ancestor; main and production are merged three-way (line endings normalised to LF).

| Result | Files |
|---|---|
| Production only, main unchanged since the base: production taken | keeper/routing.py, keeper/zones.json, web_api/keeper_routes.py (the 11/12 keeper fix), web_api/tasks.py, config/report-ingest.env.example |
| Both changed, merged without conflict | ingest.py, oidc_control.py, report_numeric/vector.py |
| Both changed, conflict resolved by hand | report_numeric/parser.py, graph.py, timescale.py: main kept (it contains all of production changes and more); config/csit-integration-v1.env.example: both blocks kept; config/wp01-deployment.env.example: KB_ASSETS_ROOT added, main removal of the staging line kept; web_api/__init__.py: router registrations of both sides kept (csit_assistant and RCA included), session key stays out of the chat log line (production) and the CSIT read-only shortcut after it stays (main) |
| Not in main, added from production | report_numeric/rca.py, rca_service.py, compare.py; web_api/rca_routes.py, rca_tasks.py; config/csit-doclib-v1.env.example, csit-doclib-vocabulary.json, km-control-auth.env.example, three nginx-km-dev-*.conf |
| Not in main, identical to a commit on another branch | report_numeric/findings.py (c732460), web_api/csit_assistant_routes.py, csit_assistants.py, csit_assistants.json (2801f47) |
| Production is an older version of a file main already has | main kept (report_numeric/chunks.py, metric_dictionary.json, query.py, schema.sql and the files identical in content) |

Not copied: config/config.yaml*, config/*.env, backups, keys (may hold credentials).

Checked: every changed Python file compiles; the whole tests/ suite gives the same failures as main (99 failed / 83 errors on main, 98 / 83 here; they need services and data the test image does not have) and one more test passes.
Not checked: the web application was not started with this tree, and tests/zone_pages cannot be collected in the test image, so web routes are not covered. Run a smoke test on the web image before any deployment.
