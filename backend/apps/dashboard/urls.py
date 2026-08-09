from django.urls import path
from .views import statistics, recent_files, recent_questions, recent_papers, question_type_chart, difficulty_chart, parse_status_chart, health, global_search
urlpatterns = [
 path("dashboard/statistics/", statistics), path("dashboard/recent-files/", recent_files), path("dashboard/recent-questions/", recent_questions), path("dashboard/recent-papers/", recent_papers), path("dashboard/question-type-chart/", question_type_chart), path("dashboard/difficulty-chart/", difficulty_chart), path("dashboard/parse-status-chart/", parse_status_chart), path("health/", health), path("search/", global_search),
]
