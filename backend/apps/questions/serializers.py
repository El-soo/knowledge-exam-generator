from rest_framework import serializers
from .models import GenerationTask, Question, QuestionOption, QuestionReview
from .services import question_hash, validate_question_structure

class QuestionOptionSerializer(serializers.ModelSerializer):
    class Meta: model = QuestionOption; fields = ["id", "label", "content", "is_correct", "sort_order"]

class QuestionReviewSerializer(serializers.ModelSerializer):
    class Meta: model = QuestionReview; fields = "__all__"

class QuestionSerializer(serializers.ModelSerializer):
    options = QuestionOptionSerializer(many=True, required=False)
    reviews = QuestionReviewSerializer(many=True, read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)
    chapter_name = serializers.CharField(source="chapter.name", read_only=True, allow_null=True)
    knowledge_point_name = serializers.CharField(source="knowledge_point.name", read_only=True, allow_null=True)
    class Meta:
        model = Question
        exclude = ["is_deleted"]
        read_only_fields = ["content_hash", "source_type", "generation_model", "ai_review_score", "use_count", "created_at", "updated_at", "is_demo"]
    def validate(self, attrs):
        raw = {**attrs, "type": attrs.get("question_type", getattr(self.instance, "question_type", None)), "options": self.initial_data.get("options", []), "answer": attrs.get("answer", getattr(self.instance, "answer", [])), "stem": attrs.get("stem", getattr(self.instance, "stem", "")), "score": attrs.get("score", getattr(self.instance, "score", 0)), "difficulty": attrs.get("difficulty", getattr(self.instance, "difficulty", "中等")), "analysis": attrs.get("analysis", getattr(self.instance, "analysis", ""))}
        issues = validate_question_structure(raw)
        if issues: raise serializers.ValidationError({"question": issues})
        return attrs
    def create(self, validated_data):
        options = validated_data.pop("options", []); validated_data["content_hash"] = question_hash(validated_data["stem"]); validated_data["source_type"] = "MANUAL"
        question = Question.objects.create(**validated_data)
        self._save_options(question, options); return question
    def update(self, instance, validated_data):
        options = validated_data.pop("options", None)
        for key, value in validated_data.items(): setattr(instance, key, value)
        instance.content_hash = question_hash(instance.stem); instance.save()
        if options is not None: instance.options.all().delete(); self._save_options(instance, options)
        return instance
    @staticmethod
    def _save_options(question, options):
        answers = set(str(x).upper() for x in question.answer)
        QuestionOption.objects.bulk_create([QuestionOption(question=question, label=o["label"].upper(), content=o["content"], is_correct=o.get("is_correct", o["label"].upper() in answers), sort_order=i) for i, o in enumerate(options)])

class GenerationTaskSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source="course.name", read_only=True)
    questions = serializers.SerializerMethodField()
    retained_count = serializers.SerializerMethodField()
    workflow_id = serializers.SerializerMethodField()
    current_agent = serializers.SerializerMethodField()
    quality_mode = serializers.SerializerMethodField()
    agent_steps = serializers.SerializerMethodField()
    workflow_status = serializers.SerializerMethodField()
    def get_questions(self, obj):
        return QuestionSerializer(obj.questions.filter(is_deleted=False), many=True).data
    def get_retained_count(self, obj):
        return obj.questions.filter(is_deleted=False).count()
    @staticmethod
    def _workflow(obj):
        from apps.agents.models import AgentWorkflowRun
        return AgentWorkflowRun.objects.filter(business_type="generation_task", business_id=obj.id).order_by("-created_at").first()
    def get_workflow_id(self, obj):
        workflow = self._workflow(obj); return str(workflow.id) if workflow else None
    def get_current_agent(self, obj):
        workflow = self._workflow(obj); return workflow.current_agent if workflow else ""
    def get_quality_mode(self, obj):
        workflow = self._workflow(obj); return workflow.quality_mode if workflow else obj.config.get("quality_mode", "STANDARD")
    def get_agent_steps(self, obj):
        workflow = self._workflow(obj)
        if not workflow: return []
        from apps.agents.serializers import AgentStepSerializer
        return AgentStepSerializer(workflow.steps.all(), many=True).data
    def get_workflow_status(self, obj):
        workflow = self._workflow(obj); return workflow.status if workflow else obj.status
    class Meta: model = GenerationTask; fields = "__all__"; read_only_fields = ["status", "progress", "retrieved_chunks", "success_count", "failed_count", "error_message", "finished_at", "model_name", "embedding_model"]
