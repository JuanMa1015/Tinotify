# 4B.1: núcleo PostgreSQL cerrado, pendiente de ejecución

Preparación local sobre feat/postgresql-supabase, base 825f8d7. No se ha ejecutado
SQL ni consultado el proyecto remoto. El parser aprobado permanece en la rama
codex/corregir-parser-sigac, commit 526f01b; no se fusiona ni se modifica aquí.
Esta rama conserva las 241 pruebas de backend anteriores a ese parser.

El diseño docs/etapa-4b.md permanece sin seguimiento y byte a byte intacto, con
respaldo externo al repositorio verificado antes del cambio de rama. Esta entrega
concreta su núcleo de ocho tablas; el bloque de observaciones futuro NO se migra.
Las secciones del borrador sobre parser son contexto histórico, no cambios en 4B.1.

## Archivos y alcance

- supabase/migrations/20261112160000_crear_nucleo_reconciliacion.sql: SQL completo,
  posterior a 20261112050000. La migración aplicada de 4A conserva su hash.
- supabase/tests/4b1_integridad.sql: pruebas PostgreSQL futuras con rollback.
- supabase/tests/4b1_concurrencia_{preparar,a,b,limpiar}.sql: dos conexiones reales
  para verificar bloqueo y unicidad. Preparación/limpieza requieren escritura
  confirmada y autorización separada; no están ejecutadas.
- supabase/tests/4b1_btree_limites.sql: ensayo de valores máximos con rollback,
  aún sin ejecutar. No instala extensiones ni modifica tipos/almacenamiento.
- backend/tests/test_postgresql_ddl.py: comprobaciones estáticas y del contrato
  Python real. No conecta, no emula PostgreSQL ni implementa un adaptador.

No funciones SECURITY DEFINER, políticas permisivas, GRANT de negocio, API,
adaptador SQL, integración SIGAC, cuentas Auth o datos iniciales. El monitor,
formato JSON v2.2, parser y reconciliación permanecen intactos.

## Ocho tablas definitivas del núcleo

| Tabla | Autoridad y relaciones |
| --- | --- |
| app.estudiantes | Perfil mínimo; auth_subject opcional y único hacia auth.users. Borrar Auth desvincula, no purga seguimiento automáticamente. |
| app.estados_reconciliacion | Cabecera por estudiante/instancia/época; revisión de estado 2, huella 1, política y flag migrated_from_v1. |
| app.expedientes | FK compuesta al estudiante/cabecera; clave de caso exacta, inclusión, generación y fencing. |
| app.actuaciones | UUID local, orden, status y huella actual; FK compuesta al caso y alcances exactos hacia cabecera/caso. |
| app_private.accesos_sigac | Estado de comprobación y épocas de sesión/acceso por estudiante/caso; no concesión institucional autosuficiente. |
| app_private.sincronizaciones | Idempotencia, reserva y generación por estudiante/caso; solo una fila reservada/ejecutando. |
| app.eventos | Tipo y prioridad mínimos; FK compuestas al trabajo y registro del mismo estudiante/caso, sin contenido jurídico. |
| app_private.importaciones | Recibo idempotente por estudiante, digest/tamaño y cabecera de resultado; no copia mutable del JSON. |

versiones_actuacion y observaciones se posponen: no existen en el estado JSON.
El estado actual no tiene doble autoridad. Las ausencias no se borran por DDL.
Todas las FK de seguimiento son NO ACTION. No hay ciclos; solo la unicidad de
orden de actuaciones es diferible, con nombre actuaciones_orden_uq.

La identidad estable del código es clave/versión/revisión del CONTRATO + instancia
+ caso + source_id. Las FK fijan alcance; el índice único incluye contrato/source_id
y NO incluye version_hash, fecha ni orden. Duplicados anónimos son filas diferentes.
Un UUID local no se repite entre casos de una misma cabecera. Cabeceras archivadas
y estudiantes distintos conservan seguimientos independientes.

una_cabecera_viva incluye activo y transicion_requerida; una transición bloqueada
no permite crear otra cabecera viva. El índice parcial es inmediato: archivar
anterior antes de insertar sucesora dentro de una transacción futura.

## Cierre de acceso, propietario y transacción

BEGIN/COMMIT engloban creación, índices, cierre y comprobaciones. No IF NOT EXISTS:
una colisión aborta en lugar de adoptar objetos desconocidos. Los bloques DO son
comprobaciones de catálogo, no funciones de negocio ni cambios de rol.

Se exige identidad efectiva current_user=postgres y los esquemas propiedad de
postgres. Se comprueban atributos de los tres roles de 4A. Si la CLI usa otra
identidad efectiva, esta migración fallará antes de crear tablas: revisar mecanismo
de conexión y autorización antes de ejecutarla. No usar SET ROLE, cambiar propietarios
ni ampliar privilegios automáticamente para superar ese fallo. Esa identidad aún
no se ha verificado para esta migración, pues no se consulta el proyecto remoto.

Cada tabla habilita ENABLE/FORCE RLS, sin políticas. REVOKE explícito para PUBLIC,
anon, authenticated, service_role y los tres roles Tinotify. Una comprobación final
rechaza ACL residuales de tabla Y columna no pertenecientes al propietario,
incluidos PUBLIC y grupos. Comprueba además permisos efectivos de clientes/servicios
y acceso heredado o SET al propietario. No modifica defaults ni roles de 4A.
Las columnas text de huellas/referencias ASCII usan COLLATE C para rangos exactos.

Nadie obtiene acceso operativo en 4B.1. No hay aún un usuario autenticado capaz de
leer su propio expediente: las futuras políticas/capacidades de 4B.2 deberán
permitirlo con límites correctos. Las FK previenen asociaciones cruzadas, pero no
autentican a quien elige un estudiante_id. FORCE RLS tampoco limita superusuarios
o roles BYPASSRLS administrativos, ni protege por sí solo TRUNCATE/REFERENCES.
Por eso se revisan privilegios, además de RLS. No usar service_role como acceso
ordinario. No se cambia Exposed schemas ni Automatically expose new tables.

## Matriz de garantías

| Garantía | 4B.1 SQL | Pendiente |
| --- | --- | --- |
| Existencia/pertenencia de estudiante, estado, caso, trabajo y actuación | PK/FK compuestas | Autenticar actor y autorizar ese alcance en 4B.2. |
| Identidad estable única por contrato/alcance | UNIQUE parcial + grupo origen todo NULL/no NULL + FK de alcance | Contrato revisado/habilitado en código y política vigente; el catálogo real sigue vacío. |
| Multiplicidad anónima y UUID global por cabecera | Sin UNIQUE por hash; UNIQUE local_id por cabecera | Aplicar resultado completo del motor, sin emparejamientos SQL nuevos. |
| Una cabecera viva y un job activo por caso | Índices únicos nativos | Bloqueos, renovación, expiración, CAS y fencing vigentes en 4B.2. |
| Versiones de estado admitidas | CHECK schema_version=2/state_revision=2/fingerprint_version=1 | Validación completa, transición explícita y política de confianza vigente. |
| Status/NULL/hash/versión decimal/tamaños individuales | NOT NULL, CHECK, grupos de identidad y límites | Transiciones válidas, codec canónico, orden contiguo, cuotas agregadas y caso incluido coherente. |
| Evento perteneciente al mismo trabajo/registro/caso | FK y UNIQUE trabajo+ordinal | Evento producido realmente por motor, prioridad y generación exacta; no basta formato válido. |
| Importación única por clave de estudiante | UNIQUE y forma del recibo | Vincular instancia/archivo, validar todo, comparar reintentos y resolver COMMIT incierto. |
| Datos y eventos atómicos durante sincronización | PostgreSQL permite transacción | El DDL no ejecuta una sincronización; unidad de trabajo en 4B.2/4B.3. |
| Aislamiento operativo | Acceso cerrado a todas las filas | Políticas por estudiante y conexiones restringidas reales en 4B.2; usuario_id no prueba autorización. |
| Autorización institucional y sesión SIGAC | Ninguna evidencia se crea por DDL | Separadas de Auth; integración real prohibida y atestador pendiente. |

## Compatibilidad estructural con v2.2

Se contrastó _validar_v2/_validar_activo, clave_estable y reconciliar. Cabecera,
records y referencias del motor tienen columnas; solo cambian representación y
contexto relacional, no claves JSON. incluido_en_estado conserva la diferencia
entre caso ausente y caso con records=[]; orden_registro preserva el array. Status
persistido no se sustituye por el estado temporal sin_cambios del resultado.

BYTEA con UTF-8/surrogatepass conserva las cadenas Python admitidas donde TEXT
no basta. La DB no verifica que esos bytes sean canónicos: 4B.3 debe decodificar
estrictamente y pasar el validador existente. No normalizar claves. UUID canónico
y entero decimal se validarán antes de almacenar; no usar float.

Topes: instancia/clave contractual 512 bytes, caso 128 caracteres según lector y
512 bytes en SQL, versión contractual 128 dígitos, archivo 64 MiB máximo. El lector
Python admite algunos valores mayores: se rechazarán íntegros, sin truncar ni
alterar originales, como ya plantea el diseño. Aprobación de SQL no es autorización
para importar archivos ni establecer otra línea base. No se elevan candidatos.

No se prueba todavía una reconstrucción SQL completa: requiere PostgreSQL y el
adaptador posterior. Los tests locales comprueban cobertura de columnas sobre
records producidos por el motor, enumeraciones y rechazo de confianza sintética
por la política real. No hay un segundo serializador de producción en esta entrega.

## Validaciones locales y límites

Ejecutar desde la raíz con el .venv existente: python -m pytest -q. Las validaciones
de esta entrega se ejecutan además con red bloqueada y temporales fuera del repo.
Las pruebas estáticas detectan regresiones de alcance, cierres, índices y contrato;
NO son un parser SQL, ni verifican sintaxis PostgreSQL, planes de índices, permisos,
bloqueos o ejecución de PL/pgSQL. No hay psql, psycopg, pglast ni sqlparse disponibles;
no se instala nada, ni se usa PostgreSQL local/Docker. La CLI no se usa para consultar
ni modificar el proyecto. La validación PostgreSQL real permanece pendiente.

## Pruebas futuras en PostgreSQL remoto, sin ejecutar ahora

Requieren aprobación separada para aplicar la migración y para escribir/limpiar
fixtures en el proyecto de desarrollo. Usar un cliente psql previamente aprobado,
autenticación local segura mediante servicio libpq/archivo protegido, sin URI
autenticada en comandos o chat. No usar db reset, TRUNCATE, DROP o datos reales.
Nunca ejecutar la migración como parte automática de pytest.

El servicio libpq ficticiamente denominado tinotify_pruebas_4b1 debe configurarse
localmente; no se crea aquí. No versionar .pg_service.conf ni .pgpass. Ejemplo futuro:

```powershell
# SOLO tras autorizacion de migracion y pruebas remotas; no ejecutar ahora.
psql -X --dbname="service=tinotify_pruebas_4b1" -f supabase/tests/4b1_integridad.sql
```

El script exige administrador YA autorizado con superusuario/BYPASSRLS para crear
fixtures pese a FORCE RLS, sin alterar permisos o políticas. Si no existe tal
identidad autorizada, detenerse: no conceder BYPASSRLS para que pasen las pruebas.
Las filas tienen UUID sintéticos reservados y auth_subject NULL. Colisión aborta,
sin adoptar datos existentes. Un único BEGIN/ROLLBACK y subtransacciones prueban
33 casos inválidos por SQLSTATE (y nombre exacto en colisiones críticas), casos positivos y cierre de catálogos. En modo psql -X -f, un fallo
con ON_ERROR_STOP cierra la conexión y revierte; en modo interactivo requiere ROLLBACK.
Las verificaciones ACL/catálogos no sustituyen pruebas operativas por usuario,
que requieren funciones/políticas reales de 4B.2.

Para concurrencia (solo con aprobación adicional de escrituras confirmadas):

1. Generar un UUID v4 NUEVO localmente (PowerShell: [guid]::NewGuid()). Pasarlo
   como -v run_id=... a preparar.sql. El INSERT falla ante cualquier colisión;
   nunca reutiliza una fila. Guardar el recibo run_id + fixture_creado_en SOLO
   cuando COMMIT se confirma. Son metadatos del fixture, no credenciales.
2. Pasar ambos valores a A, B y limpiar mediante -v, citando el timestamp completo,
   incluido offset. Los scripts los convierten a UUID/timestamptz, no concatenan
   SQL arbitrario. Si faltan variables o el recibo no coincide, fallan.
3. A/B validan perfil pendiente/auth_subject NULL/creado_en y mantienen FOR KEY
   SHARE hasta terminar. A inserta su cabecera y espera 10 s; iniciar B durante
   esa espera. B exige unique_violation (23505) y CONSTRAINT_NAME exacto
   una_cabecera_viva. FK, timeout, otra unicidad o INSERT inesperado no pasan.
4. En otra sesión autorizada read-only, registrar la espera: consultar
   pg_stat_activity filtrando application_name='tinotify_4b1_b', wait_event_type
   y pg_blocking_pids(pid), sin consultar texto de consultas ajenas. Si no se
   observó bloqueo, no se ha demostrado concurrencia, solo unicidad.
5. Cerrar A/B y ejecutar limpiar con el recibo. Bloquea perfil y cabeceras
   FOR UPDATE NOWAIT ANTES de comprobar y borrar. Rechaza trabajo activo
   (55P03), recibo incorrecto, expedientes/importaciones o cabeceras inesperadas.
   Solo borra la cabecera A derivada del run_id y ese perfil. NO ACTION conserva
   protección adicional. Una interrupción/fallo revierte la limpieza entera.
6. Ensayar de nuevo con OTRO UUID/recibo, -v abortar=1 en A y -v aceptar=1 en B.
   A revierte; B debe aceptar INSERT y revertirlo. B rechaza 23505 en este modo.

Los IDs de cabecera se derivan de a:/b: + run_id para separar PK y época. Son
identificadores exclusivos de fixtures; no representan SIGAC ni anonimización.
No hay UUID fijo compartido ni limpieza por prefijos. El recibo protege frente
a limpieza accidental/reutilización, no frente a un administrador malicioso.

Después de interrupción: cerrar conexiones; si hay recibo y setup confirmado,
reintentar limpieza acotada. Con COMMIT incierto, recibo perdido o discrepancia,
detenerse y revisar solo ese run_id mediante consulta autorizada, sin adoptar
filas por su forma ni borrar automáticamente. Una limpieza ya completada produce
perfil ausente y exige comprobar el resultado, no buscar otro fixture.

Los scripts se deben ejecutar con psql -X -f y ON_ERROR_STOP. En ese modo, un fallo
cierra la conexión y revierte transacciones abiertas. Si se cargan desde una sesión
interactiva, esta puede seguir abierta: hacer ROLLBACK explícito antes de cualquier
reintento. No afirmar rollback automático por ON_ERROR_STOP en toda modalidad.
Setup y limpieza son las únicas transacciones confirmadas del ensayo; sin grants,
cambios de rol ni políticas temporales.

## Auditoría adicional: identidad y dependencias funcionales

Sea N=(estudiante_id,estado_id), E=expediente_id. En cada fila con source_id:

- PK de cabecera: N determina una instancia I. La FK (N,alcance_instancia_utf8)
  obliga alcance_instancia_utf8=I.
- PK de expediente: (N,E) determina una clave C. La FK
  (N,E,alcance_caso_utf8) obliga alcance_caso_utf8=C.
- El CHECK exige todos los campos de origen no NULL: MATCH SIMPLE no puede omitir
  esas FK para una identidad indexada. Anónimos quedan fuera del índice.
- UNIQUE(N,clave_caso_utf8) impide dos E para la misma C dentro de N.

clave_estable devuelve (contrato.clave,contrato.version,contrato.revision,I,C,source).
Dentro de N, igualdad de la clave real implica mismo C, por tanto mismo E, y
misma referencia/source: colisión del índice. Igualdad de todos los campos del
índice implica misma N/E, por tanto mismo I/C y misma clave real. La codificación
reversible y el decimal canónico preservan igualdad en el dominio aceptado.

Por ello añadir alcance_instancia_utf8/alcance_caso_utf8 al índice no distingue
filas que hoy colisionen: son funcionalmente redundantes. NO se eliminan columnas,
FK ni campos del contrato. contrato.revision es revisión del CONTRATO; version_hash
sigue fuera. Se conserva la frontera de estudiantes y épocas: una misma clave del
motor puede existir en otros seguimientos/estados archivados, deliberadamente.

Las pruebas locales llaman clave_estable con contratos sintéticos revisados y
comparan su proyección formal; no simulan la ejecución de un índice. El script SQL
prepara colisión con distinto hash y casos admitidos por diferencias de contrato,
versión/revisión, instancia, expediente y source. Confianza del catálogo vigente
sigue siendo responsabilidad de 4B.2; ninguna fila habilita contratos.

## Auditoría adicional: privilegios

Omisión confirmada: el cierre original solo inspeccionaba relacl. REVOKE de tabla
no elimina una concesión de columna. Ahora inspecciona attacl de columnas vivas,
rechaza cualquier grantee no propietario (incluidos PUBLIC/grupos) y verifica
has_table_privilege/has_any_column_privilege efectivos para los seis roles
operativos. También rechaza USAGE o SET al propietario; no altera membresías.
Incluye MAINTAIN, privilegio de PostgreSQL 17.

Los default privileges de PostgreSQL 17 configuran objetos, no concesiones
predeterminadas por columna. Los permisos por defecto materializados en relacl
quedan cubiertos; los defaults de roles miembros NO se heredan al crear objetos.
La herencia de privilegios efectivos sí se comprueba. No se conceden permisos
ni siquiera para inyectar ACL de prueba: la validación negativa del guard SQL en
un servidor sigue pendiente. No se promete limitar superusuarios/administradores.

## Auditoría adicional: tamaño B-tree

Cálculo conservador, NO medición ni validación ejecutada. Hipótesis: PostgreSQL 17,
MAXALIGN=8 y tipos estándar; sin contar ahorro por compresión/varlena corta.
Para el índice estable (7 atributos, todos no NULL en filas indexadas):

| Componente | Octetos máximos usados en la cota |
| --- | --- |
| Tres UUID | 48 |
| Contrato BYTEA de 512 + cabecera larga | 516 |
| Versión decimal ASCII de 128 + cabecera | 132 |
| Revisión hexadecimal de 64 + cabecera | 68 |
| Source ASCII de 128 + cabecera | 132 |
| Datos totales | 896 |
| Cabecera de índice | 8 |
| Holgura conservadora de alineación | 7 por atributo, 49 |
| MAXALIGN del subtotal 953 | 960 |
| Holgura adicional heap TID | 8 |
| Cota conservadora final | 968 |

Los otros índices del esquema tienen claves menores: la mayor combinación restante
es tres UUID + BYTEA de 512 (564 octetos de datos); las colas usan estados enumerados,
timestamps y UUID. Ningún índice almacena descripciones u otros TEXT ilimitados.
Los 512 son OCTETOS, no caracteres: las pruebas incluyen caso de 128 caracteres
de cuatro bytes, contrato/instancia de 512 bytes y source/versión/revisión al máximo.

BTMaxItemSize en el código PG17 reserva tres entradas por página y espacio TID.
Con páginas de 8192, cabecera/line pointers alineados 40, opaque 16 y TID alineado 8:
MAXALIGN_DOWN((8192-40-16)/3)-8 = 2704. La cota 968 deja margen condicional 1736.
Con páginas de 2048 el límite calculado sería 656: NO existe garantía para todo
build PG17. La versión del motor por sí sola no demuestra seguridad de inserción.

No se han consultado block_size, versión compilada, alineación, metadatos de tipos,
opclasses/collations ni comportamiento de inserción del servidor remoto. No cambiar
límites basándose solo en la estimación. 4b1_btree_limites.sql exige PG17/8192/UTF8,
inserta máximos contra los índices reales, fuerza constraints y revierte; si cambia
ese perfil, aborta para revisión. No instala pageinspect ni altera STORAGE.
pg_column_size de una fila no mide una tupla B-tree y no se usa como tal.
Un fallo real de tamaño (54000), CHECK u otro error es fallo del ensayo, no éxito.
Ejecutar y registrar ese ensayo, y revisar configuración/tipos reales, sigue siendo
obligatorio antes de afirmar validación PostgreSQL.

## Decisiones pendientes antes de ejecutar

- Revisión del SQL completo y de sus límites; autorización remota explícita.
- Verificar identidad efectiva/propiedad y privilegios de ejecución con consultas
  autorizadas. La condición postgres puede bloquear una CLI con identidad temporal.
- Validar gramática/ejecución y FK/NULL/índices en PostgreSQL real; medir límites de
  B-tree según block_size/collation remotos. No hay evidencia de servidor todavía.
- Autorizar herramienta cliente y dataset de pruebas, incluidas filas confirmadas
  para concurrencia. Revisar Exposed schemas y defaults por separado, sin cambiarlos.
- En 4B.2: funciones, política vigente, autorización, RLS por usuario y privilegios
  operativos; en 4B.3: adaptador y reconstrucción/importación integrada.

Referencias: [restricciones](https://www.postgresql.org/docs/17/ddl-constraints.html),
[índices únicos](https://www.postgresql.org/docs/17/indexes-unique.html) y
[límites de RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).

Para esta auditoría: [funciones de privilegios](https://www.postgresql.org/docs/17/functions-info.html),
[defaults y herencia](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html),
[BTMaxItemSize PG17](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/include/access/nbtree.h)
y [comprobación del tamaño B-tree](https://github.com/postgres/postgres/blob/REL_17_STABLE/src/backend/access/nbtree/nbtutils.c).
