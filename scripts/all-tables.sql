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

-- Contents of every non-empty user table, each result set preceded by a one-row banner naming the
-- table. Knowledge-base payloads are omitted: kb_chunk holds split text plus embedding vectors, and
-- bytea columns (kb_document.content carries the uploaded file) are dropped from every projection,
-- since neither renders usefully in a terminal.
--
-- A first pass probes each user table with EXISTS and records the non-empty ones in a temp table, so
-- an empty table produces no banner or output at all. The probe skips session temp tables, so the
-- nonempty_table scaffolding never lists itself. The second pass then generates, per recorded table,
-- a banner SELECT and a SELECT over its readable columns, ordered banner-first. \gexec executes
-- every cell of its input as a statement, so each generator projects a single column.
DROP TABLE IF EXISTS nonempty_table;
CREATE TEMP TABLE nonempty_table (schemaname text, tablename text);

SELECT format(
         'INSERT INTO nonempty_table SELECT %L, %L WHERE EXISTS (SELECT 1 FROM %I.%I)',
         schemaname, tablename, schemaname, tablename)
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND schemaname NOT LIKE 'pg_temp%'
  AND tablename <> 'kb_chunk'
\gexec

SELECT cmd
FROM (
  SELECT 0 AS ord, schemaname, tablename,
         format('SELECT %L AS table_name', schemaname || '.' || tablename) AS cmd
  FROM nonempty_table
  UNION ALL
  SELECT 1 AS ord, t.schemaname, t.tablename,
         format('SELECT %s FROM %I.%I', readable.cols, t.schemaname, t.tablename)
  FROM nonempty_table t
  JOIN LATERAL (
    SELECT string_agg(quote_ident(attname), ', ' ORDER BY attnum) AS cols
    FROM pg_attribute
    WHERE attrelid = format('%I.%I', t.schemaname, t.tablename)::regclass
      AND attnum > 0
      AND NOT attisdropped
      AND atttypid <> 'bytea'::regtype
  ) readable ON true
) gen
ORDER BY schemaname, tablename, ord
\gexec

DROP TABLE nonempty_table;
