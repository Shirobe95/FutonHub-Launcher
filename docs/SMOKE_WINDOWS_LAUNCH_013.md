# Smoke manual · LAUNCH-013

## Preparación

- Máquina Windows con Launcher anterior operativo.
- FutonHUB instalado en commit
  `4e18e5cd04aa71141be05adfc5a827b3fe7c43d7` (`v0.2.1`).
- Remoto `main` en commit
  `2b2eee8e1dfd976c5fa8d2e150d76938f1639990` (`v0.3.0`).
- `.env` autorizado ya configurado.

## Construcción

1. Copiar este paquete sobre el clon local de `FutonHub-Launcher`, sin copiar
   carpetas `.git`, `build`, `dist` ni entornos virtuales.
2. Ejecutar `run_tests.bat`.
3. Hacer el commit/push solo tras autorización.
4. Esperar a que `CI Launcher` finalice en verde.
5. Ejecutar `Publish launcher release` con `0.13.0`.

## Prueba funcional

1. Abrir `FutonHUB-Launcher.exe`.
2. Confirmar la cabecera `FutonHUB Launcher 0.13.0`.
3. Antes de finalizar la actualización, comprobar:

```text
Versión instalada: v0.2.1
Versión disponible: v0.3.0
Estado: Hay una nueva versión disponible
```

4. En Actividad confirmar los hashes completos de ambos commits.
5. Permitir la actualización automática.
6. Confirmar después:

```text
Versión instalada: v0.3.0
Versión disponible: v0.3.0
Estado: FutonHUB está actualizado
```

7. Abrir FutonHUB mediante el botón habitual y comprobar el ERP.
8. Cerrar Launcher y ERP.
9. Volver a abrir Launcher y verificar que `v0.3.0` sigue leyéndose desde la
   instalación real.

## Casos de tolerancia

- Renombrar temporalmente una copia de prueba de `pyproject.toml` y verificar el
  fallback a `__init__.py`.
- En una copia aislada sin fuentes SemVer, comprobar `Desconocida` sin bloqueo.
- No usar `Desinstalar…` durante este smoke.
