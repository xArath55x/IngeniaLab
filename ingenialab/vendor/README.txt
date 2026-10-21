<<<<<<< Updated upstream
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
=======
PlantUML — perfil ACT-214B

Este adjunto ya incluye plantuml.jar 1.2026.2 sin modificaciones.
SHA-256: 3cdce52133c424dea22425b947ae9d47f2167b0866dfcf99e714d4ea1689975c
Fuente: https://github.com/plantuml/plantuml/releases/tag/v1.2026.2
Codigo fuente: https://github.com/plantuml/plantuml/tree/v1.2026.2
Licencia: GPL v3 o posterior; avisos en PLANTUML_LICENSE.txt y dentro del JAR.

Instala Java 17+ y Graphviz, revisa java -version y dot -V.
Desde ingenialab/:
  python manage.py install_plantuml
  python scripts/verify_environment.py

El instalador valida el SHA-256; no sobrescribe un JAR distinto. En un clon
Git el binario puede faltar porque vendor/*.jar se ignora: se descargara
con el instalador. En este ZIP se conserva el JAR original del adjunto.
No se incluyen Java ni Graphviz; instalalos mediante sus distribuciones.
>>>>>>> Stashed changes
