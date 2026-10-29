"""Carga idempotente de escenarios (data/interviews.json), inspecciones (data/inspections.json) y casos de
uso de referencia para las lecciones de CU-02 (data/usecases.json)."""
import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.inspection.models import InspectionExercise, InspectionFragment
from apps.interviews.models import InterviewQuestion, MasterRequirement, ScenarioVersion
from apps.modeling.forms import UseCaseForm
from apps.modeling.models import ReferenceUseCase


class Command(BaseCommand):
    help = "Carga o actualiza los escenarios y ejercicios de inspección de IngeniaLab."

    def add_arguments(self, parser):
        parser.add_argument("--interviews", default=str(settings.BASE_DIR / "data" / "interviews.json"))
        parser.add_argument("--inspections", default=str(settings.BASE_DIR / "data" / "inspections.json"))
        parser.add_argument("--usecases", default=str(settings.BASE_DIR / "data" / "usecases.json"))

    @transaction.atomic
    def handle(self, *args, **opts):
        with open(opts["interviews"], encoding="utf-8") as fh:
            scenarios = json.load(fh)["scenarios"]
        with open(opts["inspections"], encoding="utf-8") as fh:
            inspections = json.load(fh)["inspections"]
        with open(opts["usecases"], encoding="utf-8") as fh:
            use_cases = json.load(fh)["use_cases"]

        for sc in scenarios:
            version, created = ScenarioVersion.objects.update_or_create(
                scenario_code=sc["code"], version_number=sc["version"],
                defaults={"title": sc["title"], "summary": sc["summary"], "client_name": sc["client_name"],
                          "client_role": sc["client_role"], "client_greeting": sc["greeting"], "is_active": True},
            )
            if not created and version.attempts.exists():
                # Una versión con prácticas registradas es inmutable: publica una nueva versión en el JSON.
                self.stdout.write(self.style.WARNING(f"{version} ya tiene prácticas; se conserva sin cambios."))
                continue
            version.questions.all().delete()
            for round_number, rnd in enumerate(sc["rounds"], 1):
                qualities = sorted(o["quality"] for o in rnd["options"])
                if qualities != ["high", "low", "medium"]:
                    raise ValueError(f"{sc['code']} ronda {round_number}: se requiere una opción high, medium y low")
                for order, opt in enumerate(rnd["options"]):
                    question = InterviewQuestion.objects.create(
                        version=version, round_number=round_number, topic=rnd["topic"], text=opt["text"],
                        quality=opt["quality"], rationale=opt["rationale"], order=order,
                        answer_segments=[{"text": s["text"], "req": s["req"]["key"] if "req" in s else None}
                                         for s in opt["answer"]],
                    )
                    for s in opt["answer"]:
                        if "req" in s:
                            r = s["req"]
                            MasterRequirement.objects.create(
                                version=version, question=question, key=r["key"], statement_text=s["text"],
                                expected_type=r["type"], feedback_explanation=r["feedback"], hint=r.get("hint", ""),
                            )
            # Solo la versión recién cargada queda disponible para nuevas prácticas.
            ScenarioVersion.objects.filter(scenario_code=sc["code"]).exclude(id=version.id).update(is_active=False)
            self.stdout.write(self.style.SUCCESS(f"Escenario {version}: {version.requirements.count()} requisitos"))

        for ex in inspections:
            exercise, created = InspectionExercise.objects.update_or_create(
                code=ex["code"], defaults={"title": ex["title"], "description": ex["description"], "is_active": True},
            )
            if not created and exercise.attempts.exists():
                self.stdout.write(self.style.WARNING(f"{exercise.code} ya tiene prácticas; se conserva sin cambios."))
                continue
            exercise.fragments.all().delete()
            for order, fr in enumerate(ex["fragments"]):
                InspectionFragment.objects.create(
                    exercise=exercise, order=order, label=fr["label"], text=fr["text"],
                    defect_type=fr["defect"], explanation=fr["explanation"], hint=fr.get("hint", ""),
                )
            self.stdout.write(self.style.SUCCESS(f"Inspección {exercise.code}: {exercise.defect_count} defectos"))

        for order, uc in enumerate(use_cases):
            version = ScenarioVersion.objects.filter(scenario_code=uc["scenario"], version_number=uc["version"]).first()
            if version is None:
                raise ValueError(f"{uc['key']}: no existe el escenario {uc['scenario']} v{uc['version']}")
            _check_use_case(uc, version)
            # Las lecciones guardan copia de sus ejercicios, así que actualizar la referencia no las altera.
            ReferenceUseCase.objects.update_or_create(version=version, key=uc["key"], defaults={
                "order": order, "requirement_keys": uc["requirements"], "spec": uc["spec"], "exercises": uc["exercises"],
            })
            self.stdout.write(self.style.SUCCESS(f"Caso de uso {uc['key']} ({version.scenario_code}): {uc['spec']['name']}"))


def _check_use_case(uc, version):
    """Contenido coherente: requisitos RF existentes, especificación válida para el editor y ejercicios completos."""
    key, spec, exercises = uc["key"], uc["spec"], uc["exercises"]
    types = dict(version.requirements.filter(key__in=uc["requirements"]).values_list("key", "expected_type"))
    for req in uc["requirements"]:
        if types.get(req) != MasterRequirement.RF:
            raise ValueError(f"{key}: {req} debe ser un requisito funcional de {version.scenario_code}")
    form = UseCaseForm(data=spec)
    if not form.is_valid():
        raise ValueError(f"{key}: la especificación no pasa el editor: {form.error_messages()}")
    actors = spec["primary_actors"] + spec["secondary_actors"]
    needed = {"name", "actors", "preconditions", "main_flow", "postconditions"}
    needed |= {"primary_actor"} if len(actors) > 1 else set()
    needed |= {"alternate_flows"} if spec["alternate_flows"] else set()
    needed |= {"relations"} if spec["relations"] else set()
    if needed - set(exercises):
        raise ValueError(f"{key}: faltan ejercicios {sorted(needed - set(exercises))}")
    # Las opciones correctas de cada ejercicio deben coincidir con la especificación que se guarda.
    for name, part in (("preconditions", "preconditions"), ("postconditions", "postconditions")):
        if " ".join(exercises[name]["correct"]) != spec[part]:
            raise ValueError(f"{key}: las opciones correctas de {name} no coinciden con la especificación")
    if spec["alternate_flows"] and exercises["alternate_flows"]["correct"] != spec["alternate_flows"]:
        raise ValueError(f"{key}: las opciones correctas de alternate_flows no coinciden con la especificación")
    if spec["relations"] and exercises["relations"]["correct"] != [f"«{r['type']}» {r['target']}" for r in spec["relations"]]:
        raise ValueError(f"{key}: las opciones correctas de relations no coinciden con la especificación")
    correct = {"name": [spec["name"]], "actors": actors, "main_flow": spec["main_flow"],
               **{n: exercises.get(n, {}).get("correct", []) for n in
                  ("preconditions", "postconditions", "alternate_flows", "relations")}}
    for name, answers in correct.items():
        distractors = exercises.get(name, {}).get("distractors", [])
        if name in needed and (len(distractors) < 2 or set(distractors) & set(answers)):
            raise ValueError(f"{key}: {name} necesita al menos 2 opciones incorrectas distintas de las correctas")
