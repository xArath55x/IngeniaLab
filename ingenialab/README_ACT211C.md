# ACT-211C — Correcciones de integración

Base: `IngeniaLab.zip` subido el 23/10/2026. Revisión: `ACT-211C-v1.0`.
Se mantienen el adaptador IA, sus snapshots, las reglas pedagógicas y el
módulo de inspección de esa base. No se añaden dependencias ni migraciones.

## Ejecutar

Desde `IngeniaLab/ingenialab`, con Python 3.12 (perfil probado), Java 17+
y Graphviz preparados:

```sh
python3.12 scripts/setup_local.py
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_ingenialab
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

En Windows: `py -3.12 scripts/setup_local.py` y sustituye el ejecutable por
`.venv\Scripts\python.exe`. Las instrucciones de ACT-214B/211A1 siguen
aplicando. Si ya tenías una base propia, respáldala antes de migrate/seed.
ACT-211C no modifica el esquema; migrate conserva compatibilidad con las
migraciones anteriores que pudieran faltar. Abre de nuevo la página para
cargar el cliente actualizado. El servidor local conserva los datos del ZIP.

## Errores corregidos y comportamiento

- Las APIs de escritura aceptan objetos JSON. Listas, escalares, JSON roto y
  UTF-8 inválido reciben 400 JSON; el tamaño superior a 160000 bytes, 413.
  La sesión expirada sigue respondiendo 401 antes de procesar el cuerpo.
- Un formato de diagrama como [] o {} recibe 400 en vez de TypeError/500.
- Repetir una pregunta ya registrada recupera la misma respuesta sin volver
  a consultar IA ni sumar puntos. Tras finalizar, el comportamiento legado
  sigue bloqueando nuevas preguntas con 400; un reintento explícito marcado
  con X-Request-ID puede recuperar una respuesta existente, sin reabrirla.
- El cliente genera una clave UUID por operación. Los reintentos explícitos
  mantienen clave, cuerpo e identidad originales. En el alta de un caso de
  uso, X-Request-ID se usa como id del registro: un reintento idéntico devuelve
  el caso guardado; la misma clave con datos distintos o de otra cuenta da
  409. No se necesita una tabla nueva. Los clientes sin esa cabecera mantienen
  el contrato previo y no obtienen esta protección de alta idempotente.
- El cliente limita a 10 s la espera completa de fetch y lectura JSON. Ante
  timeout aborta el transporte y muestra Reintentar; no reenvía por sí solo
  una operación cuyo resultado puede haberse guardado. La promesa permanece
  pendiente hasta la acción del usuario, conservando su formulario.
- Un error HTML/JSON no contractual devuelve invalid_response; no se confunde
  con ausencia de conexión. Un código HTTP de error nunca se toma como éxito
  aunque el cuerpo diga ok:true.
- Ante sesión expirada o token CSRF cambiado aparece un único diálogo para
  las operaciones pendientes. Tras iniciar sesión en otra pestaña y pulsar
  Reintentar, GET /cuentas/api/sesion/ actualiza token e identidad sin caché.
  La clave de operación y los datos se conservan. No se desactiva CSRF.
- Si la cuenta activa cambió, el borrador no se envía a la cuenta nueva y
  aparece session_changed/409. El servidor también comprueba la identidad
  opcional X-IngeniaLab-User. Las autorizaciones normales se conservan.

El límite del navegador no garantiza que el servidor cancelara una escritura:
el aborto del transporte no revierte una transacción ya confirmada. La
protección de reintentos cubre preguntas registradas y altas de modelado;
no pretende establecer idempotencia universal para todos los endpoints.

## Timeout de PlantUML

La vista previa PNG ahora certifica SVG primero y aprovecha esa caché antes
de renderizar PNG. Cada render mantiene su presupuesto configurado de 1.8 s;
no se retira la certificación ni se aceptan imágenes de error como válidas.
Se redujo el arranque HotSpot con TieredStopAtLevel=1 y UseSerialGC.
Si tu JVM no admite estas opciones, usa PLANTUML_FAST_START=0.

En el servicio, `duration_ms` pasa a medir la fase del formato elegido:
antes un PNG frío incluía dentro de ese campo la certificación SVG previa.
Ahora `total_duration_ms` y `certification_ms` conservan explícitamente el
tiempo total y la certificación. Las descargas exponen también el total en
`X-Diagram-Total-Duration-Ms`. Este cambio de semántica debe considerarse si
consumes la métrica anterior como una medida de latencia global.

La API informa `duration_ms` del render elegido, `svg_certification_ms` de
la fase SVG y `total_duration_ms` del conjunto. Una solicitud PNG fría puede
sumar dos fases y superar 2 s; esta corrección funcional no certifica la meta
de latencia global bajo cualquier carga. No se cambiaron los umbrales de las
pruebas heredadas ni el timeout configurado del motor. Si una fase agota su
presupuesto, devuelve 504 y el guardado no deja datos parciales.

## Repetir verificaciones

```sh
INGENIALAB_TEST_PLANTUML=1 .venv/bin/python manage.py test apps integrations --verbosity 2
node tests/api-resilience.cjs
```

PowerShell:

```powershell
$env:INGENIALAB_TEST_PLANTUML="1"
.venv\Scripts\python.exe manage.py test apps integrations --verbosity 2
node tests/api-resilience.cjs
```

Node es necesario para las diez pruebas del cliente, no para ejecutar Django.
No se requieren paquetes npm. El DOM y fetch se simulan para probar timeout,
reautenticación, CSRF, cuenta distinta y reintentos de forma determinista;
estas pruebas no se presentan como una revisión visual en navegadores reales.
La suite Django incluye los casos de inspección señalados anteriormente.
La IA se prueba con mocks; PlantUML se ejecuta realmente con la variable indicada.

La evidencia local y la matriz de incidencias están en
`05_Testing_And_Reports/ACT-211C`. Los logs antes/intermedios documentan las
reproducciones y no son el resultado final. El workflow existente se amplía
para ejecutar apps, integrations y los tests JS, preparando Java/Graphviz y
Node. No se ejecutó ni publicó un workflow remoto desde esta entrega.
