# Smoke Windows · LAUNCH-014

## Preparación

Ejecutar en la raíz del repositorio:

```text
run_tests.bat
build_launcher.bat
```

Abrir:

```text
dist\FutonHUB-Launcher.exe
```

## Validación visual

- Cabecera con FutonEspai/FutonHUB.
- Ventana compacta.
- Botones visibles para trabajador: **Abrir FutonHUB**, **Comprobar**, **Detalles técnicos**.
- No se muestran GitHub, .env, Logs ni Desinstalar en modo normal.
- `Ctrl+Shift+A` muestra/oculta el panel de administración.

## Validación funcional

- El launcher comprueba FutonHUB.
- Las versiones aparecen como SemVer.
- **Abrir FutonHUB** abre el ERP.
- No aparece CMD durante el uso normal.
- **Detalles técnicos** muestra/oculta el log interno.

## Validación de errores

Provocar un error controlado, por ejemplo token inválido o fallo temporal de red. Debe aparecer un popup visual con:

- título claro;
- resumen entendible;
- mensaje para soporte;
- botón **Copiar mensaje**;
- botón **Abrir logs** cuando aplica.

## Validación autoactualización launcher

Para prueba real se necesita una Release posterior, por ejemplo:

```text
launcher-v0.14.1
```

El launcher instalado debe detectar versión superior, descargar `FutonHUB-Launcher.exe`, verificar SHA-256, reemplazarse y reiniciar.
