# Discusión de trade-offs y bonus - Tarea 2 INF326

**Integrantes:** Catalina Yañez (202273010-2), Eduardo Pacheco (202273014-5) y Fernanda Ojeda (202273025-0).

## 1. Contexto de decisión: USM como mandante

La función común es crear una URL corta y redirigir al destino original. Sin embargo, la USM podría usar el servicio para campañas de admisión que requieren conocer el interés recibido, o para enlaces institucionales estables usados muchas veces. Estas necesidades priorizan atributos de calidad diferentes. No se dispone de tráfico real, presupuesto ni objetivos de latencia de la USM; por eso las recomendaciones son condicionales y no se presentan cifras de rendimiento inventadas.

Las dos implementaciones comparten persistencia SQLite, IDs desde 597652313, Base62, validación de URLs y HTTPS. Se comparan como alternativas: no se pretende que ambos servicios compartan un único espacio de códigos en este despliegue.

## 2. Arquitectura 1: 302 y registro por gRPC

Cada GET válido consulta la equivalencia y envía un evento al componente Log. El evento contiene timestamp UTC, URL corta visitada, URL original, código y un identificador de evento. Log escribe en su base independiente antes de responder. Finalmente, el cliente recibe 302 y `Location`.

Se añade `Cache-Control: no-store, max-age=0`. Aunque el enunciado asocia 302 con evitar caché, el código de estado por sí solo no prohíbe todo almacenamiento: las directivas HTTP expresan esa intención de forma explícita [1, 2]. La implementación tampoco habilita caché de respuestas en el servidor v1.

### Beneficios

**Observabilidad.** Las solicitudes que llegan al servicio pueden registrarse. Para una campaña de postgrado, esto permite analizar interés por enlace y por franja temporal. Se registran accesos, no personas únicas ni matrículas concretadas: recargas, bots y herramientas que previsualizan enlaces también pueden generar GET.

**Separación de responsabilidades.** El acortador mantiene equivalencias; Log mantiene eventos. La base de visitas puede crecer, respaldarse o evolucionar sin cambiar el esquema del acortador. El contrato `.proto` hace explícitos los campos y la operación. gRPC permite usar cliente y servidor con interfaces generadas [5].

**Mayor control sobre futuras políticas.** Al volver a consultar al acortador, el servidor podría incorporar revocación o cambios de destino sin depender de redirecciones almacenadas. Es una capacidad de evolución; esta entrega conserva enlaces inmutables y no implementa edición.

### Costos y riesgos

**Latencia adicional.** El camino incluye la consulta de la equivalencia, la comunicación gRPC y la persistencia del evento. Se usa un canal reutilizado y un deadline de 0,5 s, pero no se afirma que gRPC por sí mismo vuelva más rápido al sistema. La ventaja de tipado y separación tiene un costo operativo.

**Más componentes y puntos de fallo.** Hay dos procesos de aplicación y dos bases en esta alternativa. Se deben observar la salud del logger, el almacenamiento de eventos y los errores de comunicación.

**Disponibilidad frente a integridad de la analítica.** Se escogió mantener el 302 aunque falle Log. Esto permite que un postulante siga llegando al destino durante una caída del componente analítico. La contrapartida es que pueden perderse eventos. Si vence el deadline después de que Log haya escrito, el resultado de esa llamada queda incierto para el cliente: un fallo de ACK no prueba que el evento no se guardó.

No hay cola durable ni reenvío automático de aplicación. `event_id` evita insertar dos veces el mismo evento si este se reenviara, pero no hace durable un evento que nunca llegó. Por tanto, **no se ofrece entrega exactamente una vez ni un registro completo durante fallos**. Si la USM exigiera trazabilidad auditable, propondríamos una outbox transaccional persistente y un trabajador que reintente por gRPC, conservando la deduplicación. Esto agregaría almacenamiento y complejidad y no forma parte de las figuras exigidas.

**Gestión de los registros.** URLs y timestamps pueden revelar intereses o incluir parámetros sensibles. El prototipo no almacena IP, cookies ni identidad en Log DB, pero eso no vuelve automáticamente inocuo al registro de URLs. Para un despliegue institucional se definirían acceso, retención y eliminación de eventos; los contadores `/stats` solo son de diagnóstico.

### Valoración para la USM

La arquitectura 1 es adecuada cuando el seguimiento de campañas tiene valor y la USM acepta el costo de mantener el registro. La política de continuar redirigiendo resulta razonable si llegar a información académica es más importante que contar cada intento. No bastaría si se quisiera usar ese registro como evidencia obligatoria de acceso.

## 3. Arquitectura 2: 301, control de arribo y múltiples copias

### Controlar el arribo de eventos

Se usa `RateLimitConfig` de Litestar: 60 solicitudes por minuto por IP, con una ventana administrada por el middleware y respuesta 429 al agotar la cuota. POST y GET consumen la misma cuota. El limitador actúa también cuando la respuesta se encuentra en caché. La prueba concurrente comprueba que una ráfaga no supera la cuota configurada en esta instancia.

**Beneficio:** restringe la cantidad de trabajo aceptado por cliente y ayuda a proteger la capacidad del servicio. **Trade-off:** una IP puede representar a muchos estudiantes detrás del NAT de un campus; un umbral bajo podría bloquear tráfico legítimo. Además, un atacante con muchas IP puede repartir solicitudes. No es una defensa completa contra DDoS.

El valor 60 es demostrativo y configurable, no una recomendación dimensionada con datos USM. Se excluyen `/health`, `/stats` y `/schema` de la cuota. En una publicación real habría que restringir esas rutas de diagnóstico y valorar cuotas diferentes para crear enlaces y resolverlos. No se confía directamente en `X-Forwarded-For`: el framework identifica la dirección del cliente y un proxy requeriría una configuración de confianza explícita [4].

### Mantener múltiples copias de datos

La copia persistente vive en Shortener DB; las respuestas GET 301 se conservan además en `MemoryStore`, mediante `@get(cache=True)` y `ResponseCacheConfig`. El TTL del servidor es 60 s. Ante un acierto, Litestar devuelve la respuesta sin ejecutar la consulta de resolución. Las pruebas verifican que dos GET sucesivos producen una sola lectura SQL.

Esta es la táctica de múltiples copias **en el servicio**: no se considera suficiente devolver 301 y depender solo del navegador. La caché HTTP del cliente es una capa adicional e independiente [3].

**Beneficio:** los enlaces frecuentes reducen trabajo de resolución y presión sobre la base. **Trade-off:** se consume memoria, pueden existir datos desactualizados y un reinicio deja la caché fría. No se han medido percentiles ni throughput; la evidencia demuestra consultas evitadas, no una aceleración porcentual determinada.

El TTL limita el tiempo de reutilización de cada entrada. Se eliminan periódicamente las expiradas; el prototipo no aplica un máximo estricto de memoria ni una política LRU. No se cachean errores o POST. Tampoco hay un mecanismo de coalescencia de misses: varias solicitudes simultáneas sobre un enlace frío pueden consultar la base antes de que se llene la caché.

La API no permite editar o borrar equivalencias. Esta inmutabilidad simplifica la coherencia. Si se añadieran esas operaciones, habría que invalidar la caché del servidor. La caché del navegador seguiría siendo un problema separado; borrar la memoria de Litestar no elimina la redirección guardada por un cliente.

### Redirección permanente y caché del navegador

El 301 comunica un cambio permanente y puede almacenarse. Se explicita `Cache-Control: public, max-age=300` [1, 2]. Un navegador puede reutilizar la redirección mientras la considere fresca y así evitar una nueva petición al acortador. El beneficio depende del comportamiento de cada cliente; no todos mantendrán o usarán caché de la misma forma.

Esto reduce el tráfico que llega al servicio, pero también reduce observabilidad: **una visita resuelta enteramente por el navegador no atraviesa el servidor, su contador ni su rate limiter**. La arquitectura 2 no incluye un servicio Log. Los hits de la caché de Litestar no representan el total de clics humanos.

Aunque el `max-age` limita la frescura, el significado de 301 sigue siendo permanente. No lo escogeríamos para enlaces cuyo destino debe cambiar frecuentemente o revocarse con efecto inmediato. La caché mejora disponibilidad solo para clientes que ya disponen de una respuesta reutilizable; no soluciona una caída para todos los usuarios.

### Valoración para la USM

La arquitectura 2 resulta apropiada para enlaces institucionales estables con mucha reutilización y sin necesidad de contabilizar cada acceso. Sus cuotas deben ajustarse al tráfico y a las redes compartidas de la universidad. Para una campaña cuyo éxito se mide con accesos al enlace corto, la pérdida de observabilidad sería una desventaja relevante.

## 4. Comparación de atributos de calidad

| Atributo | Arquitectura 1 | Arquitectura 2 | Consecuencia para la USM |
| --- | --- | --- | --- |
| Rendimiento | Consulta SQL y llamada gRPC por GET válido | Caché del servicio; el cliente puede evitar solicitudes | v2 reduce trabajo repetido; falta medir latencia bajo carga real |
| Observabilidad | Eventos con timestamp y destino; incompletos durante fallos | Sin Log; parte de los accesos no llega al servidor | v1 favorece campañas con seguimiento |
| Disponibilidad | El fallo analítico no bloquea la redirección, con posible espera hasta deadline | Menos dependencias; algunas lecturas sobreviven en caché | Ambas conservan dependencias de sus datos y procesos |
| Coherencia y cambios | Cada GET consulta la equivalencia | Copias con distintos tiempos de vida | v2 exige más cuidado si se incorporan cambios o revocaciones |
| Control de carga | No se exige ni implementa cuota en esta alternativa | Cuota por IP y respuestas 429 | v2 debe considerar NAT de campus y distribución del abuso |
| Operación | Acortador, Log y dos bases | Acortador, una base y memoria de caché/cuota | v1 requiere mantener más componentes |
| Escalabilidad | Log puede evolucionar aparte; SQLite limita escrituras | Caché reduce lecturas; estado en memoria es local | Ninguna es una solución distribuida lista para producción |
| Privacidad | Los eventos requieren políticas de manejo | Menos almacenamiento analítico en la aplicación | La necesidad institucional de conservar datos debe justificarse |

## 5. Decisiones comunes y límites del despliegue

**SQLite por componente.** Facilita una entrega reproducible, sin instalar un servidor de bases adicional. WAL y transacciones protegen las operaciones en un único nodo. Las escrituras se serializan: no se debe equiparar este diseño a una base distribuida. Una réplica en otra máquina con su propio SQLite comenzando desde el mismo número podría producir códigos iguales.

**Base62 y restricciones.** La codificación es reversible y no se trunca. La unicidad del código procede de la unicidad del ID, reforzada con `UNIQUE`. Los números consecutivos hacen predecibles los códigos; no deben usarse como secreto de autorización. Agregar aleatoriedad o un hash truncado no demostraría ausencia de colisiones.

**TLS.** Ambos endpoints HTTP se sirven exclusivamente por HTTPS; gRPC también usa TLS. Un certificado autofirmado permite cifrar y verificar la conexión cuando el cliente confía explícitamente en él. No proporciona la confianza automática de una autoridad pública. La demostración comparte un certificado; un despliegue institucional usaría certificados y secretos independientes, renovación y controles adecuados de acceso al logger.

**Un solo worker.** Cada aplicación mantiene sus stores y contadores en su proceso. Con varias réplicas, la cuota total podría multiplicarse y las cachés diferir. Se necesitarían stores compartidos y una operación de cuota atómica entre procesos, por ejemplo un script o transacción en Redis. **Solo cambiar `MemoryStore` por Redis no demuestra atomicidad distribuida**: el bloqueo del middleware utilizado protege una instancia, no toda la flota. Se deben revisar también la estrategia de invalidación y la base central.

## 6. Recomendación justificada

Para una campaña de admisión/postgrado donde la USM necesite analizar cuándo se visitan los enlaces, escogeríamos **arquitectura 1**, confirmando que tolera una pérdida ocasional de eventos. Si la analítica debe ser durable, se agregaría la outbox antes de comprometer esa garantía.

Para accesos frecuentes a información permanente, como una página institucional estable, escogeríamos **arquitectura 2**, configurando las cuotas con tráfico real. Si el destino pudiera cambiar o bloquearse con urgencia, reconsideraríamos la redirección permanente aun cuando la caché mejore eficiencia.

Para decidir con evidencia mediríamos: latencias p50/p95/p99 de GET, tasa de errores/429, porcentaje de aciertos de caché, consultas SQL por petición, memoria usada, crecimiento de Log DB y proporción de eventos confirmados/fallidos. Las pruebas entregadas verifican funcionamiento; no reemplazan ese estudio de carga ni permiten asignar cifras a la USM.

## 7. BONUS: unicidad en un ambiente distribuido

### Problema

Dos servidores independientes que parten en 597652313 pueden asignar el mismo ID a destinos diferentes. Aplicar Base62 a ambos no elimina la colisión. La solución debe coordinar o separar el **espacio de IDs**, además de preservar su estado ante reinicios y fallos.

### Opción recomendada inicialmente: secuencia central persistente

Para una primera versión distribuida de la USM proponemos varias instancias HTTP usando una base transaccional común, con una secuencia `BIGINT` y restricciones globales `PRIMARY KEY(id)` y `UNIQUE(hash)`.

1. Obtener el siguiente ID mediante una operación atómica de la base, comenzando en 597652313.
2. Codificar ese ID completo en Base62 e insertar la equivalencia.
3. Confirmar la transacción antes de devolver la URL al usuario.
4. No reiniciar ni retroceder la secuencia al reiniciar una aplicación.

Por ejemplo, `nextval` de PostgreSQL entrega valores distintos a sesiones concurrentes. Puede haber huecos por abortos, lo que no rompe unicidad [7]. Se evita calcular `MAX(id)+1` en cada servidor.

**Por qué es única:** la secuencia central asigna distintos enteros y la codificación Base62 es inyectiva. Las restricciones globales rechazan inconsistencias adicionales. La garantía depende de conservar un único escritor autorizado o un sistema de coordinación equivalente; no basta con replicar bases asincrónicamente y permitir escrituras simultáneas divergentes.

**Failover:** no promover una réplica con una secuencia o datos atrasados respecto de URLs ya entregadas; impedir dos líderes simultáneos y preservar los commits reconocidos. Ante pérdida de coordinación, se debe suspender la creación antes que arriesgar duplicados. Los GET existentes pueden continuar si cuentan con datos disponibles.

**Trade-off:** diseño simple y auditable, pero el asignador/base concentra coordinación. Para el contexto inicial, lo preferiríamos a introducir un generador más complejo sin datos que justifiquen esa complejidad.

### Alternativa de mayor autonomía: espacios separados

Con `N` nodos fijos y un identificador exclusivo `n` por nodo, una construcción posible es:

```text
id = 597652313 + n + N*k
0 <= n < N
k = contador persistente local que nunca se reutiliza
```

Dos IDs iguales exigirían el mismo `n` al comparar sus residuos módulo `N`, y luego el mismo `k`. Con asignaciones de nodo exclusivas y contadores sin reutilización, no hay colisiones. Hay que impedir que dos procesos usen el mismo `n`, restaurar de forma segura el contador y no cambiar `N` improvisadamente. También podrían reservarse bloques disjuntos mediante un asignador central, sin reasignar bloques usados por nodos caídos.

### Alternativa temporal: Snowflake

Un generador tipo Snowflake compone timestamp, identidad de nodo y contador por unidad de tiempo. Una configuración típica usa 41 bits de milisegundos, 10 de nodo y 12 de secuencia [8]. Para una implementación propia serían imprescindibles nodos exclusivos, sincronización del contador, espera al agotarlo y detener la generación cuando el reloj retroceda. También debe evitarse reutilizar el estado temporal tras reinicios o sustituir un nodo mientras su anterior instancia siga emitiendo.

La ventaja es reducir coordinación por cada ID; el costo es administrar relojes, asignación de nodos y recuperación. Convertir después a Base62 conserva la unicidad si esas condiciones se cumplen. Es una propuesta de evolución, **no un mecanismo implementado en esta tarea**.

Un UUID aleatorio ofrece una probabilidad muy pequeña de colisión, no una demostración de imposibilidad. Si se usara, habría que conservar una comprobación global y reintentar ante conflicto. Para el bonus se prefieren las estrategias anteriores, con sus condiciones de garantía explícitas.

