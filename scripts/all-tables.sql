-- Row count of every user table in the connected database, as one ordered result.
--
-- pg_tables is enumerated at run time, so the report follows the live schema without edits as
-- migrations add or drop tables. The catalog query builds a single UNION ALL over each user table
-- and \gexec runs it; with no user tables string_agg yields NULL and \gexec is a no-op.
SELECT string_agg(
         format('SELECT %L AS table_name, count(*) AS rows FROM %I.%I',
                schemaname || '.' || tablename, schemaname, tablename),
         E'\nUNION ALL\n'
         ORDER BY schemaname, tablename)
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
\gexec
