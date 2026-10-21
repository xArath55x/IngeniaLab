PlantUML — ACT-214B

Este paquete incluye plantuml.jar 1.2026.2, sin modificaciones.
SHA-256: 3cdce52133c424dea22425b947ae9d47f2167b0866dfcf99e714d4ea1689975c
Fuente oficial: https://github.com/plantuml/plantuml/releases/tag/v1.2026.2
Licencia: GPL; avisos y licencia de terceros incluidos en el JAR.
Código fuente de esa versión: https://github.com/plantuml/plantuml/tree/v1.2026.2
Conserva sus avisos de licencia al redistribuir.

Requiere Java 17+ y Graphviz en PATH.
python manage.py install_plantuml comprueba la copia existente sin descargarla
si el hash coincide. scripts/verify_environment.py comprueba también el hash.
Puedes indicar otra ruta con PLANTUML_JAR, pero el perfil reproducible exige
exactamente el artefacto fijado. No se incluye Java ni Graphviz.
