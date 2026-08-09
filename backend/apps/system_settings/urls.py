from django.urls import path
from .views import settings_view, ollama_models, ollama_test, model_test, prompt_list, prompt_update, prompt_reset, create_backup
urlpatterns = [
    path("settings/", settings_view), path("settings/ollama/models/", ollama_models), path("settings/ollama/test/", ollama_test), path("settings/model/test/", model_test),
    path("settings/prompts/", prompt_list), path("settings/prompts/<str:key>/", prompt_update), path("settings/prompts/<str:key>/reset/", prompt_reset), path("settings/backup/", create_backup),
]
