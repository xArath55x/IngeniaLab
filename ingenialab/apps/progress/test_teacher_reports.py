from uuid import uuid4

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import AccountRole

from .models import ReportExport, ReportSubmission
from .tests import ALL_MODULES, BaseCase


class TeacherSignupTests(TestCase):
    def test_professor_signup_and_login_open_the_inbox(self):
        signup = reverse("accounts:signup")
        credentials = {"username": "docente", "password": "Zacatecas#2026"}
        fields = {"username": credentials["username"], "first_name": "Docente", "email": "d@uaz.edu.mx",
                  "password1": credentials["password"], "password2": credentials["password"]}
        self.assertContains(self.client.get(signup), "Tipo de cuenta")
        self.client.post(signup, {**fields, "role": "admin"})
        self.assertFalse(User.objects.filter(username="docente").exists())

        inbox = reverse("progress:teacher_inbox")
        self.assertRedirects(self.client.post(signup, {**fields, "role": "teacher"}), inbox)
        self.client.logout()
        self.assertRedirects(self.client.post(reverse("accounts:login"), credentials), inbox)


@ALL_MODULES
class TeacherReportTests(BaseCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.teacher = User.objects.create_user("docente", first_name="Docente")
        cls.other_teacher = User.objects.create_user("otro_docente")
        for user in (cls.teacher, cls.other_teacher):
            AccountRole.objects.create(user=user, role=AccountRole.Role.TEACHER)

    def add_report_data(self):
        attempt = self.finished_attempt()
        req = attempt.version.requirements.get(key="B01")
        self.post(f"/clasificacion/api/intento/{attempt.id}/clasificar/", {
            "requirement_id": str(req.id), "category": "RF",
        })
        return attempt

    def send_report(self):
        self.client.post(reverse("progress:report_submit"), {"teacher": self.teacher.username})
        return ReportSubmission.objects.get()

    def test_teacher_sees_only_the_inbox_and_cannot_use_student_routes(self):
        inbox = reverse("progress:teacher_inbox")
        self.assertEqual(self.client.get(inbox).status_code, 403)
        self.client.force_login(self.teacher)
        self.assertRedirects(self.client.get("/"), inbox)
        with override_settings(INGENIALAB_MODULES=["interviews"]):
            self.assertRedirects(self.client.get("/"), inbox)
        self.assertNotContains(self.client.get(inbox), "Mi partida")
        classification = reverse("classification:classify", args=[uuid4()])
        for url in ("/elicitacion/", classification, "/modelado/", "/inspeccion/", "/reportes/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse("progress:partida_start")).status_code, 403)
        result = self.post(reverse("progress:checkpoint_save"))
        self.assertEqual(result.status_code, 403)
        self.assertFalse(result.json()["ok"])

    def test_report_and_feedback_round_trip(self):
        self.add_report_data()
        submission = self.send_report()
        detail = reverse("progress:submission_detail", args=[submission.pk])
        download = reverse("progress:submission_download", args=[submission.pk])
        feedback = reverse("progress:submission_feedback", args=[submission.pk])
        pdf = self.client.get(download).content
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertContains(self.client.get(reverse("progress:reports")), detail)

        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse("progress:teacher_inbox")), "Ana Alumna")
        self.assertContains(self.client.get(detail), "Enviar retroalimentación")
        self.assertEqual(self.client.get(download).content, pdf)
        self.assertContains(self.client.post(feedback, {"comment": "   "}), "Este campo es obligatorio")
        self.assertRedirects(self.client.post(feedback, {"comment": "Revisa los requisitos no funcionales."}), detail)

        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("progress:reports")), "1 comentario")
        self.assertContains(self.client.get(detail), "Revisa los requisitos no funcionales.")

    def test_reports_can_only_be_seen_by_the_sender_and_recipient(self):
        self.add_report_data()
        submission = self.send_report()
        detail = reverse("progress:submission_detail", args=[submission.pk])
        download = reverse("progress:submission_download", args=[submission.pk])
        feedback = reverse("progress:submission_feedback", args=[submission.pk])
        self.assertEqual(self.client.post(feedback, {"comment": "Alumno"}).status_code, 403)

        for user in (self.other, self.other_teacher):
            self.client.force_login(user)
            self.assertEqual(self.client.get(detail).status_code, 404)
            self.assertEqual(self.client.get(download).status_code, 404)
        self.assertNotContains(self.client.get(reverse("progress:teacher_inbox")), detail)
        self.assertEqual(self.client.post(feedback, {"comment": "Otro profesor"}).status_code, 404)
        self.assertFalse(submission.feedback.exists())

    def test_submission_requires_report_data_and_an_active_teacher(self):
        url = reverse("progress:report_submit")
        self.assertRedirects(self.client.post(url, {"teacher": self.teacher.username}), reverse("progress:reports"))
        self.add_report_data()
        self.teacher.is_active = False
        self.teacher.save(update_fields=["is_active"])
        for username in (self.user.username, self.teacher.username):
            with self.subTest(username=username):
                self.assertContains(self.client.post(url, {"teacher": username}), "Selecciona un profesor activo de la lista.")
        self.assertFalse(ReportExport.objects.exists())

    def test_submission_lists_only_active_teachers(self):
        self.add_report_data()
        self.other_teacher.is_active = False
        self.other_teacher.save(update_fields=["is_active"])
        page = self.client.get(reverse("progress:reports"))
        self.assertContains(page, '<select name="teacher" required id="id_teacher">')
        self.assertContains(page, '<option value="docente">Docente (@docente)</option>', html=True)
        self.assertNotContains(page, 'value="otro_docente"')
        self.assertNotContains(page, 'value="alumno"')

        self.teacher.is_active = False
        self.teacher.save(update_fields=["is_active"])
        page = self.client.get(reverse("progress:reports"))
        self.assertContains(page, "Aún no hay profesores registrados disponibles para recibir reportes.")
        self.assertNotContains(page, "<select")
