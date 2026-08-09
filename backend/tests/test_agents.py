import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.agents.models import AgentStepRun, AgentWorkflowRun
from apps.agents.services import (
    AgentWorkflowService,
    HybridRetrievalService,
    create_paper_plan_workflow,
    create_question_workflow,
    ensure_agent_definitions,
    retry_workflow,
)
from apps.courses.models import Course
from apps.knowledge.models import Chapter, KnowledgePoint
from apps.questions.models import GenerationTask, Question, QuestionOption, QuestionReview
from apps.system_settings.models import AITaskResult


class AgentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.course = Course.objects.create(name="多智能体测试课程")

    def test_only_deep_generation_creates_agent_workflow(self):
        response = self.client.post(
            "/api/v1/generation/tasks/",
            {"course": self.course.id, "count": 2, "question_types": ["judge"], "type_counts": {"judge": 2}, "quality_mode": "STANDARD"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(AgentWorkflowRun.objects.filter(business_type="generation_task", business_id=data["id"]).exists())
        self.assertIsNone(data["workflow_id"])

        response = self.client.post(
            "/api/v1/generation/tasks/",
            {"course": self.course.id, "count": 2, "question_types": ["judge"], "type_counts": {"judge": 2}, "quality_mode": "DEEP"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        workflow = AgentWorkflowRun.objects.get(business_type="generation_task", business_id=data["id"])
        self.assertEqual(workflow.quality_mode, "DEEP")
        self.assertEqual(workflow.priority, 100)
        self.assertEqual(data["workflow_id"], str(workflow.id))
        self.assertEqual(data["workflow_status"], "WAITING")

    def test_generation_task_rejects_unknown_quality_mode(self):
        response = self.client.post(
            "/api/v1/generation/tasks/",
            {"course": self.course.id, "count": 1, "question_types": ["judge"], "quality_mode": "UNSAFE"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("质量模式", response.json()["message"])

    def test_agents_endpoint_seeds_role_definitions(self):
        response = self.client.get("/api/v1/agents/")
        self.assertEqual(response.status_code, 200)
        keys = {item["key"] for item in response.json()["data"]}
        self.assertTrue({"supervisor", "retrieval_planner", "question_author", "answer_reviewer", "paper_planner"}.issubset(keys))

    def test_batch_review_only_changes_questions_from_current_task(self):
        first_task = GenerationTask.objects.create(course=self.course, total_count=1)
        other_task = GenerationTask.objects.create(course=self.course, total_count=1)
        first = Question.objects.create(course=self.course, generation_task=first_task, question_type="judge", stem="测试题1", answer=["正确"], analysis="解析", score=1, content_hash="a" * 64)
        other = Question.objects.create(course=self.course, generation_task=other_task, question_type="judge", stem="测试题2", answer=["正确"], analysis="解析", score=1, content_hash="b" * 64)
        response = self.client.post(f"/api/v1/generation/tasks/{first_task.id}/batch-review/", {"approve_ids": [first.id, other.id]}, format="json")
        self.assertEqual(response.status_code, 200)
        first.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(first.review_status, "APPROVED")
        self.assertEqual(other.review_status, "PENDING")

    def test_confirm_knowledge_curation_imports_preview_once(self):
        preview = AITaskResult.objects.create(task_type="KNOWLEDGE_CURATION", result_json={})
        workflow = AgentWorkflowRun.objects.create(
            workflow_type="KNOWLEDGE_CURATION", business_type="knowledge_file", business_id=1,
            status="AWAITING_REVIEW", thread_id="knowledge-confirm-test",
            input_data={"course_id": self.course.id}, result={
                "preview_id": preview.id,
                "chapters": [{"name": "第一章 基础", "number": "1", "description": "基础概念"}],
                "knowledge_points": [{"name": "变量", "description": "变量定义", "keywords": ["变量"], "importance": "重要", "difficulty": "简单", "chapter_name": "第一章 基础"}],
            },
        )
        response = self.client.post(f"/api/v1/agent-workflows/{workflow.id}/confirm/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Chapter.objects.filter(course=self.course, name="第一章 基础").exists())
        self.assertTrue(KnowledgePoint.objects.filter(course=self.course, name="变量").exists())
        preview.refresh_from_db(); workflow.refresh_from_db()
        self.assertEqual(preview.status, "CONFIRMED")
        self.assertEqual(workflow.status, "SUCCESS")


class AgentAlgorithmTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(name="检索算法课程")

    @patch("apps.agents.services.GenerationService.run")
    def test_partial_generation_does_not_continue_to_review(self, run_generation):
        task = GenerationTask.objects.create(course=self.course, total_count=2, status="RUNNING")
        workflow = create_question_workflow(task, "DEEP")
        Question.objects.create(
            course=self.course, generation_task=task, question_type="judge",
            stem="示例判断题", answer=["正确"], analysis="示例解析", score=2,
            content_hash="f" * 64,
        )

        def leave_partial(current_task):
            GenerationTask.objects.filter(pk=current_task.pk).update(status="FAILED", success_count=1, failed_count=1, error_message="题目数量不足")

        run_generation.side_effect = leave_partial
        with self.assertRaisesMessage(Exception, "题目数量不足"):
            AgentWorkflowService()._author(workflow, {})

    @patch.object(HybridRetrievalService, "_chunk_usage", return_value={2: 20})
    @patch.object(HybridRetrievalService, "_lexical")
    @patch("apps.agents.services.VectorService.search_many")
    def test_hybrid_retrieval_fuses_rankings_and_penalizes_overused_chunks(self, vector_search, lexical_search, _usage):
        vector_search.return_value = [
            {"chunk_id": 1, "content": "Python函数使用def定义，参数写在括号中。", "match_type": "VECTOR"},
            {"chunk_id": 2, "content": "Python函数使用def定义，可以返回结果。", "match_type": "VECTOR"},
        ]
        lexical_search.return_value = [
            {"chunk_id": 3, "content": "return语句用于从函数返回计算结果。", "match_type": "KEYWORD"},
            {"chunk_id": 2, "content": "Python函数使用def定义，可以返回结果。", "match_type": "KEYWORD"},
        ]
        results = HybridRetrievalService().retrieve(["函数定义"], {"course_id": self.course.id}, limit=3)
        self.assertEqual({item["chunk_id"] for item in results}, {1, 2, 3})
        self.assertLess(next(index for index, item in enumerate(results) if item["chunk_id"] == 2), 3)
        merged = next(item for item in results if item["chunk_id"] == 2)
        self.assertEqual(set(merged["matches"]), {"VECTOR", "KEYWORD"})

    def test_review_router_stops_after_configured_revision_limit(self):
        service = AgentWorkflowService()
        self.assertEqual(service._after_review({"failed_review_ids": [1], "revision_round": 0, "max_revisions": 1}), "revise")
        self.assertEqual(service._after_review({"failed_review_ids": [1], "revision_round": 1, "max_revisions": 1}), "rules")
        self.assertEqual(service._after_review({"failed_review_ids": [], "revision_round": 0, "max_revisions": 2}), "rules")

    @patch("apps.agents.services.OllamaService.chat_json")
    def test_answer_reviewer_solves_without_original_answer_and_rejects_mismatch(self, mocked_chat):
        task = GenerationTask.objects.create(course=self.course, total_count=1, status="RUNNING")
        question = Question.objects.create(
            course=self.course, generation_task=task, question_type="single_choice",
            stem="计算2+2的结果。", answer=["B"], analysis="2+2=4。", difficulty="简单", score=2,
            content_hash="e" * 64,
        )
        QuestionOption.objects.bulk_create([
            QuestionOption(question=question, label="A", content="3", sort_order=0),
            QuestionOption(question=question, label="B", content="4", is_correct=True, sort_order=1),
            QuestionOption(question=question, label="C", content="5", sort_order=2),
            QuestionOption(question=question, label="D", content="6", sort_order=3),
        ])
        workflow = create_question_workflow(task, "STANDARD")
        mocked_chat.side_effect = [
            {"solutions": [{"question_id": question.id, "answer": ["A"], "reasoning": "独立计算结果", "confidence": 0.95}]},
            {"reviews": [{"question_id": question.id, "passed": True, "score": 95, "grounding_score": 0.9, "issues": [], "suggestions": []}]},
        ]
        result = AgentWorkflowService()._review(workflow, {"question_ids": [question.id], "revision_round": 0, "max_revisions": 1})
        question.refresh_from_db()
        self.assertEqual(result["failed_review_ids"], [question.id])
        self.assertEqual(question.review_status, "NEEDS_REVISION")
        independent = QuestionReview.objects.get(question=question, review_type="INDEPENDENT_ANSWER")
        self.assertFalse(independent.passed)
        self.assertIn("不一致", independent.issues[0])
        solver_prompt = mocked_chat.call_args_list[0].args[0][1]["content"]
        self.assertNotIn('"answer": ["B"]', solver_prompt)
        self.assertEqual(mocked_chat.call_count, 2)

    def test_retry_uses_new_thread_and_preserves_business_link(self):
        task = GenerationTask.objects.create(course=self.course, total_count=1)
        workflow = create_question_workflow(task)
        old_thread = workflow.thread_id
        workflow.status = "INTERRUPTED"; workflow.save()
        retry_workflow(workflow)
        self.assertEqual(workflow.status, "WAITING")
        self.assertNotEqual(workflow.thread_id, old_thread)
        self.assertEqual(workflow.business_id, task.id)

    @patch("langchain_ollama.OllamaEmbeddings")
    def test_semantic_duplicate_detection_uses_embedding_similarity(self, embeddings_class):
        current_task = GenerationTask.objects.create(course=self.course, total_count=1)
        current = Question.objects.create(course=self.course, generation_task=current_task, question_type="judge", stem="函数可以通过return返回结果", answer=["正确"], analysis="解析", content_hash="c" * 64)
        existing = Question.objects.create(course=self.course, question_type="judge", stem="return语句能够把函数结果返回给调用者", answer=["正确"], analysis="解析", content_hash="d" * 64)
        embeddings_class.return_value.embed_documents.return_value = [[1.0, 0.0], [0.99, 0.01]]
        matches, error = AgentWorkflowService._semantic_duplicate_matches([current])
        self.assertEqual(error, "")
        self.assertEqual(matches[current.id]["question_id"], existing.id)
        self.assertEqual(matches[current.id]["match_type"], "SEMANTIC")


class AgentGraphTests(TestCase):
    def setUp(self):
        ensure_agent_definitions()

    @patch.object(AgentWorkflowService, "_run_question_graph")
    def test_error_after_cancel_does_not_change_workflow_back_to_failed(self, run_graph):
        course = Course.objects.create(name="取消状态测试课程")
        task = GenerationTask.objects.create(course=course, total_count=1, status="RUNNING")
        workflow = create_question_workflow(task, "DEEP")

        def cancel_then_fail(current_workflow):
            AgentWorkflowRun.objects.filter(pk=current_workflow.pk).update(cancel_requested=True, status="CANCELLED")
            raise RuntimeError("模型连接已中断")

        run_graph.side_effect = cancel_then_fail
        AgentWorkflowService().run(workflow)
        workflow.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(workflow.status, "CANCELLED")
        self.assertEqual(task.status, "CANCELLED")

    @override_settings(LANGGRAPH_CHECKPOINT_PATH=Path(tempfile.mkdtemp()) / "agent_checkpoints.sqlite3")
    @patch("apps.papers.services.parse_natural_rule")
    def test_paper_planning_graph_persists_steps_and_removes_duration(self, parse_rule):
        parse_rule.return_value = {
            "name": "Python期末试卷", "paper_type": "AI辅助组卷", "duration": 90,
            "target_score": 10, "type_config": [{"type": "judge", "count": 10, "score_each": 1}],
            "difficulty_ratio": {"简单": 0.3, "中等": 0.5, "困难": 0.2},
        }
        workflow = create_paper_plan_workflow("生成Python期末试卷", None)
        AgentWorkflowService().run(workflow)
        workflow.refresh_from_db()
        self.assertEqual(workflow.status, "AWAITING_REVIEW")
        self.assertNotIn("duration", workflow.result)
        self.assertEqual(list(workflow.steps.values_list("agent_key", flat=True)), ["paper_planner", "supervisor"])
        self.assertTrue(all(status == "SUCCESS" for status in workflow.steps.values_list("status", flat=True)))
