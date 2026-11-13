# Etapa 4B: revisión de integridad y plan de implementación

Propuesta revisada el 12 de noviembre de 2026. **No es una migración ni autoriza
SQL remoto.** El cierre 4A en `825f8d7` permanece intacto. Proyecto remoto solo de
desarrollo ficticio. No se modifica backend, motor, parser ni Data API.

## Actualización de estado — 13 de noviembre de 2026

Esta sección registra avances posteriores a la propuesta del 12 de noviembre
de 2026. Las afirmaciones históricas del documento deben interpretarse
según su fecha original y no como el estado actual de implementación.

### 4B.1 — Validación técnica aislada

- Existe una migración SQL local del núcleo de reconciliación.
- La migración corregida se ejecutó satisfactoriamente en PostgreSQL 17.11,
  dentro de un contenedor Docker aislado, sin red ni montajes.
- Se verificaron restricciones, claves foráneas, RLS ENABLE/FORCE,
  ausencia de políticas y ausencia de privilegios operativos inesperados.
- Se ejecutaron pruebas SQL de integridad y límites de índices B-tree.
- Se validó el índice único parcial de cabeceras vivas con dos conexiones:
  cuando A confirma, B encuentra el conflicto de unicidad; cuando A
  revierte, B puede insertar después de esperar el bloqueo.
- Se comprobó la limpieza de los dos fixtures de concurrencia identificados
  por sus UUID: cero estudiantes, cabeceras y sesiones A/B residuales.
- La suite de pruebas backend registró 281 pruebas aprobadas.

### Alcance y limitaciones

- La validación descrita corresponde a una base PostgreSQL restaurada
  en Docker aislado; no equivale a una validación remota.
- No se ha aplicado la migración 4B.1 a producción.
- No se han implementado ni validado integralmente 4B.2 y 4B.3.
- La aprobación del despliegue, la revisión de entrega y las pruebas
  adicionales que correspondan siguen pendientes.
- La validación técnica no sustituye la autorización para realizar
  escrituras o despliegues remotos.

---

## 1. Evidencia y problemas confirmados

Se contrastaron las diez tablas del borrador con el código real:
`persistence/monitor.py` (`_validar_v2`, `_validar_activo`, transición y lectura),
`services/reconciliacion.py`, `domain/identificadores.py`,
`domain/actuaciones.py` y pruebas de estado, reconciliación y confianza.

El motor asigna UUID locales incluso a duplicados y resultados ambiguos. Eso
no demuestra identidad física ni correspondencia inequívoca por fila HTML.
Ordena entradas por identidad/huella, no por posición original; devuelve records
ordenado por UUID y conserva ausentes. Una consulta repetida puede devolver
sin_cambios sin reemplazar el status persistido anterior. El catálogo de contratos
de producción está vacío; datos almacenados no pueden habilitarlo.

| Problema confirmado del borrador | Corrección |
| --- | --- |
| Observaciones exigía local_id/revision por entrada, sin que el motor preserve esa correlación. No todo resultado ambiguo carece de UUID. | Posponer entradas crudas; vínculo nullable si se incorporan. |
| actuaciones_origen era un índice no único. | UNIQUE por contrato y alcance, sin huella de contenido. |
| Índice de búsqueda md5 no impedía dos cabeceras vivas. | UNIQUE parcial sobre instancia exacta. |
| Ciclo actuaciones/versiones necesitaba FK diferibles para un estado que solo conserva huella actual. | Huella actual en actuaciones; historia pospuesta. El ciclo no demuestra corrupción por sí solo. |
| Permisos manuales por expediente introducían un aprobador sin justificación institucional. | Separar aprobación de integración de comprobación de acceso efectivo SIGAC. |
| No había cuotas numéricas ni límites compatibles con índices. | Rechazo íntegro y explícito fuera de límites; nunca truncar. |
| SECURITY DEFINER no cerraba propietario, contexto, GRANT/REVOKE y pruebas. | Contrato de funciones y RLS específico en 4B.2. |
| CHECK de forma no garantizaba política vigente, orden contiguo o reserva válida. | Separar invariantes SQL de funciones/adaptador. |

Carreras, fugas RLS, deadlocks y fallos transaccionales son riesgos por probar,
no incidentes observados: 4B todavía no existe en PostgreSQL. Este DDL tampoco
ha sido ejecutado ni validado por un servidor PostgreSQL.

## 2. Auditoría de las diez tablas y núcleo reducido

| Tabla original | Decisión y representación autoritativa |
| --- | --- |
| estudiantes | Conservar: identidad interna y vínculo Auth, sin nombres/emails institucionales. |
| estados_reconciliacion | Conservar: cabecera v2.2, instancia y época; una cabecera viva. |
| expedientes | Conservar: clave exacta, inclusión en cases, generación y fencing por estudiante. |
| actuaciones | Conservar: UUID local, orden, status persistido, huella actual y referencia contractual. |
| versiones_actuacion | Posponer: JSON v2.2 no contiene historia de versiones ni contenido. |
| observaciones | Posponer: no es necesaria para reconstruir v2.2; vínculo opcional si se añade. |
| permisos_caso | Sustituir por app_private.accesos_sigac: caché de comprobación efectiva, no concesión manual. |
| sincronizaciones | Conservar: reserva, épocas, fencing, idempotencia y resultado. |
| eventos | Conservar: sucesos del motor/prioridad, sin contenido jurídico. |
| importaciones | Conservar: recibo de importación, sin JSON mutable paralelo. |

Se proponen **ocho tablas iniciales**. PostgreSQL será la única autoridad tras el
corte explícito; JSON solo importación/exportación, nunca segundo escritor. Un
UUID local es seguimiento, no identidad institucional. No inventar fechas, anexos,
descripciones o versiones históricas ausentes del estado importado.

### Codificación reversible y compatibilidad delimitada

El lector acepta algunas cadenas Python incompatibles con TEXT/JSONB de PostgreSQL,
como NUL o sustitutos Unicode aislados en ciertas claves. Se propone BYTEA:

```python
# Especificación, no implementación del adaptador.
B = lambda texto: texto.encode("utf-8", errors="surrogatepass")
T = lambda dato: bytes(dato).decode("utf-8", errors="surrogatepass")
```

Aplicar a instancia, caso, clave de contrato y alcances. Exigir T(B(s)) == s,
codec canónico y validador existente; nunca errors=replace, normalizar o recortar
identidades. Codificación no cifra ni anonimiza. UUID se reconstruye con str(uuid),
versión contractual con decimal canónico de entero positivo, sin float.

Topes indexados propuestos: instancia/clave contractual 512 bytes, caso 128
caracteres Python y 512 bytes, versión contractual 128 dígitos. Son restricciones
NUEVAS del almacenamiento: no prometer compatibilidad ilimitada con cualquier
objeto aceptado por Python. Fuera de cuota se rechaza el archivo completo, sin
modificarlo ni establecer línea base. Ampliar máximos indexados exige revisar DDL.

## 3. DDL propuesto: ocho tablas cerradas

Objetivo PostgreSQL 17, versión remota pendiente de comprobación autorizada.
UUID desde el adaptador, sin extensiones. Tablas del administrador de migración,
nunca del servicio; NO ACTION salvo desvinculación Auth. Sin ciclos de FK.

```sql
-- DISEÑO: no copiar a migrations ni ejecutar todavía.
BEGIN;
CREATE TABLE app.estudiantes (
    id uuid PRIMARY KEY,
    auth_subject uuid UNIQUE REFERENCES auth.users(id) ON DELETE SET NULL,
    estado text NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente','activo','suspendido','borrado_solicitado')),
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE app.estados_reconciliacion (
    estudiante_id uuid NOT NULL REFERENCES app.estudiantes(id),
    id uuid NOT NULL,
    instancia_utf8 bytea NOT NULL CHECK (octet_length(instancia_utf8) BETWEEN 1 AND 512),
    epoca bigint NOT NULL CHECK (epoca > 0),
    situacion text NOT NULL CHECK (situacion IN ('activo','transicion_requerida','archivado')),
    schema_version smallint NOT NULL CHECK (schema_version = 2),
    state_revision smallint NOT NULL CHECK (state_revision = 2),
    fingerprint_version smallint NOT NULL CHECK (fingerprint_version = 1),
    trust_policy text NOT NULL CHECK (trust_policy ~ '^[0-9a-f]{64}$'),
    migrated_from_v1 boolean NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (estudiante_id,id),
    UNIQUE (estudiante_id,instancia_utf8,epoca),
    UNIQUE (estudiante_id,id,instancia_utf8)
);
CREATE UNIQUE INDEX una_cabecera_viva ON app.estados_reconciliacion
    (estudiante_id,instancia_utf8)
    WHERE situacion IN ('activo','transicion_requerida');
CREATE TABLE app.expedientes (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    id uuid NOT NULL,
    clave_caso_utf8 bytea NOT NULL CHECK (octet_length(clave_caso_utf8) BETWEEN 1 AND 512),
    incluido_en_estado boolean NOT NULL DEFAULT false,
    generacion bigint NOT NULL DEFAULT 0 CHECK (generacion >= 0),
    fencing bigint NOT NULL DEFAULT 0 CHECK (fencing >= 0),
    PRIMARY KEY (estudiante_id,estado_id,id),
    FOREIGN KEY (estudiante_id,estado_id)
        REFERENCES app.estados_reconciliacion(estudiante_id,id),
    UNIQUE (estudiante_id,estado_id,clave_caso_utf8),
    UNIQUE (estudiante_id,estado_id,id,clave_caso_utf8)
);
CREATE TABLE app.actuaciones (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    local_id uuid NOT NULL,
    orden_registro bigint NOT NULL CHECK (orden_registro >= 0),
    version_hash text NOT NULL CHECK (version_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN (
        'linea_base','sin_cambios','primera_observacion','modificada','ambigua')),
    source_id text COLLATE "C",
    contrato_clave_utf8 bytea,
    contrato_version_decimal text COLLATE "C",
    contrato_revision text,
    alcance_instancia_utf8 bytea,
    alcance_caso_utf8 bytea,
    PRIMARY KEY (estudiante_id,estado_id,expediente_id,local_id),
    UNIQUE (estudiante_id,estado_id,local_id),
    UNIQUE (estudiante_id,estado_id,expediente_id,orden_registro)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (estudiante_id,estado_id,expediente_id)
        REFERENCES app.expedientes(estudiante_id,estado_id,id),
    FOREIGN KEY (estudiante_id,estado_id,alcance_instancia_utf8)
        REFERENCES app.estados_reconciliacion(estudiante_id,id,instancia_utf8),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id,alcance_caso_utf8)
        REFERENCES app.expedientes(estudiante_id,estado_id,id,clave_caso_utf8),
    CHECK (
        (source_id IS NULL AND contrato_clave_utf8 IS NULL
         AND contrato_version_decimal IS NULL AND contrato_revision IS NULL
         AND alcance_instancia_utf8 IS NULL AND alcance_caso_utf8 IS NULL)
        OR
        (source_id IS NOT NULL AND contrato_clave_utf8 IS NOT NULL
         AND contrato_version_decimal IS NOT NULL AND contrato_revision IS NOT NULL
         AND alcance_instancia_utf8 IS NOT NULL AND alcance_caso_utf8 IS NOT NULL)
    ),
    CHECK (source_id IS NOT NULL OR status <> 'modificada'),
    CHECK (source_id IS NULL OR source_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'),
    CHECK (contrato_clave_utf8 IS NULL OR octet_length(contrato_clave_utf8) BETWEEN 1 AND 512),
    CHECK (contrato_version_decimal IS NULL OR
        (contrato_version_decimal ~ '^[1-9][0-9]*$' AND length(contrato_version_decimal) <= 128)),
    CHECK (contrato_revision IS NULL OR contrato_revision ~ '^[0-9a-f]{64}$')
);
CREATE UNIQUE INDEX una_identidad_estable_por_alcance ON app.actuaciones
    (estudiante_id,estado_id,expediente_id,contrato_clave_utf8,
     contrato_version_decimal,contrato_revision,source_id)
    WHERE source_id IS NOT NULL;
CREATE INDEX actuaciones_huella ON app.actuaciones
    (estudiante_id,estado_id,expediente_id,version_hash);
CREATE TABLE app_private.accesos_sigac (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    estado text NOT NULL DEFAULT 'no_verificado'
        CHECK (estado IN ('no_verificado','verificado','denegado','caducado')),
    fuente text NOT NULL DEFAULT 'ninguna' CHECK (fuente IN ('ninguna','simulador','sigac')),
    session_binding_id uuid,
    session_epoch bigint NOT NULL DEFAULT 0 CHECK (session_epoch >= 0),
    access_epoch bigint NOT NULL DEFAULT 0 CHECK (access_epoch >= 0),
    comprobado_en timestamptz,
    valido_hasta timestamptz,
    comprobante_ref uuid,
    PRIMARY KEY (estudiante_id,estado_id,expediente_id),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id)
        REFERENCES app.expedientes(estudiante_id,estado_id,id),
    CHECK (valido_hasta IS NULL OR
        (comprobado_en IS NOT NULL AND valido_hasta > comprobado_en)),
    CHECK (estado <> 'verificado' OR
        (fuente IN ('simulador','sigac') AND session_binding_id IS NOT NULL
         AND session_epoch > 0 AND access_epoch > 0 AND comprobante_ref IS NOT NULL
         AND comprobado_en IS NOT NULL AND valido_hasta IS NOT NULL))
);
CREATE INDEX accesos_caducidad ON app_private.accesos_sigac (estado,valido_hasta);
CREATE TABLE app_private.sincronizaciones (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    id uuid NOT NULL,
    idempotency_key uuid NOT NULL,
    modo text NOT NULL DEFAULT 'sintetico' CHECK (modo IN ('sintetico','institucional')),
    estado text NOT NULL CHECK (estado IN (
        'reservada','ejecutando','confirmada','fallida','cancelada','expirada')),
    generacion_base bigint NOT NULL CHECK (generacion_base >= 0),
    generacion_confirmada bigint,
    access_epoch bigint NOT NULL CHECK (access_epoch >= 0),
    session_epoch bigint NOT NULL CHECK (session_epoch >= 0),
    fencing bigint NOT NULL CHECK (fencing > 0),
    worker_id uuid,
    lease_token uuid,
    lease_hasta timestamptz,
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    terminado_en timestamptz,
    PRIMARY KEY (estudiante_id,estado_id,expediente_id,id),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id)
        REFERENCES app.expedientes(estudiante_id,estado_id,id),
    UNIQUE (estudiante_id,estado_id,expediente_id,idempotency_key),
    UNIQUE (estudiante_id,estado_id,expediente_id,fencing),
    CHECK (estado NOT IN ('reservada','ejecutando') OR
        (worker_id IS NOT NULL AND lease_token IS NOT NULL AND lease_hasta IS NOT NULL)),
    CHECK ((estado = 'confirmada' AND generacion_confirmada IS NOT NULL)
        OR (estado <> 'confirmada' AND generacion_confirmada IS NULL)),
    CHECK (generacion_confirmada IS NULL OR generacion_confirmada >= generacion_base),
    CHECK ((estado IN ('reservada','ejecutando') AND terminado_en IS NULL)
        OR (estado IN ('confirmada','fallida','cancelada','expirada') AND terminado_en IS NOT NULL))
);
CREATE UNIQUE INDEX una_sincronizacion_activa ON app_private.sincronizaciones
    (estudiante_id,estado_id,expediente_id) WHERE estado IN ('reservada','ejecutando');
CREATE INDEX sincronizaciones_cola ON app_private.sincronizaciones (estado,lease_hasta,creado_en);
CREATE TABLE app.eventos (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    id uuid NOT NULL,
    sincronizacion_id uuid NOT NULL,
    ordinal bigint NOT NULL CHECK (ordinal >= 0),
    local_id uuid NOT NULL,
    generacion_resultado bigint NOT NULL CHECK (generacion_resultado >= 0),
    tipo text NOT NULL CHECK (tipo IN (
        'primera_observacion','modificacion_confirmada','cambio_ambiguo')),
    prioridad text NOT NULL CHECK (prioridad IN ('alta','normal')),
    disposicion text NOT NULL DEFAULT 'pendiente'
        CHECK (disposicion IN ('pendiente','procesado','descartado_por_politica')),
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (estudiante_id,id),
    UNIQUE (estudiante_id,estado_id,expediente_id,sincronizacion_id,ordinal),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id,sincronizacion_id)
        REFERENCES app_private.sincronizaciones(estudiante_id,estado_id,expediente_id,id),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id,local_id)
        REFERENCES app.actuaciones(estudiante_id,estado_id,expediente_id,local_id)
);
CREATE INDEX eventos_actuacion ON app.eventos (estudiante_id,estado_id,expediente_id,local_id);
CREATE INDEX eventos_pendientes ON app.eventos (prioridad,creado_en) WHERE disposicion = 'pendiente';
CREATE TABLE app_private.importaciones (
    estudiante_id uuid NOT NULL REFERENCES app.estudiantes(id),
    id uuid NOT NULL,
    idempotency_key uuid NOT NULL,
    estado_id uuid,
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_bytes bigint NOT NULL CHECK (source_bytes BETWEEN 0 AND 67108864),
    estado text NOT NULL CHECK (estado IN ('reservada','confirmada','rechazada')),
    casos bigint CHECK (casos >= 0),
    registros bigint CHECK (registros >= 0),
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (estudiante_id,id),
    UNIQUE (estudiante_id,idempotency_key),
    FOREIGN KEY (estudiante_id,estado_id)
        REFERENCES app.estados_reconciliacion(estudiante_id,id),
    CHECK ((estado = 'confirmada' AND estado_id IS NOT NULL AND casos IS NOT NULL AND registros IS NOT NULL)
        OR (estado <> 'confirmada' AND estado_id IS NULL))
);
CREATE INDEX importaciones_estado ON app_private.importaciones (estudiante_id,estado_id);
CREATE INDEX importaciones_digest ON app_private.importaciones (estudiante_id,source_sha256);
-- Cierre inicial: sin permisos operativos y sin alterar 4A.
DO $cierre$
DECLARE t record;
BEGIN
    FOR t IN SELECT * FROM (VALUES
        ('app','estudiantes'),('app','estados_reconciliacion'),
        ('app','expedientes'),('app','actuaciones'),('app','eventos'),
        ('app_private','accesos_sigac'),('app_private','sincronizaciones'),
        ('app_private','importaciones')
    ) AS objetivos(esquema,tabla)
    LOOP
        EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',t.esquema,t.tabla);
        EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',t.esquema,t.tabla);
        EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC, anon, authenticated, service_role, tinotify_api, tinotify_sync, tinotify_notifications',t.esquema,t.tabla);
    END LOOP;
END;
$cierre$;
COMMIT;
```

La FK Auth no crea cuentas. Desvincular Auth deniega acceso, pero no sustituye
revocación/purga coordinada. Un expediente no incluido no se exporta como vacío.
Cada cabecera archivada conserva UUID originales para su reconstrucción.

## 4. Pruebas de integridad y reparto de garantías

Clave estable real: `(contrato.clave, contrato.version, contrato.revision,
instancia, caso, source_id)`. contrato.revision es revisión del CONTRATO, no de
contenido. Las FK fijan instancia/caso al alcance; UNIQUE cubre los demás campos
sin version_hash, fecha o posición. El CHECK exige todo NULL o todo no NULL;
los anónimos quedan fuera del índice y conservan multiplicidad.

- Misma identidad estable y huellas A/B en dos filas: UNIQUE 23505, también en
  concurrencia. Edición es UPDATE del mismo UUID. Otro contrato es otro namespace.
- Dos UUID anónimos con la misma huella: permitido, sin deduplicar.
- Diferentes estudiantes/cabeceras archivadas: seguimientos separados. Dentro
  de cada cabecera, local_id no se repite ni entre casos, igual que en JSON.
- Dos cabeceras vivas por estudiante/instancia: UNIQUE nativo, no SELECT previo.
  Una transición bloqueada ocupa ese lugar. Archivar antes de insertar sucesora
  en la misma transacción; el índice parcial no es diferible. Sin digest sustituto.
- Sin ciclo actuaciones/versiones. Solo el orden tiene UNIQUE diferible para
  reordenación temporal; COMMIT rechaza repetidos, la función comprueba contigüidad.
- MATCH SIMPLE omite FK opcional cuando hay NULL; CHECK impide grupos de identidad
  parciales. Todas las FK de seguimiento contienen estudiante/cabecera/caso.

| Garantía SQL declarativa | Garantía de funciones/adaptador |
| --- | --- |
| PK/FK, pertenencia, unicidad estable, cabecera viva y reserva activa. | Actor autenticado, acceso vigente, contexto confiable. |
| Tipos, grupos NULL, estados y huellas de forma válida. | Codec exacto, claves permitidas y validador v2.2 completo. |
| Alcance coincidente y UUID no repetidos por estado. | Confianza vigente y canonicalización UUID al importar. |
| Ordinales no negativos/no repetidos; evento vinculado a trabajo/registro. | Orden contiguo, eventos reales del motor y generación exacta. |
| Forma de estados terminales. | Expiración efectiva, fencing, sesión, CAS y reglas de transición. |
| Atomicidad PostgreSQL. | Uso correcto de transacción, cuotas totales y conservación de ausentes. |

La base no demuestra ejecución correcta de Python. No se implementa un segundo
reconciliador SQL para simular esa garantía. Datos persistidos no habilitan contratos.

## 5. Observaciones y versiones: alternativas pospuestas

Una observación cruda no necesita identidad demostrada. Si se añade posteriormente:

```sql
-- Alternativa futura, NO incluida en las ocho tablas del núcleo.
CREATE TABLE app.observaciones (
    estudiante_id uuid NOT NULL,
    estado_id uuid NOT NULL,
    expediente_id uuid NOT NULL,
    sincronizacion_id uuid NOT NULL,
    ordinal_entrada bigint NOT NULL CHECK (ordinal_entrada >= 0),
    observed_hash text CHECK (observed_hash ~ '^[0-9a-f]{64}$'),
    vinculo text NOT NULL CHECK (vinculo IN ('sin_vinculo','referencia_de_seguimiento')),
    motivo text NOT NULL CHECK (motivo IN (
        'sin_procesar','entrada_rechazada','sin_correspondencia_inequivoca','salida_motor_correlacionada')),
    local_id uuid,
    PRIMARY KEY (estudiante_id,estado_id,expediente_id,sincronizacion_id,ordinal_entrada),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id,sincronizacion_id)
        REFERENCES app_private.sincronizaciones(estudiante_id,estado_id,expediente_id,id),
    FOREIGN KEY (estudiante_id,estado_id,expediente_id,local_id)
        REFERENCES app.actuaciones(estudiante_id,estado_id,expediente_id,local_id),
    CHECK ((vinculo = 'sin_vinculo' AND local_id IS NULL AND motivo <> 'salida_motor_correlacionada')
        OR (vinculo = 'referencia_de_seguimiento' AND local_id IS NOT NULL AND motivo = 'salida_motor_correlacionada'))
);
```

Duplicados/ambiguas pueden quedar sin vínculo aunque el motor produzca UUID;
no alinear listas por posición ni inventar identidades para cumplir FK. Una entrada
rechazada puede no tener huella. Una referencia correlacionada es seguimiento,
no prueba de identidad física. Si se añade historia de versiones será append-only,
FK hacia actuación sin FK de vuelta ni autoridad actual duplicada. A→B→A admite
repetición de huella; importar v2.2 no inventa revisiones antiguas. Posponer ambas
tablas no pierde información que v2.2 realmente contiene.

## 6. Correspondencia completa JSON v2.2 → SQL → JSON

| JSON | Columna/reconstrucción |
| --- | --- |
| schema_version | cabecera.schema_version = 2 |
| state_revision | cabecera.state_revision = 2 |
| fingerprint_version | cabecera.fingerprint_version = 1 |
| trust_policy | cabecera.trust_policy, sin recalcular para elevar confianza |
| migrated_from_v1 | cabecera.migrated_from_v1 |
| cases = {} | Cabecera sin casos incluidos |
| cases[clave] | T(expedientes.clave_caso_utf8), solo incluido_en_estado=true |
| cases[clave].records = [] | Expediente incluido sin actuaciones |
| records[i] | Actuaciones ORDER BY orden_registro; importar conserva orden original |
| local_id | str(actuaciones.local_id) |
| source_id | actuaciones.source_id, incluido NULL |
| contract_ref | NULL o clave=T(contrato_clave_utf8), version=int(decimal), revision=contrato_revision |
| origin_scope | NULL o instancia=T(alcance_instancia_utf8), caso=T(alcance_caso_utf8) |
| version_hash | actuaciones.version_hash |
| status | actuaciones.status persistido, no estado temporal del resultado |

Instancia de seguimiento es contexto externo, no nueva clave JSON; se proporciona
al importar y debe coincidir con política/alcances. Exportar en snapshot REPEATABLE
READ, sin mezclar generaciones. Orden de arrays exacto, orden de claves de objetos
no semántico. Validar reconstrucción con lector existente. Se conserva objeto
aceptado dentro de cuotas, no espacios/escapes originales; el archivo original
se conserva separado. None (caso ausente) y records=[] tienen distinta semántica.

No activar política incompatible, contrato ausente/deshabilitado o alcance distinto.
Rechazar antes de escribir o archivar mediante transición aprobada; nunca corregir
trust_policy para hacerlo pasar ni emitir históricos. v1/v2.1 requieren transición
explícita conservando original. Una nueva base puede omitir novedades, con aviso
y aceptación. El formato de migración SQL no cambia state_revision del motor.

## 7. Identidad, acceso SIGAC e integración institucional

Tres planos separados:

1. Supabase Auth autentica. FastAPI valida firma, algoritmo permitido, issuer,
   audience, vigencia y sujeto; resuelve perfil activo. Metadata/email editable o
   estudiante_id recibido no autoriza expedientes.
2. Acceso efectivo SIGAC: sesión propia e independiente y permisos actuales del
   origen. No cuenta compartida privilegiada. La futura integración comprueba
   caso con la sesión; un token Auth no concede ese acceso.
3. Autorización institucional de integración: institución/responsables competentes
   aprueban mecanismo y tratamiento de datos. Ni una fila SQL ni login exitoso lo
   sustituyen. Falta acordar ese marco antes de integración real.

No hay justificación para un aprobador humano Tinotify por expediente: se elimina.
SIGAC decide acceso efectivo; institución aprueba integración/reglas adicionales,
no un administrador que se autoconcede casos. Nuevas reglas requieren revisión.

accesos_sigac es caché temporal, no prueba autosuficiente. Comprobar estado,
expiración, binding, session_epoch y access_epoch. API/cliente/sync no pueden
escribir evidencia. Solo futuro atestador revisado podrá comprobar acceso real;
renovar exige nueva comprobación. Denegación, logout o cambio de sesión invalidan
épocas/reservas, y una caché nunca permite ignorar una denegación del origen.

**Toda integración real permanece deshabilitada durante 4B.** Solo simulador
aprobado para comprobantes ficticios, jamás válidos para modo institucional. El
atestador real y gestión de secretos/sesiones están pospuestos. No guardar cookies,
contraseñas o tokens aquí. session_binding_id es referencia opaca, no sesión útil.

Backend usa SQL restringido, contexto local por transacción establecido por servidor
tras validar JWT. Un GUC no prueba JWT. No confiar GUC/rol/tenant/caso enviados por
móvil; limpiar contexto al devolver conexión al pool. No service_role ordinario
ni credenciales SQL/privilegiadas en app. RLS limita errores del backend, no backend
o credenciales SQL comprometidos capaces de suplantar el contexto que administran.

## 8. Funciones, propietarios y RLS de 4B.2

4B.1: RLS ENABLE/FORCE sin políticas ni GRANT de negocio. 4B.2 requiere cuerpos,
firmas y pruebas completos; un helper abstracto no es garantía implementada.

Propietarios internos propuestos (no creados aquí), NOLOGIN/NOBYPASSRLS y sin
administración ni propiedad de tablas:

- tinotify_guard_reader: SELECT de columnas mínimas de perfil/cabecera/acceso/job.
- tinotify_state_writer: DML finito de seguimiento/jobs/eventos/importaciones;
  sin DML Auth/perfiles/comprobantes. No puede autoatestarse acceso SIGAC.

Sin membresías de esos propietarios a servicios. Conexiones LOGIN futuras distintas,
provisionadas por operador autorizado con pertenencia solo a su rol operativo 4A,
sin privilegios administrativos ni propiedad. No postgres ni cambios de rol para
eludir errores. Verificar privilegios efectivos/heredados antes de habilitación.

| Familia de función | Propietario | EXECUTE y condición |
| --- | --- | --- |
| Resolver perfil/lectura propia | guard_reader | API y helpers writer concretos: sujeto confiable, perfil y acceso. |
| Validar reserva | guard_reader | Solo helpers writer necesarios: tenant/caso/sesión/lease/fencing/tiempo. |
| Reservar/renovar trabajo sintético | state_writer | tinotify_sync: contexto, bloqueos, épocas; sin acceso institucional en 4B. |
| Leer estado reservado/confirmar | state_writer | tinotify_sync: CAS/lease/política y persistencia atómica. |
| Importar estado | state_writer | Capacidad separada de operador; no sync ordinario. |
| Solicitar cierre propio | state_writer | tinotify_api: invalida su seguimiento, sin conceder permisos/purgar ajenos. |

Cada SECURITY DEFINER: propietario explícito anterior, SET search_path = pg_catalog,
pg_temp, objetos app/app_private calificados, sin SQL dinámico de cliente, SET ROLE
ni DDL. REVOKE EXECUTE de PUBLIC/roles no destinatarios por FIRMA EXACTA en la misma
transacción; GRANT EXECUTE solo firmas necesarias y USAGE mínimo de esquema. No
funciones expuestas en Data API. Propietario sujeto a RLS, sin BYPASSRLS ni propiedad
de tablas. Comprobar session_user/capacidad real del servicio en mutaciones, no un
GUC que afirme ser sync. Importaciones no entran por firma de confirmación ordinaria.

Políticas del guard_reader evalúan directamente tenant/contexto/columnas; no llamar
helper que vuelve a consultar la misma tabla generando recursión. Writer necesita
rutas separadas de provisión/reserva y confirmación: reserva inicial no puede exigir
una reserva existente. Validación sintética acotada, no excepción global/política ALL.

| Tabla | Política mínima prevista |
| --- | --- |
| estudiantes | API/reader resuelven perfil propio; writer no modifica perfiles. |
| estados_reconciliacion | Cabecera propia; crear/transicionar por función, no cambiar política arbitrariamente. |
| expedientes | Caso propio con acceso vigente; reserva/confirmación por función. |
| actuaciones | Lectura de caso autorizado; writer INSERT/UPDATE con lease; sin DELETE por ausencia. |
| accesos_sigac | Reader consulta caso propio; API/sync sin DML, fixtures solo operador. |
| sincronizaciones | Reader valida job concreto; writer reserva/renueva/finaliza con fencing. |
| eventos | Lectura propia cuando proceda; writer inserta resultado, sin contenido jurídico. |
| importaciones | Operador identificado y acotado a estudiante/instancia; sin API/sync general. |

```sql
-- Forma de política 4B.2, NO conjunto completo ni autorización de ejecución.
CREATE POLICY actuaciones_insert_reserva ON app.actuaciones
FOR INSERT TO tinotify_state_writer
WITH CHECK (app_private.reserva_vigente(estudiante_id,estado_id,expediente_id));
CREATE POLICY actuaciones_update_reserva ON app.actuaciones
FOR UPDATE TO tinotify_state_writer
USING (app_private.reserva_vigente(estudiante_id,estado_id,expediente_id))
WITH CHECK (app_private.reserva_vigente(estudiante_id,estado_id,expediente_id));
```

También hacen falta lectura/SELECT y rutas específicas antes de UPDATE. No otorgar
DML directo a sync por estos ejemplos. notifications no recibe permisos nuevos;
push/cola de entregas pospuestos. anon/authenticated/service_role/PUBLIC sin acceso
a estas tablas. FORCE RLS no limita superusuarios/BYPASSRLS de administración.

## 9. Concurrencia, fencing e idempotencia

Escrituras READ COMMITTED con locks; exportaciones REPEATABLE READ de solo lectura.
Orden: cabecera → expediente → acceso → job. No transacción durante futuros HTTP/
parseo. SKIP LOCKED solo para repartir trabajos, nunca omitir filas del historial.

1. Reservar: validar actor/caso/modo, bloquear cabecera y expediente; consultar
   idempotencia antes de nueva reserva. Expirar job vencido, incrementar fencing,
   guardar generación base/épocas/worker/token impredecible/lease. Índice parcial
   impide dos jobs activos. No contadores reiniciables en la misma época.
2. Preparar observaciones sintéticas fuera de transacción. Parcial no elimina
   ausentes; fallo de parseo no se convierte en historial vacío válido.
3. Confirmar: locks en orden, comprobar tiempo después de esperar, perfil/acceso,
   binding/épocas, cabecera activa, política, token, fencing y generación base.
   Revocación usa los mismos locks/épocas. Lease antiguo nunca recupera permiso.
4. Reconstruir y validar estado bloqueado, ejecutar motor puro actual dentro de
   transacción corta. Rutina de confirmación revalida contexto/CAS y aplica todo
   el resultado, ausentes y orden incluidos. Caso no incluido se pasa como None.
5. Guardar registros, eventos, generación siguiente y recibo en una transacción.
   Verificar número exacto de generación; rechazar desbordamiento, no wraparound.
6. Repetir job confirmado devuelve recibo mínimo job/generación/estado, sin volver
   a ejecutar motor ni eventos. Nuevo job con mismo historial tampoco genera avisos.

Evento único por job+ordinal, no por local_id+hash: A→B→A admite dos modificaciones
confirmadas con contrato estable. Sin identidad, puede ser ambiguo. Ausencia no
borra. No prometer exactamente una entrega push. Notificaciones futuras genéricas
con prioridad del motor; sin responsable/caso/descripción/anexo en el mensaje.

## 10. Cuotas, retención e importación

Valores propuestos, pendientes de aprobación y carga. Reducibles por configuración;
topes indexados requieren DDL para ampliar. Nunca cortar listas ni importar partes.

| Recurso | Predeterminado | Tope inicial |
| --- | --- | --- |
| Archivo | 16 MiB | 64 MiB |
| Casos por cabecera/importación | 250 | 1.000 |
| Registros por caso/lote | 20.000 | 100.000, sujeto al total |
| Registros por archivo | 100.000 | 250.000 y tope de bytes |
| Instancia/clave contractual | 512 bytes | 512 bytes cada una |
| Versión contractual | 128 dígitos | 128 dígitos |
| Caso/source_id | Contrato actual 128 caracteres | Más topes binarios/sintaxis |
| Confirmación | Objetivo 5 s | statement_timeout 15 s, lock_timeout 3 s propuestos |

Prevalidar bytes/cantidades, rechazar entero sin modificar original ni emitir
históricos. Un estado existente mayor a una cuota reducida bloquea nuevas escrituras,
no se purga y conserva exportación. Totales en funciones/adaptador, no CHECK entre
filas. No cambiar validador del motor para ocultar límites del almacenamiento.

Conservar registros mientras época activa: purgar ausentes rompe multiplicidad/
reapariciones. Cierre/reset explícito. Revocación deniega inmediatamente e invalida
jobs; purga propuesta hasta 30 días, sujeta a reglas institucionales. Eventos
procesados: propuesta 30 días, pendientes sin purga automática. Recibos mínimos de
idempotencia durante toda la época; limpiar worker/token terminales sin borrar
recibos/fencing. Backups requieren política propia, sin prometer borrado instantáneo.

Importación: operador vincula estudiante/instancia (JSON no prueba propietario),
respaldo externo protegido, lectura estricta sin claves duplicadas, validador v2.2+
confianza+cuotas y transacción única. Mismo idempotency_key con otro digest/tamaño/
propietario/instancia falla. Digest es integridad, no anonimización ni clave global.
Sin eventos históricos. Fallo/caída: rollback y original intacto. COMMIT incierto:
consultar recibo antes de repetir. Corte explícito, nunca dos motores/escritores.

Posponer entradas crudas, versiones históricas, comprobantes históricos, gestión
real de sesiones y entrega push. No almacenar HTML, documentos, cookies o contenido
jurídico en este núcleo. Retención de datos reales requiere revisión institucional.

### Automatically expose new tables

Se observó activado en 4A; no se modifica. app/app_private estaban desmarcados en
Exposed schemas. La opción afecta concesiones futuras Data API, no equivale a exponer
cualquier esquema. Proponer desactivación con aprobación separada; no revoca
privilegios existentes ni EXECUTE público de funciones. Mantener cierre explícito
y revisar catálogos/Dashboard tras fases. No modificar 4A ni exponer esquemas privados.

## 11. Entregas 4B.1, 4B.2 y 4B.3

### 4B.1: DDL cerrado y validación

Tras aprobación, convertir ocho tablas/índices/FK/CHECK en migración, RLS ENABLE/FORCE
sin GRANT de negocio. Revisar versión/catálogos/identidad/pendientes/dry-run antes de
aplicar; dry-run no prueba ejecución SQL. Validación solo PostgreSQL remoto de desarrollo,
dataset ficticio aislado autorizado; sin Docker/local ni reset del proyecto.

Puerta: revisión DDL y pruebas de cada FK/NULL/estado, unicidad de identidad/cabecera
con dos conexiones concurrentes, límites de índices, orden al COMMIT y tablas cerradas
sin políticas. Escritura y limpieza remotas requieren autorización, incluso con rollback.

### 4B.2: funciones, permisos y RLS

Tras aprobación, cuerpos/firmas completos, propietarios/GRANT/REVOKE y políticas por
comando. Provisionar capacidades operativas solo mediante mecanismo seguro autorizado,
sin secretos en chat/SQL versionado. No atestador SIGAC real.

Puerta: conexiones realmente restringidas API/sync y dos estudiantes ficticios; probar
PUBLIC EXECUTE, dueño sin BYPASSRLS, pg_temp malicioso, servicio incorrecto, contexto
faltante/ajeno, recursión RLS, reserva inicial, herencia, revocación, pool y fencing.
No basta postgres con GUC. Si falta cliente SQL, solicitar instalación antes de pruebas;
no habilitar permisos dejando evidencia RLS para después.

### 4B.3: adaptador Python y pruebas integradas

Tras aprobación, codec/importador/exportador/unidad de trabajo usando motor intacto.
Dependencia SQL con autorización previa. No SQLite, FastAPI, Expo, Auth real, SIGAC ni push.
Puerta: 241 pruebas actuales más paridad JSON/PostgreSQL, fallos, reinicios, cuotas y
privacidad. UUID nuevos se comparan por propiedades, no igualdad aleatoria entre motores.

| Grupo | Casos mínimos |
| --- | --- |
| Identidad/cabecera | Duplicado estable distinto hash falla; anónimos permitidos; dos cabeceras vivas concurrentes fallan; archivo histórico permitido. |
| FK/NULL/orden | Alcance/tenant ajeno, identidad parcial, UUID entre casos, status inválido, ordinal repetido/huecos y reordenación temporal. |
| Motor | Baseline cero; [A]→[B]→[A], [A,A]→[A]→[A,A], ambiguos repetidos, parciales sin borrado. |
| Contenido | Fecha/etapa/dirección/remitente/descripción y anexos añadidos/eliminados/repetidos/reordenados según contrato actual. |
| Autorización/RLS | Auth no concede SIGAC; no_verificado/denegado/caducado y simulador no permiten modo real; A no lee/escribe B con UUID conocidos. |
| Concurrencia | Dos procesos, lease vencido, worker viejo, generación CAS, revocación esperando locks y mismo idempotency_key. |
| Fallos | Error entre registros/eventos, desconexión antes/después de COMMIT, reinicio/deadlock: estado completo anterior o nuevo. |
| JSON/importación | Cabecera/caso vacío, orden/status, Unicode/NUL/sustitutos, enteros límite, revisiones incompatibles, corruptos, cuotas y reimportación. |
| Privacidad | Logs/errores/recibos sin contenido ni credenciales; purga A no afecta B; respaldos protegidos. |

Pruebas SQL remotas pendientes; no se presenta este diseño como validación PostgreSQL.

Validación local de esta revisión: **241 pruebas aprobadas en 7,85 s** con el
`.venv` existente, plugins externos deshabilitados y conexiones/DNS de Python
bloqueados. Sin bytecode ni caché pytest; archivos de prueba en directorio temporal
aislado, eliminado al terminar. No se añadieron pruebas persistentes ni dependencias.
Además se ejecutaron ejemplos ficticios en memoria que confirman las limitaciones
del parser descritas abajo, los UUID distintos para duplicados de línea base y
la existencia de UUID de seguimiento en un resultado ambiguo.

## 12. Parser SIGAC: diagnóstico y propuesta sin implementación

No usar HTML real ni incorporarlo al repositorio. No se crean fixtures/pruebas ni
se modifica código en esta entrega. Revisados parser.py, Actuacion, SigacService y tests.

| Limitación confirmada del parser | Efecto |
| --- | --- |
| Todos los tr y find(hr) recursivo | HR anidado puede abrir/cortar un bloque. |
| Exactamente tres filas hermanas con dos td | Pierde contenido variable, filas posteriores y ciertas envolturas tbody. |
| Comunicación exige --> | Descarta comunicación vacía; título vacío funciona si existe su fila. |
| Solo etiqueta Actuación en tercera fila | Reparto/Creación de cita/otros no se reconocen. |
| Solo primera fila de contenido | Cambiar filas posteriores puede dejar huella sin cambios. |
| Anexos solo fila inmediatamente siguiente | Pierde anexos separados; recorrido recursivo mezcla niveles. |
| Ruta endswith y URL externa rechazada | No garantiza endpoint/query exactos ni ausencia de fragmento; no descarga. |
| Service rechaza lista vacía, no pérdida parcial | Un parseo parcial puede sincronizarse sin diagnóstico. |

Diseño DOM propuesto:

1. Identificar contenedor único de historial por estructura/anchor demostrado,
   excluyendo tablaAnexos. No adivinar un ID desconocido; múltiples candidatas dan
   diagnóstico e impiden sincronización automática.
2. Filas cuyo ancestro table más cercano es el contenedor, también con tbody/thead.
   Separadores solo HR del nivel dueño en fila sin contenido semántico. Ignorar
   HR de tablas anidadas y dentro de contenido; no número fijo de filas.
3. Fecha/responsable según estructura conocida; título/comunicación opcionales.
   No inferir comunicación del responsable ni inventar fechas.
4. Cada fila relevante como etiqueta/valor/orden; conservar repeticiones, vacíos y
   etiquetas nuevas, excluyendo contenido de tablas de anexos. Normalización de
   saltos de línea explícita y determinista, sin borrar información relevante.
5. Anexos de todas las tablas tablaAnexos del bloque, sus filas propias; descripción,
   archivo/referencia sin GET. Endpoint relativo exacto general.descargarAnexo.con,
   sin host/esquema/fragmento; un solo codigo no vacío, sin query inesperada. Variantes
   no demostradas requieren revisión, no relajación silenciosa.
6. DTO con bloques/filas ordenadas/anexos/diagnóstico completo-parcial-no reconocido.
   BeautifulSoup repara HTML pero no prueba recuperación íntegra. Fecha/frontera
   irrecuperable impide confirmar; historial vacío se distingue de fallo de parseo.

Compatibilidad y decisiones antes de tocar código:

- DTO: título/comunicación opcionales, fecha, responsable, filas ordenadas y anexos.
  Actuacion permite origen/destino vacíos, adaptar_observacion(dict) no. Service
  conserva Actuacion; usar ese recorrido explícito, sin ampliar dict ocultamente.
  Dirección desconocida queda prioridad normal, --> interno no prueba comunicación.
- Título no está demostrado equivalente a etapa. Decidir mapeo. Representar filas
  etiquetadas en descripción con serialización determinista o ampliar modelo
  versionado son alternativas que requieren aprobación; no concatenar ambiguamente.
- identificador_origen=None. Código de descarga/fecha/posición/huella no son IDs
  estables; duplicados se conservan. Prioridad solo con comunicación observada.
- Huella legacy omite etapa/anexos; motor usa huella_version que sí los incluye.
  Conservar interfaz legacy o justificar expectativas; ninguna huella es identidad.
- Reconocer filas antes omitidas cambia contenido/huellas de estados existentes.
  Aprobar transición de interpretación con respaldo; nueva baseline solo explícita,
  advirtiendo novedades omitidas. No reset ni trust_policy recalculada automáticamente.
- Integrar rechazo de extracción parcial en Service es cambio funcional que también
  requiere aprobación. Motor v2.2 intacto, primera sincronización sin históricos.

Fixtures futuros enteramente sintéticos, sin nombres/personas/documentos/datos jurídicos:
título/comunicación vacíos y ausentes, etiquetas variables, filas repetidas/vacías,
duplicados, anexos separados/múltiples/repetidos/reordenados, HR anidados, tbody,
HTML malformado, enlaces inválidos y fecha ilegible. Mutar cualquier fila relevante
cambia huella; reordenar anexos no, duplicarlos sí. Integración motor: baseline y
repetición sin eventos; multiplicidad/cambios ambiguos según estado previo.

## 13. Aprobaciones pendientes y referencias

Revisar ocho tablas y aplazamientos, codec/cuotas y rechazo explícito fuera de límites;
contrato completo de funciones/RLS antes de 4B.2; dataset remoto y herramientas de
prueba, retención y eventual cambio de Automatically expose new tables. Para parser,
aprobar semántica título/etapa, filas, diagnóstico parcial y transición de huellas
por separado. No crear migraciones ejecutables antes de la revisión.

- [Índices únicos PostgreSQL](https://www.postgresql.org/docs/17/indexes-unique.html)
- [Restricciones y NULL](https://www.postgresql.org/docs/17/ddl-constraints.html)
- [RLS y propietarios](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)
- [CREATE FUNCTION y SECURITY DEFINER](https://www.postgresql.org/docs/17/sql-createfunction.html)
- [Aislamiento](https://www.postgresql.org/docs/17/transaction-iso.html)
- [Seguridad Data API Supabase](https://supabase.com/docs/guides/api/securing-your-api)
