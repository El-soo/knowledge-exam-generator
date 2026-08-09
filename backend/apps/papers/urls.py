from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import PaperViewSet, download_export
router = DefaultRouter(); router.register("papers", PaperViewSet, basename="paper")
urlpatterns = router.urls + [path("exports/<int:pk>/download/", download_export)]
