# Verificación realizada

Fecha de preparación: **4 de noviembre de 2026**.

## Resultado observado

La ejecución de `python -m pytest -q` terminó con:

```text
51 passed in 13.26s
```

Es el resultado de la suite en el entorno de preparación. El tiempo es duración de las pruebas, **no un benchmark de latencia del servicio**. No hubo pruebas omitidas ni advertencias en esa ejecución final.

También terminaron correctamente:

```text
python -m pip check              -> No broken requirements found.
python -m ruff check .           -> All checks passed!
python -m ruff format --check .  -> Todos los archivos revisados ya formateados.
python scripts/generate_proto.py -> Stubs idénticos a los incluidos, verificados por SHA-256.
```

La suite usa Python 3.12 y las versiones fijadas de las dependencias. `requirements.lock` registra las versiones de la instalación usada.

## Qué cubren las pruebas

| Archivo | Comportamiento comprobado |
| --- | --- |
| `tests/test_repository.py` | Primer ID exacto, códigos Base62 conocidos, reversibilidad, IDs consecutivos, persistencia, no reutilización tras borrar, 60 escrituras concurrentes y parámetros SQL |
| `tests/test_http.py` | POST y GET en ambas versiones; errores de entrada; 302 sin caché; eventos reales gRPC; 301; separación de entradas; TTL; errores no cacheados; cuotas en POST y cache hits; IP falsificada; ráfaga concurrente; logger caído |
| `tests/test_grpc.py` | Canal TLS, Ping, persistencia del evento, deduplicación por event_id y rechazo de eventos incompletos |
| `tests/test_https.py` | Tres procesos reales, puertos TCP, Uvicorn, HTTPS con validación del certificado, gRPC/TLS, estados 301/302/429, caché, escritura en Log DB y persistencia tras reiniciar v2 |

Las pruebas unitarias y de integración usan directorios temporales. La prueba de HTTPS ejecuta realmente los tres servicios; no sustituye gRPC ni las bases por dobles de prueba.

