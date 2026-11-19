# Cómo lanzar una versión de la app

El APK se compila en **GitHub Actions** (gratis, sin depender de ningún equipo personal ni de las builds de Expo) y queda en el **release** de
GitHub, con un enlace fijo para pasarlo a las personas.

## Una sola vez: preparar los 5 secretos

En GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Los valores no se escriben en ningún archivo del repositorio.

### 1. La clave de firma (keystore)
Es la identidad de la app: **todas las versiones futuras deben firmarse con la misma**; si se pierde, nadie podrá actualizar y habrá que reinstalar.
**Guarda una copia del archivo y de las contraseñas en un lugar seguro y privado (gestor de contraseñas).**

En PowerShell (Java incluye `keytool`; si no lo encuentra, usa el de Android Studio):

```powershell
keytool -genkeypair -v -keystore tinotify-release.jks -alias tinotify -keyalg RSA -keysize 2048 -validity 10000
```

Te pide una contraseña del almacén, tus datos (pueden ser mínimos) y la contraseña de la clave (puede ser la misma). Luego convierte el archivo a texto:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("tinotify-release.jks")) | Set-Clipboard
```

| Secreto | Valor |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | El texto que acabas de copiar (el portapapeles) |
| `ANDROID_KEYSTORE_PASSWORD` | La contraseña del almacén |
| `ANDROID_KEY_ALIAS` | `tinotify` |
| `ANDROID_KEY_PASSWORD` | La contraseña de la clave |

### 2. Firebase (notificaciones)
| Secreto | Valor |
|---|---|
| `GOOGLE_SERVICES_JSON` | El **contenido completo** de `google-services.json` de la app `com.tinotify.app` (Firebase → Configuración del proyecto → Tus apps → Android → Descargar) |

## Publicar una versión

1. Actualiza `version` en `mobile/app.config.ts` y el `mobile/CHANGELOG.md`, y fusiona esos cambios en `main`.
2. Crea y sube la etiqueta desde `main`:

   ```powershell
   git checkout main; git pull
   git tag v0.1.0
   git push origin v0.1.0
   ```

   Las **notas del release se generan solas**: toman la sección `## [x.y.z]` del `CHANGELOG`, añaden las instrucciones de instalación, el SHA-256 del APK y los avisos
   importantes, y marcan como *pre-lanzamiento* las versiones `0.x`. Por eso la sección de la versión debe existir en el CHANGELOG **antes** de crear la etiqueta.
3. En la pestaña **Actions → apk-release** se ve la compilación (unos 15 a 25 minutos). Al terminar, el APK queda en **Releases → v0.1.0**
   junto a su `.sha256`.
4. Pasa a las personas el enlace del release (o el archivo `.apk`).

Para probar la compilación sin publicar: **Actions → apk-release → Run workflow**. El APK queda como artefacto durante 5 días.

## Instalar el APK en un teléfono
1. Abrir el enlace del release en el teléfono y descargar el archivo `.apk`.
2. Android pedirá permitir instalar desde esa fuente (el navegador o el gestor de archivos): aceptar solo para esta instalación.
3. Abrir Tinotify, tocar **Crear cuenta con invitación** y escribir el código que dio quien administra.

## Notas
- El APK incluye las arquitecturas arm64 y armeabi-v7a (prácticamente todos los teléfonos Android actuales).
- La clave de firma cambia respecto a las builds anteriores de Expo: quien tenga instalada una build anterior debe **desinstalarla** antes de instalar la del release.
- `versionCode` es el número de ejecución del workflow: siempre crece, así que cada release se puede instalar encima del anterior.
