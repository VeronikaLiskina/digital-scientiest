-- Перед alembic upgrade head можно проверить, есть ли дубли после нормализации.

SELECT regexp_replace(lower(trim(replace(full_name, 'ё', 'е'))), '\s+', ' ', 'g') AS normalized_name,
       COUNT(*)
FROM authors
GROUP BY normalized_name
HAVING COUNT(*) > 1;

SELECT regexp_replace(lower(trim(replace(name, 'ё', 'е'))), '\s+', ' ', 'g') AS normalized_name,
       COUNT(*)
FROM keywords
GROUP BY normalized_name
HAVING COUNT(*) > 1;

SELECT regexp_replace(lower(trim(replace(name, 'ё', 'е'))), '\s+', ' ', 'g') AS normalized_name,
       COUNT(*)
FROM topics
GROUP BY normalized_name
HAVING COUNT(*) > 1;
