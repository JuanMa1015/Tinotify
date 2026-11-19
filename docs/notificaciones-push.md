# Notificaciones push (Firebase Cloud Messaging)

**Estado: implementado.** Cada revisión que detecta novedades envía una notificación a los teléfonos de esa persona; el correo de aviso es el
respaldo, con reintentos.

## Flujo

1. La app pide permiso, obtiene el **token FCM del dispositivo** (`expo-notifications`, `getDevicePushTokenAsync`) y lo registra con
   `POST /real/dispositivos` usando su sesión. Cada token pertenece a una sola cuenta: un teléfono recibe los avisos de la última cuenta que los activó.
2. El servidor guarda el token en `tinotify_real.dispositivos`, ligado a la persona.
3. Al cerrar una revisión que crea un aviso, el servidor envía **un intento** de mensaje FCM a los dispositivos **de esa persona** (API HTTP v1, con la cuenta
   de servicio) y registra el resultado del canal (`enviado`, `fallido`, `sin_dispositivos` o `no_configurado`), que la app muestra en *Actividad*.
4. Si FCM responde que el token ya no existe o no es válido, se borra el dispositivo.
5. El correo de aviso lo envía el ciclo de GitHub Actions y es independiente del push.

## Contenido del mensaje

Título «Tinotify» y un cuerpo con el radicado y, cuando hay una sola actuación nueva, su etapa y su sentido; por ejemplo:
`1 actuación nueva en el radicado 12345: <etapa> (ASESOR → ESTUDIANTE)`. Con varios expedientes se listan hasta tres radicados y luego se cuentan.
**Nunca** viaja el texto de la actuación ni el nombre del cliente. El mensaje se marca como **privado** (`visibility: PRIVATE`): con la pantalla bloqueada y
la seguridad del teléfono activa, Android oculta el texto hasta desbloquear.

En `data` el mensaje lleva `{tipo, pestana, expediente?}`. Al tocar la notificación, la app abre la pestaña correspondiente y, si el aviso es de un único
expediente, abre directamente ese expediente (por su identificador opaco).

## Configuración

| Qué | Dónde | Notas |
| --- | --- | --- |
| Proyecto de Firebase con una app Android `com.tinotify.app` | Consola de Firebase (plan Spark, gratis) | |
| **Cuenta de servicio** con el rol de Firebase Cloud Messaging | Render → *Secret File*; su ruta en `TINOTIFY_RR_FCM_CUENTA_SERVICIO` | Nunca en el repositorio |
| `google-services.json` de la app | Secreto `GOOGLE_SERVICES_JSON` de GitHub Actions (para compilar el APK) | Está en `.gitignore`; nunca en el repositorio |

Sin `TINOTIFY_RR_FCM_CUENTA_SERVICIO`, el servicio funciona igual pero marca el canal de push como `no_configurado`. La variable se añade **después** de desplegar el
código que la reconoce (ver [despliegue](despliegue-real-remoto-render.md#6-desplegar-una-versión-del-backend)).

## Comprobación

En la app, *Ajustes → Notificaciones → Enviar notificación de prueba* envía un mensaje a los teléfonos registrados sin tocar expedientes ni avisos.
