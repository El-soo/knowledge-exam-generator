from rest_framework import serializers
from .models import AgentArtifact, AgentDefinition, AgentMetric, AgentStepRun, AgentWorkflowRun


class AgentDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentDefinition
        fields = "__all__"
        read_only_fields = ["key", "name", "role", "model_setting_key", "prompt_key", "sort_order", "updated_at"]


class AgentStepSerializer(serializers.ModelSerializer):
    agent_name = serializers.SerializerMethodField()

    def get_agent_name(self, obj):
        return AgentDefinition.objects.filter(key=obj.agent_key).values_list("name", flat=True).first() or obj.agent_key

    class Meta:
        model = AgentStepRun
        fields = "__all__"


class AgentArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentArtifact
        fields = "__all__"


class AgentMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentMetric
        fields = "__all__"


class AgentWorkflowSerializer(serializers.ModelSerializer):
    steps = AgentStepSerializer(many=True, read_only=True)
    artifacts = AgentArtifactSerializer(many=True, read_only=True)
    metrics = AgentMetricSerializer(many=True, read_only=True)
    business_name = serializers.SerializerMethodField()

    def get_business_name(self, obj):
        if obj.business_type == "generation_task" and obj.business_id:
            from apps.questions.models import GenerationTask
            task = GenerationTask.objects.select_related("course").filter(pk=obj.business_id).first()
            return f"{task.course.name}·出题任务#{task.id}" if task else "出题任务"
        return obj.input_data.get("name") or obj.input_data.get("text", "")[:40] or obj.workflow_type

    class Meta:
        model = AgentWorkflowRun
        fields = "__all__"
