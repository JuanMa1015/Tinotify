# Diseño: cuentas, registro y login multiusuario

Estado: propuesta. Hoy el sistema es de un solo usuario (un token único, una fila de credenciales, una referencia acreditada).

## Decisiones propuestas
1. **Registro por invitación (decidido).** Solo se crea cuenta con un código de invitación generado por el administrador. Evita guardar credenciales de desconocidos y limita la carga sobre SIGAC. Registro abierto: se evalúa tras el ensayo.
1b. **Identificador: solo el correo (decidido).** No se añade nombre de usuario: con pocos invitados no aporta, obliga a validar unicidad y a aceptar dos formas de entrar, y el correo ya hace falta para los avisos. Si más adelante hay muchos usuarios, se reevalúa.
2. **Identidad de la app separada de SIGAC.** Cuenta Tinotify = correo verificado con un código de un solo uso (sin contraseña propia). Las credenciales de SIGAC son un dato aparte, guardado cifrado, por usuario.
3. **Código de acceso:** de 8 caracteres sin ambiguos (~40 bits), 15 minutos, un solo uso y 5 intentos; en la base solo su SHA-256 ligado al usuario. El de registro (cuenta nueva) no se guarda: es un HMAC del correo y la invitación, válido entre 10 y 20 minutos.
4. **Sesiones por dispositivo:** token aleatorio de 256 bits; en la base solo su SHA-256. Caduca (30 días), se puede revocar una a una, y una cuenta suspendida las pierde todas.
5. **Biometría:** desbloquea localmente el token guardado en el almacén seguro del teléfono; la app la ofrece tras la primera entrada.
6. **Consentimiento:** se registra por usuario (versión y fecha) antes de aceptar credenciales de SIGAC.

## Modelo de datos (esquema `tinotify_real`)
- `usuarios(id, correo_hash, correo_cifrado?, pass_hash, creado_en, consentimiento_version, consentimiento_en, activo)`
- `invitaciones(codigo_hash, creado_por, usado_por, usado_en, expira_en)`
- `sesiones(id, usuario_id, token_hash, dispositivo, creado_en, expira_en, revocada_en)`
- Añadir `usuario_id` (con RLS por usuario) a: `credenciales`, `estado_expediente`, `huellas`, `avisos`, `ejecuciones`, `dispositivos`.
- `caso_ref` y huellas con clave derivada **por usuario** (misma llave maestra + `usuario_id`), para que dos usuarios con el mismo expediente no se correlacionen.

## Endpoints nuevos
`POST /auth/registro/codigo` (correo, invitación) · `POST /auth/registro` (correo, código, invitación, consentimiento) · `POST /auth/entrar/codigo` (correo) · `POST /auth/entrar` (correo, código) · `POST /auth/logout` · `DELETE /auth/cuenta` (escribe el correo; borra todo) · `GET /auth/yo` · administración en `/admin/usuarios`.
Los endpoints actuales `/real/*` pasan a requerir la sesión de usuario y a operar solo sobre sus datos. El token del monitor (GitHub Actions) sigue existiendo y ejecuta usuario por usuario.

## Ejecución del monitor
`POST /real/monitor/ejecutar` recorre usuarios activos con credenciales, uno por llamada interna y con tiempo limitado; un fallo de un usuario no detiene a los demás. Con ~3 minutos por usuario, la ejecución se divide: Actions llama por usuario (o por lotes) en vez de una sola llamada larga.

## Identidad de expedientes
La referencia acreditada hoy es de una sola persona. Para los demás usuarios los expedientes se tratan como **provisionales**: línea base silenciosa y avisos de novedades por diferencia de huellas, sin la validación de identidad reforzada. Documentar esa limitación al usuario.

## Seguridad y abuso
Límite de intentos por correo e IP, bloqueo temporal, mensajes de error que no revelan si el correo existe, y registro de eventos sin datos personales.

## Fases (un PR por fase)
1. Esquema SQL + migración (el SQL lo ejecuta el administrador en Supabase) y servicio de cuentas/sesiones con tests.
2. Datos por usuario en el almacén y en el monitor; ejecución por usuario.
3. App: pantallas de registro, login, "olvidé mi contraseña" (si se decide), consentimiento y biometría.
4. Actions: ejecución por usuario y avisos por usuario (correo destino o push por dispositivo).
5. Revisión legal y apertura a los invitados.
