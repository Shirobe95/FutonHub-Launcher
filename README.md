# FutonHUB Launcher 0.14.0

Launcher autónomo para Windows. Instala, actualiza, valida y abre FutonHUB sin que el trabajador tenga que usar Git, Python ni consola.

## Interfaz

- Vista compacta con logo FutonEspai.
- Botón principal: **Abrir FutonHUB**.
- Botón secundario: **Comprobar**.
- Detalles técnicos plegables.
- Panel de administración oculto por defecto. Se muestra con `Ctrl+Shift+A` o configurando `worker_mode=false`.
- Errores con ventana visual y botón para copiar el mensaje de soporte.

## Canales de actualización

- **FutonHUB ERP:** repositorio privado `Shirobe95/FutonEspaiHUB`, rama `main`, comparación por commit.
- **Launcher:** repositorio público `Shirobe95/FutonHub-Launcher`, Releases `launcher-vX.Y.Z`, verificación SHA-256 y reemplazo transaccional.

El token privado del ERP se guarda en Windows Credential Manager y no se envía al repositorio público del launcher.

## Build local

```text
run_tests.bat
build_launcher.bat
```

Artefactos:

```text
dist/FutonHUB-Launcher.exe
dist/FutonHUB-Launcher.exe.sha256
```

## Release

Tras subir el código a `main` y ver CI en verde, ejecutar **Publish launcher release** con la versión exacta, por ejemplo `0.14.0`.
