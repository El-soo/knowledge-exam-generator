from django.db import models

class SystemConfig(models.Model):
    config_key = models.CharField(max_length=120, unique=True)
    config_value = models.JSONField(default=dict)
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

class PromptTemplate(models.Model):
    key = models.CharField(max_length=80)
    version = models.PositiveIntegerField(default=1)
    content = models.TextField()
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["key", "version"], name="unique_prompt_version")]

class AITaskResult(models.Model):
    task_type = models.CharField(max_length=40)
    input_config = models.JSONField(default=dict)
    result_json = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="PREVIEW")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
