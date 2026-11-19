from django.contrib import admin
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    # ACT-313B (OBS-01): los navegadores que no usan el favicon SVG (p. ej. Safari) piden /favicon.ico.
    path("favicon.ico", RedirectView.as_view(url=static("img/favicon.ico"), permanent=True)),
    path("cuentas/", include("apps.accounts.urls")),
    path("elicitacion/", include("apps.interviews.urls")),
    path("clasificacion/", include("apps.classification.urls")),
    path("modelado/", include("apps.modeling.urls")),
    path("inspeccion/", include("apps.inspection.urls")),
    path("", include("apps.progress.urls")),
]
