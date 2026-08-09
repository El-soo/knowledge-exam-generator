from rest_framework import serializers
from .models import Paper, PaperSection, PaperQuestion, ExportRecord

class PaperQuestionSerializer(serializers.ModelSerializer):
    question_status = serializers.CharField(source="question.review_status", read_only=True, allow_null=True)
    class Meta: model = PaperQuestion; fields = "__all__"
class PaperSectionSerializer(serializers.ModelSerializer):
    paper_questions = PaperQuestionSerializer(many=True, read_only=True)
    class Meta: model = PaperSection; fields = "__all__"
class ExportRecordSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    class Meta: model = ExportRecord; fields = "__all__"
    def get_download_url(self, obj): return f"/api/v1/exports/{obj.id}/download/" if obj.status == "SUCCESS" else None
class PaperSerializer(serializers.ModelSerializer):
    sections = PaperSectionSerializer(many=True, read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)
    question_count = serializers.IntegerField(source="paper_questions.count", read_only=True)
    class Meta: model = Paper; exclude = ["is_deleted"]; read_only_fields = ["total_score", "quality_score", "is_demo", "created_at", "updated_at"]
