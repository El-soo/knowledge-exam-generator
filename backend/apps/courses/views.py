from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from common.response import api_response
from .models import Course
from .serializers import CourseSerializer

class CourseViewSet(viewsets.ModelViewSet):
    serializer_class = CourseSerializer
    def get_queryset(self):
        qs = Course.objects.filter(is_deleted=False)
        keyword = self.request.query_params.get("keyword")
        status = self.request.query_params.get("status")
        if keyword: qs = qs.filter(name__icontains=keyword)
        if status: qs = qs.filter(status=status)
        return qs
    @transaction.atomic
    def perform_destroy(self, instance):
        instance.is_deleted = True; instance.status = "ARCHIVED"; instance.save()
        instance.knowledge_files.update(is_enabled=False)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        course = self.get_object(); course.status = "ARCHIVED"; course.save()
        return api_response(CourseSerializer(course, context={"request": request}).data, "课程已归档", request=request)
    @action(detail=True, methods=["get"])
    def statistics(self, request, pk=None):
        return api_response(CourseSerializer(self.get_object(), context={"request": request}).data["statistics"], request=request)
