# FutonHUB Launcher 0.11.1

Launcher autónomo para Windows. Cada equipo recibe una sola vez `FutonHUB Launcher.exe`.

Al abrirlo:

1. crea `%LOCALAPPDATA%\FutonHUB`;
2. solicita una vez un token GitHub fine-grained de solo lectura;
3. consulta `Shirobe95/FutonEspaiHUB`, rama `refactor/modularizacion-v1`;
4. compara el commit local y remoto;
5. instala Python 3.13.14 si no hay un Python compatible;
6. prepara un entorno aislado por hash de dependencias;
7. instala o actualiza con staging, health check, backup y rollback;
8. conserva `.env`, SQLite, constantes, Excel y datos locales;
9. abre el ERP con el runtime administrado, manteniendo `Abrir ERP.bat` como respaldo manual.

LAUNCH-011.1 corrige la descarga del snapshot GitHub (`HTTP 415`) usando el tipo de contenido exigido por el endpoint `zipball`.

## Construcción del EXE

En la máquina de administración:

```text
run_tests.bat
build_launcher.bat
```

Entregable final:

```text
dist/FutonHUB Launcher.exe
```

Ese EXE es lo único que se entrega a cada máquina. No necesitan Git, Python ni Release Manager.

## Acceso al repositorio privado

La primera ejecución solicita un token fine-grained limitado al repositorio `FutonEspaiHUB` con permiso `Contents: Read-only`. Se guarda en Windows Credential Manager y nunca en JSON, `.env` ni logs.
