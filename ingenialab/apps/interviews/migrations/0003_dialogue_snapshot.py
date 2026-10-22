from copy import deepcopy
from django.db import migrations, models


def preserve_existing_log(apps, schema_editor):
    Entry = apps.get_model('interviews', 'InterviewLogEntry')
    alias = schema_editor.connection.alias
    for entry in Entry.objects.using(alias).select_related('question').iterator():
        entry.response_segments = deepcopy(entry.question.answer_segments)
        entry.save(using=alias, update_fields=['response_segments'])


class Migration(migrations.Migration):
    dependencies = [('interviews', '0002_question_rounds')]
    operations = [
        migrations.AddField(model_name='interviewlogentry', name='response_segments', field=models.JSONField(default=list, blank=True)),
        migrations.AddField(model_name='interviewlogentry', name='response_source', field=models.CharField(max_length=10, default='catalog')),
        migrations.AddField(model_name='interviewlogentry', name='fallback_reason', field=models.CharField(max_length=32, blank=True, default='')),
        migrations.RunPython(preserve_existing_log, migrations.RunPython.noop),
    ]
