"""Opciones de corrección y ejemplos breves para la práctica guiada."""
import random


# Cada acción se muestra junto a otra que resolvería un problema diferente.
ACTIONS = {
    "ambiguity": ("Aclarar a quién o a qué se refiere la frase.", "incomplete"),
    "incomplete": ("Añadir la regla o el paso que falta.", "unverifiable"),
    "inconsistency": ("Corregir lo que contradice otra regla o una definición.", "redundancy"),
    "unverifiable": ("Añadir un criterio medible para comprobar que se cumple.", "ambiguity"),
    "redundancy": ("Dejar una sola versión de la información repetida.", "inconsistency"),
    "design": ("Describir el resultado que necesita el usuario sin imponer una solución técnica.", "unverifiable"),
}

CONTEXT = {
    ("INS-CONTROL-ESCOLAR-01", "RF-06"): "RF-05",
    ("INS-CONTROL-ESCOLAR-01", "RF-07"): "RF-04",
}

EXAMPLES = {
    "INS-CONTROL-ESCOLAR-01": {
        "RF-02": "Cuando un alumno repruebe una materia, el sistema enviará un correo institucional al alumno y a su tutor.",
        "RF-06": "Eliminar RF-06 y conservar RF-05 como único requisito para generar la boleta en PDF.",
        "RF-07": "Conservar una sola regla: el docente puede capturar calificaciones hasta cinco días hábiles después del cierre.",
        "RF-08": "El sistema conservará las calificaciones registradas para que el coordinador pueda consultarlas.",
        "RF-09": "El sistema calculará el promedio general con las calificaciones de todas las materias cursadas, incluidas las reprobadas.",
        "RNF-01": "En una prueba de usabilidad, al menos el 90 % de los alumnos podrá consultar su boleta en menos de un minuto sin ayuda.",
    },
    "INS-CASO-USO-SALAS-01": {
        "Actores": "Actor principal: Estudiante.",
        "Paso 2": "El sistema muestra en dos segundos o menos las salas disponibles para el horario elegido.",
        "Paso 3": "El estudiante elige una sala y el sistema registra la reserva.",
        "Flujo alterno": "Si no hay salas disponibles, el sistema avisa al estudiante y le pide elegir otro horario.",
        "Postcondición": "La reserva queda registrada.",
    },
}


CHOICE_TEXT = {
    "INS-CONTROL-ESCOLAR-01": {
        "RF-02": ("Aclarar quién reprueba y por qué medio se envía el aviso.",
                  "Añadir una regla para calcular la calificación final."),
        "RF-06": ("Dejar un solo requisito para la boleta en PDF.",
                  "Cambiar la fecha límite de captura de calificaciones."),
        "RF-07": ("Unificar las fechas límite en una sola regla.",
                  "Eliminar la frase que se repite literalmente."),
        "RF-08": ("Decir qué datos se deben conservar y para qué.",
                  "Indicar en cuánto tiempo debe abrir el sistema."),
        "RF-09": ("Definir cómo cuentan las materias reprobadas en el promedio.",
                  "Especificar en cuánto tiempo debe aparecer el resultado."),
        "RNF-01": ("Definir una tarea y medir si los alumnos pueden completarla.",
                   "Aclarar a qué alumnos se refiere la frase."),
    },
    "INS-CASO-USO-SALAS-01": {
        "Actores": ("Quitar al propio sistema de la lista de actores.",
                    "Fusionar al estudiante y al sistema en un solo actor."),
        "Paso 2": ("Indicar un tiempo máximo para mostrar las salas.",
                   "Aclarar quién consulta las salas."),
        "Paso 3": ("Decir que el sistema registra la reserva.",
                   "Indicar cuánto tarda la consulta de salas."),
        "Flujo alterno": ("Indicar qué hace el sistema cuando no hay salas.",
                          "Medir cuánto tarda en abrirse el calendario."),
        "Postcondición": ("Dejar una sola oración que confirme el registro de la reserva.",
                          "Cambiar una de las oraciones para decir que la reserva se canceló."),
    },
}


def options(fragment):
    expected = fragment.defect_type
    current_action, other = ACTIONS[expected]
    current_action, other_action = CHOICE_TEXT.get(fragment.exercise.code, {}).get(
        fragment.label, (current_action, ACTIONS[other][0]),
    )
    choices = [(expected, current_action), (other, other_action)]
    random.Random(fragment.id.int).shuffle(choices)
    return choices


def example(exercise, fragment):
    return EXAMPLES.get(exercise.code, {}).get(fragment.label)
