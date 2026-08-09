from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.dashboard.urls")),
    path("api/v1/", include("apps.courses.urls")),
    path("api/v1/", include("apps.knowledge.urls")),
    path("api/v1/", include("apps.questions.urls")),
    path("api/v1/", include("apps.papers.urls")),
    path("api/v1/", include("apps.system_settings.urls")),
    path("api/v1/", include("apps.agents.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
