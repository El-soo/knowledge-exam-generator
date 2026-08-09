import uuid
from django.db import models


class AgentDefinition(models.Model):
    key = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    role = models.TextField()
    model_setting_key = models.CharField(max_length=60, default="chat_model")
    prompt_key = models.CharField(max_length=80, blank=True)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]


class AgentWorkflowRun(models.Model):
    STATUSES = [(x, x) for x in ["WAITING", "RUNNING", "AWAITING_REVIEW", "SUCCESS", "FAILED", "CANCELLED", "INTERRUPTED"]]
    QUALITY_MODES = [(x, x) for x in ["FAST", "STANDARD", "DEEP"]]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow_type = models.CharField(max_length=60, db_index=True)
    business_type = models.CharField(max_length=60, db_index=True)
    business_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=30, choices=STATUSES, default="WAITING", db_index=True)
    priority = models.PositiveSmallIntegerField(default=50, db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    current_agent = models.CharField(max_length=80, blank=True)
    quality_mode = models.CharField(max_length=20, choices=QUALITY_MODES, default="STANDARD")
    thread_id = models.CharField(max_length=80, unique=True)
    input_data = models.JSONField(default=dict, blank=True)
    state_summary = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    cancel_requested = models.BooleanField(default=False)
    retry_count = models.PositiveSmallIntegerField(default=0)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "priority", "created_at"], name="agents_agen_status_9b52e5_idx")]

    def save(self, *args, **kwargs):
        if not self.thread_id:
            self.thread_id = str(self.id or uuid.uuid4())
        super().save(*args, **kwargs)


class AgentStepRun(models.Model):
    workflow = models.ForeignKey(AgentWorkflowRun, on_delete=models.CASCADE, related_name="steps")
    agent_key = models.CharField(max_length=80)
    step_name = models.CharField(max_length=120)
    status = models.CharField(max_length=30, default="WAITING", db_index=True)
    attempt = models.PositiveSmallIntegerField(default=1)
    input_summary = models.JSONField(default=dict, blank=True)
    output_summary = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["workflow", "agent_key", "attempt"], name="unique_agent_step_attempt")]


class AgentArtifact(models.Model):
    workflow = models.ForeignKey(AgentWorkflowRun, on_delete=models.CASCADE, related_name="artifacts")
    artifact_type = models.CharField(max_length=60, db_index=True)
    created_by = models.CharField(max_length=80)
    version = models.PositiveSmallIntegerField(default=1)
    content = models.JSONField(default=dict)
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["artifact_type", "-version"]
        constraints = [models.UniqueConstraint(fields=["workflow", "artifact_type", "version"], name="unique_agent_artifact_version")]


class AgentMetric(models.Model):
    workflow = models.ForeignKey(AgentWorkflowRun, on_delete=models.CASCADE, related_name="metrics")
    agent_key = models.CharField(max_length=80)
    model_name = models.CharField(max_length=120, blank=True)
    call_count = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    input_chars = models.PositiveIntegerField(default=0)
    output_chars = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    rework_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
