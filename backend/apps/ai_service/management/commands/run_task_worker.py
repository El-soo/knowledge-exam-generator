import signal
import threading
import time
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import OperationalError, close_old_connections, transaction
from django.utils import timezone
from apps.knowledge.models import ParseTask
from apps.knowledge.services import FileParseService
from apps.questions.models import GenerationTask
from apps.questions.services import GenerationService
from apps.system_settings.models import SystemConfig
from apps.agents.models import AgentWorkflowRun
from apps.agents.services import AgentWorkflowService, create_question_workflow

class Command(BaseCommand):
    help = "运行本地后台任务Worker（文件解析、向量化和AI出题）"
    stopped = False
    def handle(self, *args, **options):
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "stopped", True)); signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopped", True))
        stale = timezone.now() - timedelta(minutes=5)
        ParseTask.objects.filter(status="RUNNING", heartbeat_at__lt=stale).update(status="INTERRUPTED", error_message="Django或Worker重启，任务已中断，可重新解析。")
        GenerationTask.objects.filter(status="RUNNING", heartbeat_at__lt=stale).update(status="INTERRUPTED", error_message="Django或Worker重启，任务已中断，可重新生成。")
        AgentWorkflowRun.objects.filter(status="RUNNING", heartbeat_at__lt=stale).update(status="INTERRUPTED", error_message="Django或Worker重启，智能体工作流已中断，可重试。")
        self.stdout.write(self.style.SUCCESS("后台Worker已启动，按 Ctrl+C 停止。"))
        SystemConfig.objects.update_or_create(config_key="worker_heartbeat", defaults={"config_value":{"status":"RUNNING"}, "description":"本地后台Worker心跳"})
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(target=self.heartbeat, args=(heartbeat_stop,), daemon=True)
        heartbeat_thread.start()
        try:
            while not self.stopped:
                try:
                    # 智能体工作流按优先级执行：出题 > 组卷 > 知识整理 > 向量化。
                    workflow = self.claim(AgentWorkflowRun)
                    if workflow: AgentWorkflowService().run(workflow); continue
                    # 兼容升级前已经排队、但没有工作流记录的老出题任务。
                    generation = self.claim(GenerationTask)
                    if generation:
                        if str(generation.config.get("quality_mode", "STANDARD")).upper() == "DEEP":
                            workflow = create_question_workflow(generation, "DEEP")
                            AgentWorkflowService().run(workflow)
                        else:
                            GenerationService().run(generation)
                        continue
                    task = self.claim(ParseTask)
                    if task: FileParseService().run(task); continue
                except OperationalError:
                    # SQLite 只允许一个写入者。API 请求或心跳短暂占用数据库时，
                    # 稍后重试即可，不应让整个 Worker 退出。
                    close_old_connections()
                    time.sleep(0.2)
                    continue
                time.sleep(1)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)
            self.stdout.write("后台Worker已安全停止。")
            SystemConfig.objects.update_or_create(config_key="worker_heartbeat", defaults={"config_value":{"status":"STOPPED"}, "description":"本地后台Worker心跳"})

    @staticmethod
    def heartbeat(stop_event):
        # 先等待一个周期；启动状态已由主线程写入，避免两个线程
        # 在 Worker 刚启动时同时争抢 SQLite 写锁。
        while not stop_event.wait(5):
            try:
                close_old_connections()
                SystemConfig.objects.update_or_create(config_key="worker_heartbeat", defaults={"config_value":{"status":"RUNNING"}, "description":"本地后台Worker心跳"})
            except OperationalError:
                # SQLite 同一时刻只允许一个写入者；主线程领取任务时短暂重试即可。
                pass
            finally:
                close_old_connections()
    @staticmethod
    def claim(model):
        with transaction.atomic():
            queryset = model.objects.select_for_update().filter(status="WAITING")
            if model is ParseTask:
                queryset = queryset.order_by("knowledge_file__file_size", "created_at")
            elif model is AgentWorkflowRun:
                queryset = queryset.order_by("-priority", "created_at")
            elif model is GenerationTask:
                linked_ids = AgentWorkflowRun.objects.filter(
                    business_type="generation_task", status__in=["WAITING", "RUNNING"]
                ).values_list("business_id", flat=True)
                queryset = queryset.exclude(id__in=linked_ids).order_by("created_at")
            else:
                queryset = queryset.order_by("created_at")
            item = queryset.first()
            if item: item.status = "RUNNING"; item.heartbeat_at = timezone.now(); item.save()
            return item
