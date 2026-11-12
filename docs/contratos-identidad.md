# Contratos de identidad de origen

## Tres decisiones diferentes

1. **Sintaxis:** `IdentificadorCandidato` valida un valor observado y describe el
   sistema y mecanismo que se declaran como procedencia. No demuestra que el
   valor sea único, estable, auténtico o que identifique una actuación.
2. **Revisión:** un contrato necesita evidencia real y revisión de sus garantías
   antes de incorporarse al catálogo de código confiable.
3. **Habilitación:** la política puede habilitar una referencia exacta que ya
   figure en ese catálogo. La configuración no puede crear esa evidencia ni
   añadir contratos no revisados.

`IdentificadorSigac` se conserva como alias de `IdentificadorCandidato`.
Construirlo nunca habilita el emparejamiento estable. Tampoco lo hace construir
manualmente un `IdentificadorEstableVerificado`: el motor revalida su afirmación
contra la política vigente y el contexto de cada operación.

## Definición del contrato

`ContratoOrigen` contiene:

| Campo | Significado |
| --- | --- |
| `clave`, `version` | Identificación y versión del contrato |
| `sistema` | Sistema que proporciona el identificador |
| `mecanismo` | Campo o mecanismo de extracción revisado |
| `alcance` | Actualmente solo unicidad por caso dentro de una instancia |
| `garantias` | Garantías explícitas de estabilidad, unicidad y no reutilización |
| `evidencia` | Referencia documental, huella del documento y justificación |

La referencia del contrato incluye clave, versión y huella de su definición
completa, incluida la evidencia. Modificar su mecanismo, alcance, garantías o
justificación cambia la referencia. El catálogo rechaza dos definiciones de
una misma clave y versión. La política informa `NO_REVISADO`, `DESHABILITADO` o
`HABILITADO` por separado de la descripción del contrato.

La aplicación comprueba tipos, estructura, consistencia y pertenencia al catálogo.
**No puede demostrar por sí sola que una garantía externa sea verdadera.** Un
documento nombrado, su hash o una justificación escrita no equivalen a una
auditoría. Admitir una entrada en `CatalogoContratosRevisados` es una operación
de composición de código confiable que requiere revisión previa real. Ese
catálogo nunca debe construirse a partir de JSON, solicitudes, estado persistido
o variables de entorno. No hay cargador que lo haga.

El código de aplicación que puede sustituir el catálogo forma parte de la base
de confianza; no se pretende defender el proceso frente a código Python malicioso
con los mismos privilegios. El adaptador futuro también deberá acreditar que los
datos proceden del sistema y mecanismo revisados, no de etiquetas del cliente.

## Estado actual de producción

`CATALOGO_PRODUCCION` está vacío. La política predeterminada no habilita ningún
ID estable de SIGAC. No se ha consultado SIGAC ni se dispone de evidencia real
suficiente. El parser no deduce IDs de atributos HTML ni de códigos de anexos.

Los contratos sintéticos están definidos exclusivamente en `backend/tests` y
se inyectan explícitamente en las pruebas que necesitan identidad estable. No
se incluyen en el catálogo de producción ni se activan por variables de entorno.
Crear un booleano `True`, una definición o una referencia aislada no habilita
ningún contrato en la política predeterminada.

## Aplicación y alcance

Para utilizar una identidad estable se necesitan candidato, referencia revisada
y habilitada, y `ContextoOrigen(instancia, caso)`. Sistema y mecanismo deben
coincidir con el contrato. El motor valida de nuevo la referencia, la habilitación
y el contexto. Si la afirmación entrante no satisface esas condiciones, se trata
como candidato y se aplica reconciliación conservadora.

La clave estable contiene contrato, versión/revisión, instancia, caso y valor.
No se emparejan IDs de casos, instancias, mecanismos o contratos diferentes.
Una sustitución entre contratos con registros anteriores ausentes queda ambigua;
no se presume que dos espacios de identidad distintos sean equivalentes.

Sin identidad estable se mantiene la comparación exacta por versión y cantidad.
Un candidato repetido puede aparecer en dos ocurrencias distintas; no se usa su
valor para fusionarlas. Una coincidencia sintáctica tampoco confirma ediciones.
Los UUID locales de ocurrencias indistinguibles siguen sin demostrar identidad
física. Estos contratos identifican actuaciones: no autentican estudiantes ni
conceden permisos sobre expedientes.

## Persistencia v2, revisión 2

El esquema exterior sigue en versión 2 y ahora exige `state_revision=2`.
La huella de contenido conserva `fingerprint_version=1`: esta corrección no
modifica la normalización del contenido ni la política de multiplicidad.

El sobre añade `trust_policy`, huella de las referencias habilitadas y de la
instancia. **No es una firma criptográfica ni prueba de confianza.** Se utiliza
para detectar cambios de política; siempre se consulta además el catálogo vivo.

Cada registro contiene los campos anteriores y estos metadatos:

- `contract_ref`: clave, versión y revisión del contrato, o `null`.
- `origin_scope`: instancia y caso, o `null`.
- `source_id`: solo se persiste para identidades verificadas bajo política vigente.

Los candidatos no se guardan como IDs estables. El estado no contiene el catálogo
ni puede introducir entradas mediante metadatos o una supuesta evidencia.
Al cargar registros con identidad estable se comprueban sus referencias y alcance
contra la política del proceso. Una huella de política falsificada en el archivo
no basta para habilitar contratos ausentes o deshabilitados.

Un atacante con capacidad de alterar el archivo puede corromper o falsificar
otros datos; este mecanismo no autentica criptográficamente todo el estado.
La protección del almacenamiento sigue siendo una tarea separada.

## Transiciones explícitas y sin sobrescritura

Los v2 anteriores sin `state_revision` se reconocen como revisión 1. No se elevan
sus `source_id` a verificados. Cargarlos lanza `TransicionRequerida`, igual que
perder un contrato vigente, cambiar de instancia o alterar las referencias
habilitadas. Se detiene el seguimiento antes de emitir eventos o escribir.

`MonitorActuaciones.transicionar_estado(origen, destino, ...)` admite v1, v2.1
o v2.2 estructuralmente válidos. Es una operación explícita del operador, nunca
una conversión automática. Valida el archivo, exige destino diferente y ausente,
y crea un v2.2 vacío con la política elegida. Las revisiones desconocidas o estados
corruptos se rechazan; el origen queda intacto incluso ante fallos capturados de
escritura. Tampoco se reemplaza un destino ya existente.

`migrar_estado_v1` mantiene su interfaz y solo admite v1, con las mismas reglas.
No se ejecutan motores antiguos en paralelo dentro del programa.

La transición reinicia la línea base y las identidades locales del nuevo archivo;
no reconstruye identidades a partir de hashes o IDs sin evidencia. La primera
consulta de cada caso no emite avisos históricos, aunque contenga muchos
registros. Las consultas repetidas tampoco los emiten. Esto evita una avalancha
de avisos al retirar confianza, pero **puede omitir novedades durante el cambio**
y rompe la continuidad de UUID entre archivos. Debe quedar registrada como una
decisión explícita, con el origen conservado y un único destino activo.

No se realizaron transiciones sobre estados reales durante esta corrección.
