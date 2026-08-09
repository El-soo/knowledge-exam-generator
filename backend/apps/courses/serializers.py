from rest_framework import serializers
from .models import Course

class CourseSerializer(serializers.ModelSerializer):
    statistics = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()
    class Meta:
        model = Course
        fields = ["id", "name", "code", "description", "grade", "major", "cover", "cover_url", "remark", "status", "is_demo", "created_at", "updated_at", "statistics"]
        read_only_fields = ["is_demo", "created_at", "updated_at"]
        extra_kwargs = {"name": {"required": True, "allow_blank": False}}
    def get_cover_url(self, obj):
        if not obj.cover: return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.cover.url) if request else obj.cover.url
    def get_statistics(self, obj):
        return {"files": obj.knowledge_files.filter(is_deleted=False).count(), "chapters": obj.chapters.count(), "knowledge_points": obj.knowledge_points.count(), "questions": obj.questions.filter(is_deleted=False).count(), "papers": obj.papers.filter(is_deleted=False).count()}
