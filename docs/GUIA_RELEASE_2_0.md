# Guía de operación de la distribución actualizada

Referencia: IngeniaLab(2).zip. Este documento aclara la operación de esta
base; los manuales Word originales se conservan como antecedentes.

1. Abra el servidor con el lanzador y cree su cuenta.
2. Entre en Entrevistas, elija Biblioteca o Cafetería, lea el contexto y
   seleccione una de las tres preguntas por turno. Espere la respuesta.
   La bitácora permite revisar el diálogo. Terminar antes de completar o
   Reiniciar pide confirmación. Lea el resumen al finalizar.
3. En Clasificación seleccione una declaración subrayada, elija RF/RNF y
   confirme. Puede corregir sin duplicar la declaración. Lea la explicación.
4. En Modelado complete nombre, actor, precondiciones, al menos dos pasos
   y postcondiciones. Valide, genere y guarde. La vista previa no sustituye
   el guardado. Las descargas SVG/PNG son de la versión persistida. Esta
   versión conserva el asistente y las lecciones con ocho casos de referencia;
   siga sus precondiciones e instrucciones en pantalla.
5. En Inspección seleccione un ejercicio, un fragmento y un tipo de defecto.
   Registre el hallazgo y lea la explicación. Las pistas penalizan puntos.
   Concluir cierra la práctica y muestra la clave.
6. Mi progreso permite retomar trabajo. Reportes genera un PDF con datos
   guardados; concluya la inspección para que aparezca en el reporte.

## IA y banco de respuestas de esta base

La versión incluye AnswerVariant, generate_answer_variants y opciones de
respuesta libre del cliente simulado; no equivalen a una caja de preguntas
libres para el estudiante. Los lanzadores de este paquete fuerzan catálogo
y desactivan respuestas en vivo y uso del banco para iniciar sin proveedor.
La base limpia no copia variantes generadas, cuentas o prácticas de la base
original. Para generar y usar variantes siga ingenialab/README.md y ejecute
manualmente el servidor con las variables allí indicadas. No introduzca
claves en los archivos distribuidos. El modo catálogo no necesita Ollama
ni API key; el proveedor en vivo no fue conectado al preparar este release.

## Teclado y problemas de ejecución

Use Tab y Shift+Tab para enfocar. Enter activa botones. Las declaraciones y
fragmentos aceptan Enter/Espacio; las filas de clasificación, Enter. En las
listas del editor, Enter agrega otra fila. Ctrl+S pertenece al navegador:
use Guardar especificación. Escape cancela confirmModal; lea el diálogo
antes de Enter porque su acción afirmativa puede tener el foco.

Ante una interrupción conserve la pestaña y use el reintento ofrecido.
Entre con la misma cuenta si la sesión vence. No se garantiza una cola
IndexedDB que conserve pendientes después de cerrar o recargar. Antes de
recargar conserve manualmente el texto pendiente. Ajuste zoom y realice
pausas; puntajes e insignias son formativos.

Para fallos de diagramación compruebe Java, dot y el JAR con
manage.py plantuml_check --strict. Un respaldo demostrativo no acredita
motor real y el timeout configurado no prueba cumplimiento global de RNF-03.
Si el puerto 8000 está ocupado, use manualmente otro puerto y abra su URL.

## Pruebas E2E de la versión actualizada

Se conserva scripts/e2e_staging.py, que crea una base de staging y recorre
los módulos mediante HTTP, cookies y CSRF. Sus resultados de esta entrega
figuran en NOTAS_RELEASE.txt y evidencia/ACT221A/. No confunda la prueba
HTTP con una evaluación visual de navegador ni con aprobación de usuarios.
