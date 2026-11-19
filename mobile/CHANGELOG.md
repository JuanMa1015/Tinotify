# Changelog

Formato Keep a Changelog; versionado semántico.

## [0.1.0] - 2026-11-19
Primer lanzamiento para una beta cerrada.

### Añadido
- **Seguimiento de SIGAC**: la app revisa tu cuenta tres veces al día (7:30, 12:30 y 18:30) y te avisa de las actuaciones y expedientes nuevos por notificación y por correo, con el radicado, la etapa y el sentido de cada actuación.
- **Novedades**: pestaña con solo las actuaciones nuevas, agrupadas por día, con su detalle.
- **Casos**: listado de expedientes con estado, búsqueda, filtros, detalle de actuaciones en vivo y descarga de anexos.
- **Acceso sin contraseñas**: registro por invitación y entrada con un código de 6 dígitos enviado al correo (que además verifica el correo donde llegan los avisos).
- Huella o rostro para abrir la aplicación, ofrecida tras la primera entrada.
- **Administración**: panel para crear invitaciones, suspender o reactivar cuentas, dar o quitar administración, vaciar datos de seguimiento y eliminar cuentas. Nunca muestra claves de SIGAC ni el contenido de los expedientes.
- Aviso de «Revisión atrasada» si una revisión programada no se hizo.
- Textos de privacidad y consentimiento; los datos sensibles se guardan cifrados y las actuaciones nuevas, solo como una ficha corta por 90 días.
- Tema claro azul con acentos lima.

### Notas
- El APK se compila en GitHub Actions y se publica en el release de cada versión (ver docs/lanzamiento.md).
