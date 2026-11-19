# Política de tratamiento de datos personales de Tinotify

Versión: 0.1 (borrador) · Fecha: `[FECHA]`

## 1. Responsable
`[RESPONSABLE]`. Contacto para consultas, reclamos y ejercicio de derechos: `[CONTACTO]`.

## 2. Qué es Tinotify
Un servicio que, con tu autorización, entra a tu cuenta de SIGAC tres veces al día (7:30, 12:30 y 18:30, hora de Bogotá), detecta si hay actuaciones o expedientes nuevos y te avisa. Tinotify **no está afiliado a SIGAC** ni lo reemplaza: revisa SIGAC cuando necesites certeza.

## 3. Qué datos tratamos y cómo
| Dato | Para qué | Cómo se protege |
|---|---|---|
| Usuario y contraseña de SIGAC | Iniciar sesión en tu nombre para revisar tu cuenta | Cifrados (AES-256-GCM) en el servidor. La llave solo existe en la configuración del servicio de aplicación, no en la base de datos. Nunca se guardan en tu teléfono. |
| Huellas de tus actuaciones | Detectar qué es nuevo comparando con la revisión anterior | Resúmenes con clave (HMAC): no permiten reconstruir el texto. |
| Ficha de cada actuación **nueva** (fecha, etapa, sentido, remitente y un extracto de hasta 240 caracteres de su texto) | Mostrarte el apartado de Novedades y detallar los avisos | Cifrada (AES-256-GCM), ligada a su expediente; se conserva **90 días** y luego se borra. No guardamos el historial completo de tus actuaciones ni sus anexos: el detalle y los archivos se leen de SIGAC cuando los abres. Pueden contener datos personales de terceros. |
| Listado de tus expedientes (radicado, nombre del cliente y estado, tal como los muestra SIGAC) | Mostrarte la lista de expedientes al instante y señalar cuáles tienen novedades | Cifrados (AES-256-GCM) con la misma llave del servicio, ligados a cada expediente: la base de datos solo contiene texto cifrado. Se descifran en el servidor únicamente para enviártelos a ti. Contienen datos personales de terceros (nombres de clientes): tú eres responsable de tener autorización para tratarlos. |
| Tu nombre en SIGAC | Saludarte por tu nombre en la app | El servidor lo lee del encabezado de SIGAC cuando la app lo pide y lo entrega a tu teléfono; **no se guarda en el servidor ni en la base de datos**. En el teléfono se conserva en el almacén seguro y se borra al cerrar sesión. |
| Conteos y resultados de revisión | Mostrar el estado y decidir si avisar | Solo cifras y estados (por ejemplo "ok" o "error de acceso"). |
| Código de acceso al servidor | Autenticar tu app ante el servidor | Almacén seguro del teléfono; con huella o rostro si lo activas. |
| Destino de avisos (correo o dispositivo) | Enviarte los avisos | Solo para avisos. Los avisos nombran el radicado y la etapa de la actuación nueva; en el correo, además, el nombre del cliente. |

Durante cada revisión el servidor lee tu historial de SIGAC **en memoria** para calcular las huellas y lo descarta al terminar. Las cookies de SIGAC viven solo en memoria durante la lectura. La app móvil no usa cookies, rastreadores ni analítica.

## 4. Finalidades
Solo: (a) revisar tu cuenta de SIGAC por ti, (b) avisarte de novedades y (c) operar y proteger el servicio. No vendemos ni cedemos tus datos ni los usamos para publicidad.

## 5. Terceros que intervienen (encargados)
Render (alojamiento del servidor), Supabase (base de datos), GitHub (ejecución programada) y Google (envío de correo y, si se activan, notificaciones). Varios operan **fuera de Colombia** (por ejemplo, en Estados Unidos). Al autorizar este tratamiento autorizas esa transferencia internacional para las finalidades anteriores.

## 6. Tus derechos
Conocer, actualizar, rectificar y suprimir tus datos, revocar la autorización y presentar quejas ante la Superintendencia de Industria y Comercio. Puedes ejercerlos en la app (Ajustes → "Olvidar mis credenciales", que borra del servidor tus credenciales y estado) o escribiendo a `[CONTACTO]`.

## 7. Conservación
Mientras mantengas la autorización. Al revocarla o borrar tu cuenta se eliminan tus credenciales cifradas y tu estado; los registros técnicos mínimos se conservan por `[PLAZO]` por seguridad.

## 8. Seguridad y límites
Aplicamos cifrado, acceso restringido y mínimo de datos, pero ningún sistema es infalible. Los avisos son una ayuda y pueden retrasarse o fallar (por ejemplo, si SIGAC no responde). Si cambias tu clave de SIGAC debes actualizarla en la app.

## 9. Menores de edad
Tinotify es para mayores de 18 años.

## 10. Cambios
Si cambia lo que guardamos o su finalidad, publicaremos una nueva versión y la app pedirá de nuevo tu autorización.
