from django.db import models

class Course(models.Model):
    STATUS_CHOICES = [("ACTIVE", "使用中"), ("ARCHIVED", "已归档")]
    name = models.CharField("课程名称", max_length=120)
    code = models.CharField("课程编号", max_length=50, blank=True)
    description = models.TextField("课程简介", blank=True)
    grade = models.CharField("适用年级", max_length=80, blank=True)
    major = models.CharField("适用专业", max_length=120, blank=True)
    cover = models.ImageField(upload_to="course_covers/%Y/%m/", blank=True)
    remark = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE", db_index=True)
    is_demo = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["is_deleted", "status"])]
    def __str__(self): return self.name
