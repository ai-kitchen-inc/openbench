# DuckDB SQL for uploaded tables

Queries run against DuckDB, over tables loaded from the user's uploaded
files. The syntax is close to PostgreSQL.

## What is allowed

Only one read-only statement per call: `SELECT`, `WITH`, `DESCRIBE`,
`SUMMARIZE`, or `EXPLAIN`.

Everything else is rejected before the query runs — writes (`INSERT`,
`UPDATE`, `DELETE`, `CREATE`, `DROP`, `ALTER`), file and network access
(`COPY`, `ATTACH`, `INSTALL`, `LOAD`, `read_parquet`, `read_csv`, `glob`,
any `*_scan` function), settings changes (`SET`, `PRAGMA`), and multiple
statements separated by `;`. The connection itself has filesystem and
network access disabled, so there is no way to reach a file that is not
one of the user's own tables. Do not try — describe what you need
instead.

## Identifiers

Table and column names come from the source card. Quote them with double
quotes whenever they contain spaces, punctuation, or mixed case:

```sql
SELECT "Nilai Penjualan" FROM "penjualan_2024"
```

String literals use single quotes: `WHERE cabang = 'Bandung'`.

## Common shapes

Total by group, largest first:

```sql
SELECT cabang, SUM(nilai) AS total
FROM penjualan_2024
GROUP BY cabang
ORDER BY total DESC
```

Count matching rows:

```sql
SELECT COUNT(*) AS jumlah FROM penjualan_2024 WHERE nilai > 1000000
```

Top N:

```sql
SELECT * FROM penjualan_2024 ORDER BY nilai DESC LIMIT 10
```

Share of total:

```sql
SELECT cabang,
       SUM(nilai) AS total,
       100.0 * SUM(nilai) / SUM(SUM(nilai)) OVER () AS persen
FROM penjualan_2024
GROUP BY cabang
```

Join two sheets from the same workbook:

```sql
SELECT r.cabang, SUM(d.qty) AS unit
FROM ringkasan r
JOIN detail d ON d.cabang_id = r.id
GROUP BY r.cabang
```

## Dates

Date columns are typed. Use date functions rather than string matching:

```sql
SELECT date_trunc('month', tanggal) AS bulan, SUM(nilai) AS total
FROM penjualan_2024
GROUP BY bulan
ORDER BY bulan
```

`EXTRACT(year FROM tanggal)`, `EXTRACT(month FROM tanggal)`, and
`strftime(tanggal, '%Y-%m')` also work. When a date arrived as text, cast
it: `CAST(tanggal AS DATE)` or `strptime(tanggal, '%d/%m/%Y')`.

## Text

`LIKE` is case-sensitive; `ILIKE` is not. For loose matching, lower both
sides: `WHERE lower(cabang) LIKE '%bandung%'`.

## Nulls

Empty spreadsheet cells become `NULL`. `SUM` and `AVG` skip them, but
`COUNT(*)` does not — use `COUNT(column)` to count non-empty values, and
`COALESCE(column, 0)` when a null should read as zero.

## Limits

Results are capped by row count and by response size. A capped result is
flagged `truncated`. If you hit the cap, the query was probably too broad:
aggregate it or add a `LIMIT` with an explicit `ORDER BY`.

Queries also have a time limit. If one is interrupted, narrow it with a
`WHERE` clause or aggregate earlier.
