PlantUML de ACT-207B

Instala Java 17+ y Graphviz, y verifica java -version y dot -V.
Desde la carpeta con manage.py ejecuta:
  python manage.py install_plantuml
  python manage.py plantuml_check --strict

El instalador descarga PlantUML 1.2026.2 del repositorio oficial y verifica
el SHA-256 fijado. Tambien puedes colocar manualmente plantuml.jar aqui
o indicar otra ruta con PLANTUML_JAR. El JAR no viene dentro de este ZIP.
Descarga oficial: https://plantuml.com/download
El archivo conserva la licencia de su distribucion oficial.
