"""Preservación de bitácoras existentes al incorporar snapshots de ACT-211A1."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DialogueSnapshotMigrationTests(TransactionTestCase):
    def test_migracion_preserva_bitacora_anterior(self):
        executor=MigrationExecutor(connection)
        previous=[('interviews','0002_question_rounds')]
        current=[('interviews','0003_dialogue_snapshot')]
        try:
            executor.migrate(previous)
            old=executor.loader.project_state(previous).apps
            user=old.get_model('auth','User').objects.create(username='alumno-migracion')
            version=old.get_model('interviews','ScenarioVersion').objects.create(scenario_code='MIG',version_number='1',title='Migracion')
            segments=[{'text':'Necesito registrar solicitudes.','req':'M01'}]
            question=old.get_model('interviews','InterviewQuestion').objects.create(version=version,round_number=1,text='Pregunta original',answer_segments=segments)
            attempt=old.get_model('interviews','StudentAttempt').objects.create(user=user,version=version)
            entry=old.get_model('interviews','InterviewLogEntry').objects.create(attempt=attempt,question=question)
            entry_id=entry.pk
            executor=MigrationExecutor(connection);executor.migrate(current)
            new=executor.loader.project_state(current).apps
            saved=new.get_model('interviews','InterviewLogEntry').objects.get(pk=entry_id)
            self.assertEqual(saved.response_segments,segments)
            self.assertEqual(saved.response_source,'catalog')
            self.assertEqual(saved.attempt_id,attempt.pk)
            self.assertEqual(saved.question_id,question.pk)
        finally:
            executor=MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
