from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import KnowledgeFileViewSet, ParseTaskViewSet, ChapterViewSet, KnowledgePointViewSet, knowledge_search
router = DefaultRouter(); router.register("knowledge/files", KnowledgeFileViewSet, basename="knowledge-file"); router.register("knowledge/parse-tasks", ParseTaskViewSet); router.register("chapters", ChapterViewSet, basename="chapter"); router.register("knowledge-points", KnowledgePointViewSet, basename="knowledge-point")
urlpatterns = router.urls + [path("knowledge/search/", knowledge_search)]
