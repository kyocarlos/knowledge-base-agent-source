-- CI/isolated deployment may substitute the password through a controlled
-- provisioning step.  No password is stored in this repository.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'km_ts_readonly') THEN
        CREATE ROLE km_ts_readonly NOLOGIN;
    END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO km_ts_readonly;
GRANT SELECT ON test_run, metric_sample, test_run_summary TO km_ts_readonly;
