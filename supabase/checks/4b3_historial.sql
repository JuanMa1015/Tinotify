-- Solo despues de confirmar existencia y SELECT en 4b3_preflight.sql.
-- No leer statements, nombres de operadores, fechas o texto de migraciones.
WITH previstas(version) AS (VALUES
    ('20261112050000'),('20261112160000'),('20261114010000'),('20261114020000')
), conteos AS (
    SELECT h.version,pg_catalog.count(*) AS veces
    FROM supabase_migrations.schema_migrations h
    GROUP BY h.version
)
SELECT pg_catalog.jsonb_build_object(
    'revision_informe',2,
    'versiones', (SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'version',p.version,'aplicaciones',coalesce(c.veces,0)) ORDER BY p.version)
        FROM previstas p LEFT JOIN conteos c ON c.version=p.version),
    'filas_no_previstas',coalesce((SELECT pg_catalog.sum(c.veces) FROM conteos c
        WHERE NOT EXISTS(SELECT 1 FROM previstas p WHERE p.version=c.version)),0),
    'orden_invalido',EXISTS(SELECT 1 FROM previstas p JOIN conteos c ON c.version=p.version
        WHERE EXISTS(SELECT 1 FROM previstas anterior WHERE anterior.version<p.version
            AND NOT EXISTS(SELECT 1 FROM conteos aplicado WHERE aplicado.version=anterior.version))),
    'limite','El historial no demuestra igualdad del SQL aplicado con Git; no se leen cuerpos ni se repara historial'
) AS historial_4b3;
