from rest_framework.routers import DefaultRouter
from .views import AgentDefinitionViewSet, AgentWorkflowViewSet

router = DefaultRouter()
router.register("agents", AgentDefinitionViewSet, basename="agent")
router.register("agent-workflows", AgentWorkflowViewSet, basename="agent-workflow")
urlpatterns = router.urls
