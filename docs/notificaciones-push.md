# Notificaciones push (Firebase Cloud Messaging)

Estado: diseño y pasos de configuración. Aún sin código.

## Flujo
1. La app pide permiso, obtiene el **token FCM del dispositivo** (`expo-notifications`, `getDevicePushTokenAsync`) y lo envía a `POST /real/dispositivos` con su sesión.
2. El servidor lo guarda en `tinotify_real.dispositivos` (hoy sin dueño; en la fase 2 se añade `usuario_id`).
3. Al terminar una revisión con aviso nuevo, el servidor envía un mensaje FCM a los dispositivos **de ese usuario** (API HTTP v1, con la cuenta de servicio) y marca el aviso como entregado. Es el mismo outbox que usa el correo: si el envío falla, el aviso sigue pendiente.
4. Si FCM responde que el token no existe o no está registrado, se borra el dispositivo.

## Contenido del mensaje
Genérico y sin datos del caso: título "Tinotify", cuerpo "Hay novedades en SIGAC" (o "Un expediente nuevo en tu cuenta"). Los conteos pueden ir en `data`, nunca números ni textos de expedientes.

## Qué hace falta de tu lado (consola de Firebase)
1. Crear un proyecto en Firebase (plan Spark, gratis) y añadir una app Android con el paquete `com.tinotify.app`.
2. Descargar `google-services.json` (va a EAS como variable de entorno de tipo archivo y **nunca al repositorio**: ya está en `.gitignore`).
3. Crear una **cuenta de servicio** con el rol de Firebase Cloud Messaging y descargar su JSON. Va a Render como *Secret File*, no al repositorio.
4. Dime cuando esté, y conecto el envío y el registro del dispositivo.

## Cambios de código previstos
- Servidor: módulo de envío FCM v1 (token OAuth con la cuenta de servicio), ruta de registro de dispositivo y envío tras cada ejecución, con tests simulados.
- App: pedir permiso, registrar el token y manejar la notificación al abrirla.
- Si el usuario tiene push activo, el correo pasa a ser opcional.
- Requiere un build nuevo de la app (cambia la configuración nativa).
