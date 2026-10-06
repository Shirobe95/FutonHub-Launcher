# LAUNCH-014 · Visual compacto, errores reportables y autoactualización del launcher

## Objetivo

Transformar el launcher en una herramienta más limpia para trabajadores: menos ruido técnico, botones de administración ocultos, cabecera FutonEspai y errores copiables para soporte.

## Cambios aplicados

1. Interfaz compacta de 590×430.
2. Cabecera con marca visual FutonEspai y versión propia del launcher.
3. Tarjetas centrales para versiones de FutonHUB.
4. Botón principal **Abrir FutonHUB**.
5. Botón **Comprobar** para instalación y actualización.
6. Detalles técnicos plegables.
7. Panel de administración oculto por defecto.
8. Atajo `Ctrl+Shift+A` para mostrar/ocultar administración.
9. Botones GitHub, .env, Logs y Desinstalar retirados de la vista de trabajador.
10. Popups visuales de error con mensaje preparado para copiar y enviar a soporte.
11. Botón **Copiar mensaje** dentro del popup.
12. Botón **Abrir logs** dentro del popup cuando aplica.
13. Aviso visual específico cuando la actualización del launcher falla sin impedir abrir FutonHUB.
14. Se conserva autoactualización del launcher desde GitHub Releases.
15. Se conserva verificación SHA-256 y reemplazo transaccional.

## Archivos modificados

- `futonhub_auto/__init__.py`
- `futonhub_auto/config.py`
- `futonhub_auto/gui.py`
- `futonhub_auto/dialogs.py`
- `assets/version_info.txt`
- `assets/futonespai_logo.png`
- `assets/futonespai_logo.png.b64`
- `build_launcher.bat`
- `tests/test_distribution.py`
- `README.md`
- `CHANGELOG.md`

## Confirmaciones

- No se modificó la lógica de descarga del ERP.
- No se modificó la verificación de integridad del ERP.
- No se modificaron rutas de instalación.
- No se tocó `.env`.
- No se tocaron credenciales.
- No se requiere Git en máquinas cliente.
- La comparación de FutonHUB sigue usando commits.
- La versión visible de FutonHUB sigue siendo SemVer.
- La autoactualización del launcher sigue usando Releases públicas y SHA-256.
- No se ejecutó Git.

## Validación

```text
75 tests OK
compileall OK
```

## Smoke manual pendiente

1. Construir `dist/FutonHUB-Launcher.exe`.
2. Abrirlo en Windows.
3. Verificar vista compacta.
4. Confirmar que no aparecen botones de administración en modo trabajador.
5. Pulsar `Ctrl+Shift+A` y verificar que aparecen GitHub, .env, Logs y Desinstalar.
6. Confirmar que no aparece CMD al abrir el launcher ni al abrir FutonHUB.
7. Provocar un error controlado y verificar popup visual con mensaje copiable.
8. Publicar una Release posterior para validar actualización del launcher real.

## Versión final

```text
Launcher: 0.14.0
```
