-- Ejecutado como tinotify_real_login (miembro de tinotify_real_app). Solo datos ficticios.
\set ON_ERROR_STOP on
SET client_min_messages = notice;
CREATE FUNCTION pg_temp.debe_pasar(consulta text, etiqueta text) RETURNS void LANGUAGE plpgsql AS $f$
BEGIN
  EXECUTE consulta;
  RAISE NOTICE 'OK_POSITIVO %', etiqueta;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION 'FALLO_POSITIVO % (%: %)', etiqueta, SQLSTATE, SQLERRM;
END $f$;
CREATE FUNCTION pg_temp.debe_fallar(consulta text, etiqueta text) RETURNS void LANGUAGE plpgsql AS $f$
BEGIN
  BEGIN
    EXECUTE consulta;
  EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'OK_NEGATIVO % [%]', etiqueta, SQLSTATE;
    RETURN;
  END;
  RAISE EXCEPTION 'DEBIA_FALLAR %', etiqueta;
END $f$;

-- Operaciones legitimas de la aplicacion
SELECT pg_temp.debe_pasar($q$SELECT 1 FROM tinotify_real.entorno WHERE proposito = 'real'$q$, 'leer entorno');
SELECT pg_temp.debe_pasar($q$INSERT INTO tinotify_real.credenciales (version_llave, nonce, cifrado) VALUES (1, decode(repeat('00',12),'hex'), decode(repeat('ab',40),'hex'))$q$, 'insertar credenciales');
SELECT pg_temp.debe_pasar($q$UPDATE tinotify_real.credenciales SET cifrado = decode(repeat('cd',40),'hex'), actualizado_en = clock_timestamp()$q$, 'actualizar credenciales');
SELECT pg_temp.debe_pasar($q$DELETE FROM tinotify_real.credenciales$q$, 'olvidar credenciales');
SELECT pg_temp.debe_pasar($q$INSERT INTO tinotify_real.estado_expediente (caso_ref, actuaciones) VALUES (repeat('a',64), 3)$q$, 'insertar expediente');
SELECT pg_temp.debe_pasar($q$INSERT INTO tinotify_real.huellas (caso_ref, huella, cantidad) VALUES (repeat('a',64), repeat('b',64), 2), (repeat('a',64), repeat('c',64), 1)$q$, 'insertar huellas');
SELECT pg_temp.debe_pasar($q$UPDATE tinotify_real.huellas SET cantidad = 3 WHERE huella = repeat('b',64)$q$, 'actualizar cantidad');
SELECT pg_temp.debe_pasar($q$UPDATE tinotify_real.estado_expediente SET actuaciones = 4, generacion = 2, anomalia = true, acreditado = true, ultima_lectura = clock_timestamp()$q$, 'actualizar expediente');
SELECT pg_temp.debe_pasar($q$INSERT INTO tinotify_real.avisos (expedientes_con_novedades, novedades) VALUES (1, 2)$q$, 'crear aviso');
SELECT pg_temp.debe_pasar($q$UPDATE tinotify_real.avisos SET intentos = intentos + 1, entregado_en = clock_timestamp()$q$, 'marcar aviso entregado');
SELECT pg_temp.debe_pasar($q$INSERT INTO tinotify_real.ejecuciones (resultado) VALUES ('en_curso')$q$, 'iniciar ejecucion');
SELECT pg_temp.debe_pasar($q$UPDATE tinotify_real.ejecuciones SET fin = clock_timestamp(), resultado = 'ok', expedientes = 15, novedades = 0, codigo = 'sin_novedades'$q$, 'cerrar ejecucion');
SELECT pg_temp.debe_pasar($q$INSERT INTO tinotify_real.dispositivos (token) VALUES (repeat('t',40))$q$, 'registrar dispositivo');
SELECT pg_temp.debe_pasar($q$UPDATE tinotify_real.dispositivos SET ultimo_uso = clock_timestamp()$q$, 'tocar dispositivo');
SELECT pg_temp.debe_pasar($q$DELETE FROM tinotify_real.dispositivos$q$, 'borrar dispositivo');
SELECT pg_temp.debe_pasar($q$DELETE FROM tinotify_real.huellas WHERE caso_ref = repeat('a',64)$q$, 'borrar huellas');

-- Formatos cerrados
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.estado_expediente (caso_ref, actuaciones) VALUES ('no-es-hex', 1)$q$, 'caso_ref invalido');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.estado_expediente (caso_ref, actuaciones) VALUES (repeat('A',64), 1)$q$, 'caso_ref en mayusculas');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.estado_expediente (caso_ref, actuaciones) VALUES (repeat('d',64), 20001)$q$, 'demasiadas actuaciones');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.huellas (caso_ref, huella, cantidad) VALUES (repeat('a',64), 'texto judicial libre', 1)$q$, 'huella con texto');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.huellas (caso_ref, huella, cantidad) VALUES (repeat('a',64), repeat('e',64), 0)$q$, 'cantidad cero');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.huellas (caso_ref, huella, cantidad) VALUES (repeat('9',64), repeat('e',64), 1)$q$, 'huella de expediente inexistente');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.credenciales (version_llave, nonce, cifrado) VALUES (1, decode('00','hex'), decode(repeat('ab',40),'hex'))$q$, 'nonce corto');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.credenciales (version_llave, nonce, cifrado) VALUES (1, decode(repeat('00',12),'hex'), decode('ab','hex'))$q$, 'cifrado demasiado corto');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.avisos (expedientes_con_novedades, novedades) VALUES (0, 0)$q$, 'aviso vacio');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.avisos (expedientes_con_novedades, novedades) VALUES (1, 100001)$q$, 'aviso desmesurado');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.ejecuciones (resultado) VALUES ('texto libre')$q$, 'resultado fuera de catalogo');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.ejecuciones (resultado, codigo) VALUES ('ok', 'Codigo Con Espacios y Mayusculas')$q$, 'codigo libre');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.dispositivos (token) VALUES ('con espacio ' || repeat('x',30))$q$, 'token con espacios');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.dispositivos (token, plataforma) VALUES (repeat('u',40), 'ios')$q$, 'plataforma no admitida');

-- Privilegios: columnas no concedidas, DDL, TRUNCATE, otras tablas
SELECT pg_temp.debe_fallar($q$UPDATE tinotify_real.estado_expediente SET caso_ref = repeat('f',64)$q$, 'cambiar caso_ref');
SELECT pg_temp.debe_fallar($q$UPDATE tinotify_real.huellas SET huella = repeat('f',64)$q$, 'cambiar huella');
SELECT pg_temp.debe_fallar($q$UPDATE tinotify_real.avisos SET novedades = 99$q$, 'reescribir conteo del aviso');
SELECT pg_temp.debe_fallar($q$UPDATE tinotify_real.credenciales SET creado_en = now()$q$, 'cambiar creado_en');
SELECT pg_temp.debe_fallar($q$UPDATE tinotify_real.entorno SET version_esquema = 1$q$, 'actualizar entorno');
SELECT pg_temp.debe_fallar($q$INSERT INTO tinotify_real.entorno DEFAULT VALUES$q$, 'insertar entorno');
SELECT pg_temp.debe_fallar($q$DELETE FROM tinotify_real.avisos$q$, 'borrar avisos');
SELECT pg_temp.debe_fallar($q$DELETE FROM tinotify_real.ejecuciones$q$, 'borrar ejecuciones');
SELECT pg_temp.debe_fallar($q$DELETE FROM tinotify_real.estado_expediente$q$, 'borrar expedientes');
SELECT pg_temp.debe_fallar($q$TRUNCATE tinotify_real.huellas$q$, 'truncate');
SELECT pg_temp.debe_fallar($q$CREATE TABLE tinotify_real.intruso (x int)$q$, 'crear tabla en el esquema');
SELECT pg_temp.debe_fallar($q$CREATE TABLE public.intruso (x int)$q$, 'crear tabla en public');
SELECT pg_temp.debe_fallar($q$CREATE SCHEMA intruso$q$, 'crear esquema');
SELECT pg_temp.debe_fallar($q$ALTER TABLE tinotify_real.huellas DISABLE ROW LEVEL SECURITY$q$, 'desactivar RLS');
SELECT pg_temp.debe_fallar($q$SELECT 1 FROM tinotify_sintetico.casos$q$, 'esquema sintetico ajeno');
SELECT pg_temp.debe_fallar($q$CREATE ROLE otro LOGIN$q$, 'crear roles');
RESET ALL;
