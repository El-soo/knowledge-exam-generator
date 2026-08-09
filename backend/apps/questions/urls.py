from rest_framework.routers import DefaultRouter
from .views import GenerationTaskViewSet, QuestionViewSet
router = DefaultRouter(); router.register("generation/tasks", GenerationTaskViewSet); router.register("questions", QuestionViewSet, basename="question")
urlpatterns = router.urls
