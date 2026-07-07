-- Row count of every user table in the connected database, as one ordered result.
--
-- pg_tables is enumerated at run time, so the report follows the live schema without edits as
-- migrations add or drop tables. The catalog query builds a single UNION ALL over each user table
-- and \gexec runs it; with no user tables string_agg yields NULL and \gexec is a no-op.
-- SELECT string_agg(
--          format('SELECT %L AS table_name, count(*) AS rows FROM %I.%I',
--                 schemaname || '.' || tablename, schemaname, tablename),
--          E'\nUNION ALL\n'
--          ORDER BY schemaname, tablename)
-- FROM pg_tables
-- WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
-- \gexec

-- Full contents of every non-empty user table, each result set preceded by a one-row banner naming
-- the table.
--
-- A first pass probes each user table with EXISTS and records the non-empty ones in a temp table, so
-- an empty table produces no banner or output at all. The probe skips session temp tables, so the
-- nonempty_table scaffolding never lists itself. The second pass then generates, per recorded table,
-- a banner SELECT and a TABLE statement (equivalent to SELECT *), ordered banner-first. \gexec
-- executes every cell of its input as a statement, so each generator projects a single column.
DROP TABLE IF EXISTS nonempty_table;
CREATE TEMP TABLE nonempty_table (schemaname text, tablename text);

SELECT format(
         'INSERT INTO nonempty_table SELECT %L, %L WHERE EXISTS (SELECT 1 FROM %I.%I)',
         schemaname, tablename, schemaname, tablename)
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND schemaname NOT LIKE 'pg_temp%'
\gexec

SELECT cmd
FROM (
  SELECT 0 AS ord, schemaname, tablename,
         format('SELECT %L AS table_name', schemaname || '.' || tablename) AS cmd
  FROM nonempty_table
  UNION ALL
  SELECT 1 AS ord, schemaname, tablename,
         format('TABLE %I.%I', schemaname, tablename)
  FROM nonempty_table
) gen
ORDER BY schemaname, tablename, ord
\gexec

DROP TABLE nonempty_table;
