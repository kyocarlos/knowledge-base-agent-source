-- Canonical Integration v1 allows null project/case/task number and name.
-- KM's legacy *_code column names remain internal and are not wire aliases.
BEGIN;
ALTER TABLE km_csit_ingestion_jobs
  ALTER COLUMN project_code DROP NOT NULL,
  ALTER COLUMN project_name DROP NOT NULL,
  ALTER COLUMN case_code DROP NOT NULL,
  ALTER COLUMN case_name DROP NOT NULL,
  ALTER COLUMN task_code DROP NOT NULL,
  ALTER COLUMN task_name DROP NOT NULL;
COMMIT;
