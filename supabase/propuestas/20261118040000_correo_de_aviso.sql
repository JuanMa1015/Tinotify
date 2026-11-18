-- Correo de aviso de cada usuario, CIFRADO. PROPUESTA: NO aplicada a Supabase. SOLO ADITIVA (dos columnas anulables en usuarios).
-- La llave de cifrado no esta en la base: vive solo como secreto del servicio. Sin ella, estas columnas no sirven. Las cuentas ya
-- creadas quedan en NULL (sin correo de aviso: solo reciben notificacion en el telefono).
-- Requiere la migracion de cuentas (20261118000000). Reversion: 20261118040000_correo_de_aviso_down.sql
BEGIN;
DO $precondiciones$
BEGIN
    IF to_regclass('tinotify_real.usuarios') IS NULL THEN
        RAISE EXCEPTION 'Falta la migracion de cuentas (20261118000000).';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'tinotify_real' AND table_name = 'usuarios'
               AND column_name IN ('correo_nonce', 'correo_cifrado')) THEN
        RAISE EXCEPTION 'Las columnas de correo ya existen; revisar en lugar de reutilizar.';
    END IF;
END;
$precondiciones$;

ALTER TABLE tinotify_real.usuarios
    ADD COLUMN correo_nonce bytea CHECK (correo_nonce IS NULL OR octet_length(correo_nonce) = 12),
    ADD COLUMN correo_cifrado bytea CHECK (correo_cifrado IS NULL OR octet_length(correo_cifrado) BETWEEN 17 AND 1024),
    ADD CONSTRAINT correo_completo CHECK ((correo_nonce IS NULL) = (correo_cifrado IS NULL));

DO $auditoria$
DECLARE rol text;
BEGIN
    FOREACH rol IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
        IF has_table_privilege(rol, 'tinotify_real.usuarios', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
           OR has_any_column_privilege(rol, 'tinotify_real.usuarios', 'SELECT,INSERT,UPDATE,REFERENCES') THEN
            RAISE EXCEPTION 'Permiso residual de cliente en tinotify_real.usuarios';
        END IF;
    END LOOP;
END;
$auditoria$;
COMMIT;
