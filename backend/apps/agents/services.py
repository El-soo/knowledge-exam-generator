import json
import logging
import math
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import TypedDict

import numpy as np
from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Max
from django.utils import timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from apps.ai_service.services import OllamaService, get_config, get_prompt
from apps.knowledge.models import TextChunk
from apps.knowledge.services import VectorService, is_meaningful_chunk
from apps.questions.models import GenerationTask, Question, QuestionOption, QuestionReview
from apps.questions.services import (
    GenerationService,
    find_generation_duplicate,
    generation_topic_queries,
    independent_answers_consistent,
    normalize_generated_question,
    question_batch_schema,
    question_hash,
    snapshot_question,
    validate_question_structure,
)
from common.exceptions import BusinessError
from .models import AgentArtifact, AgentDefinition, AgentMetric, AgentStepRun, AgentWorkflowRun

logger = logging.getLogger("agents")

AGENT_DEFINITIONS = [
    ("supervisor", "总控调度智能体", "校验任务并编制可执行的出题或组卷计划。", "chat_model", "", 10),
    ("retrieval_planner", "检索规划智能体", "拆分检索主题，融合向量和关键词结果，构建多样化证据包。", "embedding_model", "query_rewrite", 20),
    ("question_author", "命题智能体", "严格依据证据包生成题干、答案、解析和来源。", "chat_model", "question_generation", 30),
    ("answer_reviewer", "答案校验智能体", "独立核对答案、解析与知识库证据是否一致。", "review_model", "question_review", 40),
    ("rule_similarity", "规则与相似度智能体", "执行题型结构、禁用语、Hash、文字和语义相似度校验。", "embedding_model", "", 50),
    ("quality_reviewer", "质量审核智能体", "评估知识忠实度、题意、难度、干扰项和教学价值。", "review_model", "question_review", 60),
    ("question_reviser", "修订智能体", "根据审核问题定向修订题目，不得脱离原证据。", "chat_model", "question_generation", 70),
    ("knowledge_curator", "知识整理智能体", "从解析后的资料中识别章节和可命题知识点。", "knowledge_model", "knowledge_point", 80),
    ("paper_planner", "组卷规划智能体", "把自然语言要求转换为不含考试时间的结构化组卷规则。", "chat_model", "paper_rule", 90),
    ("paper_selector", "组卷选题智能体", "根据题型、难度、覆盖率和使用次数从正式题库选题。", "chat_model", "", 100),
    ("paper_evaluator", "试卷评估智能体", "检查总分、结构、难度、覆盖率和重复度并给出建议。", "review_model", "", 110),
]


def ensure_agent_definitions():
    for key, name, role, model_key, prompt_key, order in AGENT_DEFINITIONS:
        AgentDefinition.objects.update_or_create(
            key=key,
            defaults={"name": name, "role": role, "model_setting_key": model_key, "prompt_key": prompt_key, "sort_order": order},
        )


def get_agent_config(key):
    ensure_agent_definitions()
    agent = AgentDefinition.objects.get(key=key)
    config = get_config()
    return {"enabled": agent.enabled, "model": agent.config.get("model") or config.get(agent.model_setting_key), **agent.config}


def create_question_workflow(task, quality_mode="STANDARD"):
    quality_mode = str(quality_mode or "STANDARD").upper()
    if quality_mode not in {"FAST", "STANDARD", "DEEP"}:
        raise BusinessError("质量模式必须是快速、标准或深度。", 40071)
    ensure_agent_definitions()
    existing = AgentWorkflowRun.objects.filter(business_type="generation_task", business_id=task.id).exclude(status="CANCELLED").first()
    if existing:
        return existing
    return AgentWorkflowRun.objects.create(
        workflow_type="QUESTION_GENERATION",
        business_type="generation_task",
        business_id=task.id,
        quality_mode=quality_mode,
        priority=100,
        thread_id=str(uuid.uuid4()),
        input_data={"course_id": task.course_id, "count": task.total_count, "config": task.config},
    )


def create_paper_plan_workflow(text, course_id=None):
    if not str(text or "").strip():
        raise BusinessError("请输入组卷要求。", 40058)
    ensure_agent_definitions()
    return AgentWorkflowRun.objects.create(
        workflow_type="PAPER_PLAN",
        business_type="paper_plan",
        priority=90,
        quality_mode="STANDARD",
        thread_id=str(uuid.uuid4()),
        input_data={"text": str(text).strip(), "course_id": course_id},
    )


def create_knowledge_curation_workflow(knowledge_file):
    config = knowledge_file.parse_config or {}
    if not (config.get("auto_chapter") or config.get("auto_knowledge")):
        return None
    ensure_agent_definitions()
    existing = AgentWorkflowRun.objects.filter(business_type="knowledge_file", business_id=knowledge_file.id, status__in=["WAITING", "RUNNING", "AWAITING_REVIEW"]).first()
    if existing:
        return existing
    return AgentWorkflowRun.objects.create(
        workflow_type="KNOWLEDGE_CURATION", business_type="knowledge_file", business_id=knowledge_file.id,
        priority=20, quality_mode="STANDARD", thread_id=str(uuid.uuid4()),
        input_data={"file_id": knowledge_file.id, "course_id": knowledge_file.course_id, "auto_chapter": bool(config.get("auto_chapter")), "auto_knowledge": bool(config.get("auto_knowledge"))},
    )


def create_artifact(workflow, artifact_type, created_by, content):
    latest = AgentArtifact.objects.filter(workflow=workflow, artifact_type=artifact_type).aggregate(value=Max("version"))["value"] or 0
    AgentArtifact.objects.filter(workflow=workflow, artifact_type=artifact_type, is_current=True).update(is_current=False)
    return AgentArtifact.objects.create(workflow=workflow, artifact_type=artifact_type, created_by=created_by, version=latest + 1, content=content)


class HybridRetrievalService:
    """RRF融合向量/关键词排名，再用MMR抑制内容重复。"""

    def retrieve(self, queries, filters, limit=30, threshold=0.25):
        queries = [str(item).strip() for item in queries if str(item).strip()]
        if not queries:
            return []
        vector = VectorService().search_many(queries, filters, per_query=max(3, min(8, math.ceil(limit / len(queries)))), threshold=threshold, max_results=limit * 2)
        lexical = self._lexical(queries, filters, limit * 2)
        usage = self._chunk_usage(filters.get("course_id"))
        fused = {}
        for source, weight in ((vector, 1.0), (lexical, 0.85)):
            for rank, item in enumerate(source, 1):
                chunk_id = int(item.get("chunk_id") or 0)
                if not chunk_id:
                    continue
                entry = fused.setdefault(chunk_id, {**item, "rrf_score": 0.0, "matches": []})
                entry["rrf_score"] += weight / (60 + rank)
                entry["matches"].append(item.get("match_type", "VECTOR"))
        ordered = sorted(fused.values(), key=lambda item: item["rrf_score"] / (1 + usage.get(int(item["chunk_id"]), 0) * 0.08), reverse=True)
        return self._mmr(ordered, limit)

    @staticmethod
    def _queryset(filters):
        qs = TextChunk.objects.select_related("knowledge_file", "chapter").filter(knowledge_file__is_enabled=True, knowledge_file__is_deleted=False)
        for key, field in (("course_id", "course_id"), ("file_id", "knowledge_file_id"), ("chapter_id", "chapter_id")):
            if filters.get(key):
                qs = qs.filter(**{field: filters[key]})
        return qs

    def _lexical(self, queries, filters, limit):
        chunks = list(self._queryset(filters).only("id", "content", "chunk_index", "page_number", "knowledge_file__original_name", "knowledge_file_id", "chapter_id")[:2000])
        if not chunks:
            return []
        texts = [chunk.content for chunk in chunks]
        try:
            matrix = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), max_features=12000).fit_transform(texts + queries)
            scores = cosine_similarity(matrix[-len(queries):], matrix[:-len(queries)]).max(axis=0)
        except ValueError:
            return []
        results = []
        for index in np.argsort(scores)[::-1][:limit]:
            if scores[index] <= 0 or not is_meaningful_chunk(chunks[index].content):
                continue
            chunk = chunks[index]
            results.append({
                "chunk_id": chunk.id, "content": chunk.content, "similarity": round(float(scores[index]), 4),
                "file_id": chunk.knowledge_file_id, "file_name": chunk.knowledge_file.original_name,
                "chapter_id": chunk.chapter_id, "page_number": chunk.page_number, "chunk_index": chunk.chunk_index,
                "match_type": "KEYWORD", "retrieval_query": queries[0],
            })
        return results

    @staticmethod
    def _chunk_usage(course_id):
        counter = Counter()
        if not course_id:
            return counter
        for ids in Question.objects.filter(course_id=course_id, is_deleted=False).values_list("source_chunk_ids", flat=True):
            counter.update(int(item) for item in (ids or []) if str(item).isdigit())
        return counter

    @staticmethod
    def _mmr(items, limit, diversity=0.35):
        if len(items) <= 1:
            return items[:limit]
        texts = [str(item.get("content", "")) for item in items]
        try:
            vectors = TfidfVectorizer(analyzer="char", ngram_range=(2, 3), max_features=8000).fit_transform(texts)
            pairwise = cosine_similarity(vectors)
        except ValueError:
            return items[:limit]
        selected, remaining = [], list(range(len(items)))
        relevance = np.array([float(item.get("rrf_score", 0)) for item in items])
        if relevance.max() > 0:
            relevance = relevance / relevance.max()
        while remaining and len(selected) < limit:
            best = max(remaining, key=lambda idx: (1 - diversity) * relevance[idx] - diversity * max((pairwise[idx][chosen] for chosen in selected), default=0))
            selected.append(best)
            remaining.remove(best)
        return [{**items[idx], "rrf_score": round(float(items[idx].get("rrf_score", 0)), 6)} for idx in selected]


class WorkflowState(TypedDict, total=False):
    workflow_id: str
    task_id: int
    plan: dict
    evidence_count: int
    question_ids: list[int]
    failed_review_ids: list[int]
    revision_round: int
    max_revisions: int
    rule_failures: dict
    result: dict


class WorkflowCancelled(Exception):
    pass


class AgentWorkflowService:
    def run(self, workflow):
        workflow.refresh_from_db()
        if workflow.cancel_requested:
            self._cancel(workflow)
            return
        workflow.status = "RUNNING"
        workflow.started_at = workflow.started_at or timezone.now()
        workflow.heartbeat_at = timezone.now()
        workflow.error_message = ""
        workflow.save()
        try:
            if workflow.workflow_type == "QUESTION_GENERATION":
                self._run_question_graph(workflow)
            elif workflow.workflow_type == "PAPER_PLAN":
                self._run_paper_graph(workflow)
            elif workflow.workflow_type == "KNOWLEDGE_CURATION":
                self._run_knowledge_graph(workflow)
            else:
                raise BusinessError(f"不支持的智能体工作流：{workflow.workflow_type}", 40072)
        except WorkflowCancelled:
            self._cancel(workflow)
        except Exception as exc:
            workflow.refresh_from_db()
            if workflow.cancel_requested or workflow.status == "CANCELLED":
                self._cancel(workflow)
                return
            workflow.status = "FAILED"
            workflow.error_message = str(exc)
            workflow.finished_at = timezone.now()
            workflow.save()
            if workflow.business_type == "generation_task" and workflow.business_id:
                GenerationTask.objects.filter(pk=workflow.business_id).update(status="FAILED", error_message=str(exc), finished_at=timezone.now())
            logger.exception("智能体工作流%s失败", workflow.id)
        finally:
            close_old_connections()

    def _run_question_graph(self, workflow):
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(WorkflowState)
        builder.add_node("supervisor", lambda state: self._step(workflow, "supervisor", "编制出题计划", state, self._supervisor))
        builder.add_node("retrieval_planner", lambda state: self._step(workflow, "retrieval_planner", "构建RAG证据包", state, self._retrieve))
        builder.add_node("question_author", lambda state: self._step(workflow, "question_author", "生成题目与答案", state, self._author))
        builder.add_node("answer_reviewer", lambda state: self._step(workflow, "answer_reviewer", "独立校验答案与依据", state, self._review))
        builder.add_node("question_reviser", lambda state: self._step(workflow, "question_reviser", "根据审核意见修订", state, self._revise))
        builder.add_node("rule_similarity", lambda state: self._step(workflow, "rule_similarity", "执行规则和相似题检测", state, self._rules))
        builder.add_node("quality_reviewer", lambda state: self._step(workflow, "quality_reviewer", "汇总质量结论", state, self._finalize_questions))
        builder.add_edge(START, "supervisor")
        builder.add_edge("supervisor", "retrieval_planner")
        builder.add_edge("retrieval_planner", "question_author")
        builder.add_conditional_edges("question_author", lambda state: "rules" if workflow.quality_mode == "FAST" else "review", {"review": "answer_reviewer", "rules": "rule_similarity"})
        builder.add_conditional_edges("answer_reviewer", self._after_review, {"revise": "question_reviser", "rules": "rule_similarity"})
        builder.add_edge("question_reviser", "answer_reviewer")
        builder.add_edge("rule_similarity", "quality_reviewer")
        builder.add_edge("quality_reviewer", END)
        checkpoint_path = Path(settings.LANGGRAPH_CHECKPOINT_PATH)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        config = {"configurable": {"thread_id": workflow.thread_id}}
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            graph = builder.compile(checkpointer=saver)
            existing = saver.get_tuple(config)
            configured_revisions = int(get_agent_config("question_reviser").get("max_revisions", 2 if workflow.quality_mode == "DEEP" else 1))
            initial = None if existing and existing.checkpoint.get("channel_values") else {"workflow_id": str(workflow.id), "task_id": workflow.business_id, "revision_round": 0, "max_revisions": 0 if workflow.quality_mode == "FAST" else configured_revisions}
            graph.invoke(initial, config=config)

    def _run_paper_graph(self, workflow):
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(WorkflowState)
        builder.add_node("paper_planner", lambda state: self._step(workflow, "paper_planner", "解析自然语言组卷要求", state, self._paper_plan))
        builder.add_node("supervisor", lambda state: self._step(workflow, "supervisor", "校验结构化组卷规则", state, self._paper_validate))
        builder.add_edge(START, "paper_planner")
        builder.add_edge("paper_planner", "supervisor")
        builder.add_edge("supervisor", END)
        checkpoint_path = Path(settings.LANGGRAPH_CHECKPOINT_PATH)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        config = {"configurable": {"thread_id": workflow.thread_id}}
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            graph = builder.compile(checkpointer=saver)
            graph.invoke({"workflow_id": str(workflow.id)}, config=config)

    def _run_knowledge_graph(self, workflow):
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
        builder = StateGraph(WorkflowState)
        builder.add_node("knowledge_curator", lambda state: self._step(workflow, "knowledge_curator", "识别章节与知识点预览", state, self._knowledge_curate))
        builder.add_node("supervisor", lambda state: self._step(workflow, "supervisor", "保存待教师确认的整理结果", state, self._knowledge_finalize))
        builder.add_edge(START, "knowledge_curator"); builder.add_edge("knowledge_curator", "supervisor"); builder.add_edge("supervisor", END)
        checkpoint_path = Path(settings.LANGGRAPH_CHECKPOINT_PATH); checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        config = {"configurable": {"thread_id": workflow.thread_id}}
        with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            builder.compile(checkpointer=saver).invoke({"workflow_id": str(workflow.id)}, config=config)

    def _step(self, workflow, agent_key, step_name, state, handler):
        self._check_cancel(workflow)
        attempt = (AgentStepRun.objects.filter(workflow=workflow, agent_key=agent_key).aggregate(value=Max("attempt"))["value"] or 0) + 1
        step = AgentStepRun.objects.create(workflow=workflow, agent_key=agent_key, step_name=step_name, status="RUNNING", attempt=attempt, input_summary=self._state_summary(state), started_at=timezone.now())
        workflow.current_agent = agent_key
        workflow.heartbeat_at = timezone.now()
        workflow.progress = min(95, AgentStepRun.objects.filter(workflow=workflow, status="SUCCESS").count() * 14 + 5)
        workflow.save(update_fields=["current_agent", "heartbeat_at", "progress", "updated_at"])
        started = time.monotonic()
        try:
            output = handler(workflow, state) or {}
            step.status = "SUCCESS"
            step.output_summary = self._state_summary(output)
            step.metrics = {"duration_ms": int((time.monotonic() - started) * 1000)}
            step.finished_at = timezone.now()
            step.save()
            workflow.state_summary = {**workflow.state_summary, **step.output_summary}
            workflow.save(update_fields=["state_summary", "updated_at"])
            return output
        except Exception as exc:
            step.status = "FAILED"
            step.error_message = str(exc)
            step.metrics = {"duration_ms": int((time.monotonic() - started) * 1000)}
            step.finished_at = timezone.now()
            step.save()
            raise

    @staticmethod
    def _state_summary(data):
        summary = {}
        for key, value in (data or {}).items():
            if key in {"plan", "result", "rule_failures"}:
                summary[key] = value
            elif isinstance(value, list):
                summary[f"{key}_count"] = len(value)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                summary[key] = value
        return summary

    @staticmethod
    def _check_cancel(workflow):
        workflow.refresh_from_db(fields=["cancel_requested"])
        if workflow.cancel_requested:
            raise WorkflowCancelled()

    @staticmethod
    def _supervisor(workflow, state):
        task = GenerationTask.objects.select_related("course").get(pk=workflow.business_id)
        config = task.config
        counts = config.get("type_counts") or {}
        plan = {"course": task.course.name, "total": task.total_count, "type_counts": counts, "quality_mode": workflow.quality_mode, "batch_size": config.get("batch_size", get_config()["batch_size"])}
        create_artifact(workflow, "EXECUTION_PLAN", "supervisor", plan)
        return {"plan": plan, "task_id": task.id, "revision_round": int(state.get("revision_round", 0)), "max_revisions": int(state.get("max_revisions", 1))}

    @staticmethod
    def _retrieve(workflow, state):
        task = GenerationTask.objects.select_related("course").get(pk=workflow.business_id)
        config = {**get_config(), **task.config}
        from apps.questions.services import resolve_subject_style
        config["resolved_subject_style"] = resolve_subject_style(config, task.course)
        queries = generation_topic_queries(config, task.course.name, task.course.grade)
        limit = min(50, max(int(config.get("retrieval_top_k", 5)), task.total_count, len(queries) * 3))
        evidence = HybridRetrievalService().retrieve(queries, {"course_id": task.course_id, "file_id": config.get("file_id"), "chapter_id": config.get("chapter_id")}, limit, float(config.get("similarity_threshold", 0.25)))
        if not evidence:
            raise BusinessError("没有检索到可支持出题的知识库内容，请先完成文件解析或放宽检索条件。", 40042)
        task.retrieved_chunks = evidence
        task.save(update_fields=["retrieved_chunks"])
        create_artifact(workflow, "EVIDENCE_PACK", "retrieval_planner", {"queries": queries, "chunk_ids": [item["chunk_id"] for item in evidence], "sources": [{"file_name": item.get("file_name"), "page_number": item.get("page_number"), "match_type": item.get("matches", [])} for item in evidence]})
        return {"evidence_count": len(evidence)}

    @staticmethod
    def _author(workflow, state):
        task = GenerationTask.objects.get(pk=workflow.business_id)
        GenerationService().run(task)
        task.refresh_from_db()
        ids = list(task.questions.filter(is_deleted=False).values_list("id", flat=True))
        create_artifact(workflow, "QUESTION_DRAFT", "question_author", {"question_ids": ids, "success_count": len(ids), "failed_count": task.failed_count})
        if task.status != "SUCCESS":
            raise BusinessError(task.error_message or "命题智能体未生成合格题目。", 50271, 502)
        return {"question_ids": ids}

    def _review(self, workflow, state):
        question_ids = state.get("question_ids") or list(Question.objects.filter(generation_task_id=workflow.business_id, is_deleted=False).values_list("id", flat=True))
        questions = list(Question.objects.filter(id__in=question_ids).prefetch_related("options"))
        chunk_ids = sorted({chunk_id for question in questions for chunk_id in (question.source_chunk_ids or [])})
        chunks = {item.id: item.content for item in TextChunk.objects.filter(id__in=chunk_ids)}
        payload = []
        solver_payload = []
        for question in questions:
            evidence = [chunks.get(int(chunk_id), "") for chunk_id in question.source_chunk_ids if str(chunk_id).isdigit()]
            snapshot = snapshot_question(question)
            payload.append({"question_id": question.id, "question": snapshot, "evidence": evidence})
            solver_payload.append({
                "question_id": question.id,
                "question": {
                    "question_type": snapshot["question_type"],
                    "stem": snapshot["stem"],
                    "options": snapshot["options"],
                    "difficulty": snapshot["difficulty"],
                },
                "evidence": evidence,
            })
        solution_schema = {"type": "object", "properties": {"solutions": {"type": "array", "items": {"type": "object", "properties": {"question_id": {"type": "integer"}, "answer": {"type": "array", "minItems": 1, "items": {"type": "string"}}, "reasoning": {"type": "string"}, "confidence": {"type": "number"}}, "required": ["question_id", "answer", "reasoning", "confidence"]}}}, "required": ["solutions"]}
        schema = {"type": "object", "properties": {"reviews": {"type": "array", "items": {"type": "object", "properties": {"question_id": {"type": "integer"}, "passed": {"type": "boolean"}, "score": {"type": "number"}, "grounding_score": {"type": "number"}, "issues": {"type": "array", "items": {"type": "string"}}, "suggestions": {"type": "array", "items": {"type": "string"}}}, "required": ["question_id", "passed", "score", "grounding_score", "issues", "suggestions"]}}}, "required": ["reviews"]}
        system = get_prompt("question_review", "严格根据知识库证据审核题目，输出JSON。") + "\n请先独立作答，再核对原答案和解析。只有得分不低于80且忠实度不低于0.75才能passed=true。"
        review_config = get_agent_config("answer_reviewer")
        model_name = review_config["model"]
        pass_score = float(review_config.get("pass_score", 80))
        grounding_threshold = float(review_config.get("grounding_threshold", 0.75))
        started = time.monotonic()
        solver_system = "你是独立解题员。你看不到命题者的答案和解析，必须从题干、选项和知识证据重新作答。选择题answer只写选项字母；其他题写明确结果。不要猜测原答案。输出严格JSON。"
        solver_result = OllamaService().chat_json([{"role": "system", "content": solver_system}, {"role": "user", "content": json.dumps({"items": solver_payload}, ensure_ascii=False)}], model_name, "agent_independent_solver", solution_schema)
        solutions_by_id = {int(item.get("question_id")): item for item in solver_result.get("solutions", []) if item.get("question_id")}
        for item in payload:
            item["independent_solution"] = solutions_by_id.get(item["question_id"], {})
        result = OllamaService().chat_json([{"role": "system", "content": system}, {"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)}], model_name, "agent_answer_review", schema)
        by_id = {int(item.get("question_id")): item for item in result.get("reviews", []) if item.get("question_id")}
        failed = []
        hard_consistency_types = {"single_choice", "multiple_choice", "judge", "fill_blank", "calculation"}
        for question in questions:
            item = by_id.get(question.id, {"passed": False, "score": 0, "grounding_score": 0, "issues": ["审核智能体未返回该题结果"], "suggestions": []})
            score, grounding = float(item.get("score", 0)), float(item.get("grounding_score", 0))
            solution = solutions_by_id.get(question.id, {})
            independent_answer = solution.get("answer", [])
            consistent = independent_answers_consistent(question.question_type, question.answer, independent_answer)
            consistency_required = question.question_type in hard_consistency_types
            consistency_issues = [] if (consistent or not consistency_required) else ["独立解题答案与命题答案不一致"]
            QuestionReview.objects.create(
                question=question,
                review_type="INDEPENDENT_ANSWER",
                passed=consistent if consistency_required else bool(independent_answer),
                score=100 if consistent else (70 if independent_answer and not consistency_required else 0),
                issues=consistency_issues,
                suggestions=[str(solution.get("reasoning", ""))] if solution.get("reasoning") else [],
                model_name=model_name,
            )
            item["issues"] = list(item.get("issues", [])) + consistency_issues
            passed = bool(item.get("passed")) and score >= pass_score and grounding >= grounding_threshold
            if consistency_required and not consistent:
                passed = False
                score = min(score, 60)
            QuestionReview.objects.create(question=question, review_type="AGENT", passed=passed, score=score, issues=item.get("issues", []), suggestions=item.get("suggestions", []), model_name=model_name)
            question.ai_review_score = score
            question.grounding_score = grounding
            question.review_status = "PENDING" if passed else "NEEDS_REVISION"
            question.save(update_fields=["ai_review_score", "grounding_score", "review_status", "updated_at"])
            if not passed:
                failed.append(question.id)
        AgentMetric.objects.create(workflow=workflow, agent_key="answer_reviewer", model_name=model_name, call_count=2, duration_ms=int((time.monotonic() - started) * 1000), input_chars=len(json.dumps(solver_payload, ensure_ascii=False)) + len(json.dumps(payload, ensure_ascii=False)), output_chars=len(json.dumps(solver_result, ensure_ascii=False)) + len(json.dumps(result, ensure_ascii=False)), success=True, rework_count=len(failed))
        create_artifact(workflow, "REVIEW_REPORT", "answer_reviewer", {"failed_question_ids": failed, "reviewed_count": len(questions)})
        return {"question_ids": question_ids, "failed_review_ids": failed, "revision_round": int(state.get("revision_round", 0)), "max_revisions": int(state.get("max_revisions", 1))}

    @staticmethod
    def _after_review(state):
        if state.get("failed_review_ids") and int(state.get("revision_round", 0)) < int(state.get("max_revisions", 1)):
            return "revise"
        return "rules"

    def _revise(self, workflow, state):
        failed_ids = state.get("failed_review_ids") or []
        questions = list(Question.objects.filter(id__in=failed_ids).prefetch_related("options", "reviews"))
        revised_ids = []
        for question in questions:
            self._check_cancel(workflow)
            context = "\n\n".join(TextChunk.objects.filter(id__in=question.source_chunk_ids).values_list("content", flat=True))[:get_config()["max_context_chars"]]
            latest = question.reviews.order_by("-created_at").first()
            prompt = {"current_question": snapshot_question(question), "issues": latest.issues if latest else [], "suggestions": latest.suggestions if latest else [], "knowledge_context": context, "instruction": "只修改审核指出的问题，保留原题型，不得增加证据外的知识。"}
            result = OllamaService().chat_json([{"role": "system", "content": get_prompt("question_generation", "严格根据证据修订题目。")}, {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}], get_agent_config("question_reviser")["model"], "agent_question_revision", question_batch_schema(question.question_type, 1))
            candidates = result.get("questions", [])
            if candidates and self._apply_revision(question, candidates[0]):
                revised_ids.append(question.id)
        round_number = int(state.get("revision_round", 0)) + 1
        create_artifact(workflow, "REVISION_REPORT", "question_reviser", {"revision_round": round_number, "requested_ids": failed_ids, "revised_ids": revised_ids})
        return {"question_ids": state.get("question_ids", []), "failed_review_ids": revised_ids or failed_ids, "revision_round": round_number, "max_revisions": int(state.get("max_revisions", 1))}

    @staticmethod
    @transaction.atomic
    def _apply_revision(question, raw):
        data = normalize_generated_question(raw)
        data["type"] = question.question_type
        data.setdefault("source_chunk_ids", question.source_chunk_ids)
        data.setdefault("source_summary", question.source_summary)
        issues = validate_question_structure(data)
        if issues:
            return False
        question.stem = str(data["stem"]).strip()
        question.answer = data.get("answer", [])
        question.analysis = data.get("analysis", "")
        question.scoring_points = data.get("scoring_points", [])
        question.difficulty = data.get("difficulty", question.difficulty)
        question.source_summary = data.get("source_summary", question.source_summary)
        question.source_chunk_ids = data.get("source_chunk_ids", question.source_chunk_ids)
        question.content_hash = question_hash(question.stem)
        question.review_status = "PENDING"
        question.save()
        question.options.all().delete()
        answers = {str(item).upper() for item in question.answer}
        QuestionOption.objects.bulk_create([QuestionOption(question=question, label=str(item["label"]).upper(), content=item["content"], is_correct=str(item["label"]).upper() in answers, sort_order=index) for index, item in enumerate(data.get("options", []))])
        return True

    def _rules(self, workflow, state):
        ids = state.get("question_ids") or list(Question.objects.filter(generation_task_id=workflow.business_id, is_deleted=False).values_list("id", flat=True))
        failures = {}
        questions = list(Question.objects.filter(id__in=ids).prefetch_related("options"))
        for question in questions:
            data = snapshot_question(question)
            data["type"] = question.question_type
            data["_requested_difficulty"] = question.difficulty
            issues = validate_question_structure(data)
            duplicates = []
            duplicate = find_generation_duplicate(
                question.stem,
                question.course_id,
                question.question_type,
                threshold=0.92,
                template_threshold=0.96,
                exclude_id=question.id,
            )
            if duplicate:
                duplicates.append(duplicate)
            if not question.source_chunk_ids:
                issues.append("缺少知识库来源")
            if duplicates:
                issues.append("与已有题目过于接近，只有措辞或数字变化")
            if issues:
                failures[str(question.id)] = {"issues": issues, "duplicates": duplicates}
                question.review_status = "NEEDS_REVISION"
                question.save(update_fields=["review_status", "updated_at"])
            QuestionReview.objects.create(question=question, review_type="AGENT_RULE", passed=not issues, score=max(0, 100 - 15 * len(issues)), issues=issues, suggestions=[])
        report = {"failures": failures, "checked_count": len(ids), "duplicate_policy": "允许同知识点变式；拦截只换措辞或只换数字的同模板题"}
        create_artifact(workflow, "RULE_REPORT", "rule_similarity", report)
        return {"question_ids": ids, "rule_failures": failures}

    @staticmethod
    def _semantic_duplicate_matches(questions):
        """用当前配置的 Embedding 模型检测语义近似；模型不可用时保留规则审核结果。"""
        if not questions:
            return {}, ""
        from langchain_ollama import OllamaEmbeddings

        course_ids = {question.course_id for question in questions}
        candidate_qs = Question.objects.filter(course_id__in=course_ids, is_deleted=False).exclude(
            id__in=[question.id for question in questions]
        ).only("id", "course_id", "question_type", "stem").order_by("-created_at")[:500]
        candidates = list(candidate_qs)
        if not candidates:
            return {}, ""
        all_items = questions + candidates
        try:
            config = get_config()
            vectors = np.asarray(
                OllamaEmbeddings(
                    model=get_agent_config("rule_similarity")["model"],
                    base_url=config["ollama_base_url"],
                ).embed_documents([item.stem for item in all_items]),
                dtype=float,
            )
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            normalized = vectors / np.maximum(norms, 1e-12)
            threshold = float(config["duplicate_threshold"])
            matches = {}
            question_count = len(questions)
            for index, question in enumerate(questions):
                allowed = [
                    offset for offset, candidate in enumerate(candidates)
                    if candidate.course_id == question.course_id and candidate.question_type == question.question_type
                ]
                if not allowed:
                    continue
                similarities = normalized[index] @ normalized[question_count:][allowed].T
                best_local = int(np.argmax(similarities))
                score = float(similarities[best_local])
                if score >= threshold:
                    candidate = candidates[allowed[best_local]]
                    matches[question.id] = {"question_id": candidate.id, "similarity": round(score, 4), "match_type": "SEMANTIC"}
            return matches, ""
        except Exception as exc:
            logger.warning("语义相似题检测跳过：%s", exc)
            return {}, f"Embedding模型暂时不可用：{exc}"

    @staticmethod
    def _finalize_questions(workflow, state):
        ids = state.get("question_ids", [])
        questions = Question.objects.filter(id__in=ids, is_deleted=False)
        pending_ids = list(questions.filter(review_status="PENDING").values_list("id", flat=True))
        revision_ids = list(questions.filter(review_status="NEEDS_REVISION").values_list("id", flat=True))
        result = {"question_ids": ids, "pending_ids": pending_ids, "needs_revision_ids": revision_ids, "rule_failures": state.get("rule_failures", {})}
        workflow.result = result
        workflow.status = "AWAITING_REVIEW" if ids else "FAILED"
        workflow.progress = 100 if ids else workflow.progress
        workflow.current_agent = "quality_reviewer"
        workflow.finished_at = timezone.now()
        workflow.save()
        create_artifact(workflow, "FINAL_REPORT", "quality_reviewer", result)
        return {"result": result}

    @staticmethod
    def _paper_plan(workflow, state):
        from apps.papers.services import parse_natural_rule
        started = time.monotonic()
        rule = parse_natural_rule(workflow.input_data["text"], workflow.input_data.get("course_id"))
        AgentMetric.objects.create(workflow=workflow, agent_key="paper_planner", model_name=get_config()["chat_model"], call_count=1, duration_ms=int((time.monotonic() - started) * 1000), input_chars=len(workflow.input_data["text"]), output_chars=len(json.dumps(rule, ensure_ascii=False)))
        create_artifact(workflow, "PAPER_RULE", "paper_planner", rule)
        return {"result": rule}

    @staticmethod
    def _paper_validate(workflow, state):
        from apps.papers.services import normalize_paper_rule
        rule = normalize_paper_rule(state.get("result") or {})
        rule.pop("duration", None)
        rule.pop("exam_time", None)
        rule["paper_type"] = "AI辅助组卷"
        workflow.result = rule
        workflow.status = "AWAITING_REVIEW"
        workflow.progress = 100
        workflow.current_agent = "supervisor"
        workflow.finished_at = timezone.now()
        workflow.save()
        create_artifact(workflow, "VALIDATED_PAPER_RULE", "supervisor", rule)
        return {"result": rule}

    @staticmethod
    def _knowledge_curate(workflow, state):
        from apps.knowledge.models import KnowledgeFile
        knowledge_file = KnowledgeFile.objects.get(pk=workflow.business_id)
        context = "\n\n".join(knowledge_file.chunks.order_by("chunk_index").values_list("content", flat=True)[:40])[:get_config()["max_context_chars"]]
        schema = {"type": "object", "properties": {"chapters": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "number": {"type": "string"}, "description": {"type": "string"}}, "required": ["name", "number", "description"]}}, "knowledge_points": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}}, "importance": {"type": "string", "enum": ["一般", "重要", "核心"]}, "difficulty": {"type": "string"}, "chapter_name": {"type": "string"}, "source_summary": {"type": "string"}}, "required": ["name", "description", "keywords", "importance", "difficulty", "chapter_name", "source_summary"]}}}, "required": ["chapters", "knowledge_points"]}
        instruction = {"file_name": knowledge_file.original_name, "extract_chapters": workflow.input_data.get("auto_chapter"), "extract_knowledge_points": workflow.input_data.get("auto_knowledge"), "content": context}
        result = OllamaService().chat_json([{"role": "system", "content": get_prompt("knowledge_point", "根据资料识别章节和可命题知识点，输出JSON。")}, {"role": "user", "content": json.dumps(instruction, ensure_ascii=False)}], get_agent_config("knowledge_curator")["model"], "agent_knowledge_curation", schema)
        if not workflow.input_data.get("auto_chapter"): result["chapters"] = []
        if not workflow.input_data.get("auto_knowledge"): result["knowledge_points"] = []
        create_artifact(workflow, "KNOWLEDGE_PREVIEW", "knowledge_curator", result)
        return {"result": result}

    @staticmethod
    def _knowledge_finalize(workflow, state):
        from apps.system_settings.models import AITaskResult
        preview = AITaskResult.objects.create(task_type="KNOWLEDGE_CURATION", input_config=workflow.input_data, result_json=state.get("result") or {})
        workflow.result = {"preview_id": preview.id, **(state.get("result") or {})}
        workflow.status = "AWAITING_REVIEW"; workflow.progress = 100; workflow.current_agent = "supervisor"; workflow.finished_at = timezone.now(); workflow.save()
        return {"result": workflow.result}

    @staticmethod
    def _cancel(workflow):
        workflow.status = "CANCELLED"
        workflow.finished_at = timezone.now()
        workflow.save()
        if workflow.business_type == "generation_task" and workflow.business_id:
            GenerationTask.objects.filter(pk=workflow.business_id).update(cancel_requested=True, status="CANCELLED", finished_at=timezone.now())


def retry_workflow(workflow):
    if workflow.status not in {"FAILED", "CANCELLED", "INTERRUPTED"}:
        raise BusinessError("只有失败、取消或中断的智能体任务可以重试。", 40931, 409)
    workflow.status = "WAITING"
    workflow.progress = 0
    workflow.current_agent = ""
    workflow.cancel_requested = False
    workflow.error_message = ""
    workflow.finished_at = None
    workflow.retry_count += 1
    workflow.thread_id = str(uuid.uuid4())
    workflow.save()
    if workflow.business_type == "generation_task" and workflow.business_id:
        task = GenerationTask.objects.get(pk=workflow.business_id)
        task.status = "WAITING"
        task.cancel_requested = False
        task.error_message = ""
        task.finished_at = None
        task.save()
    return workflow


def record_paper_selection_workflow(paper, shortages):
    """记录确定性选题智能体的执行轨迹，不重复调用大模型。"""
    ensure_agent_definitions()
    workflow = AgentWorkflowRun.objects.create(
        workflow_type="PAPER_SELECTION", business_type="paper", business_id=paper.id,
        status="SUCCESS", priority=80, progress=100, current_agent="paper_selector",
        quality_mode="STANDARD", thread_id=str(uuid.uuid4()), input_data=paper.config,
        result={"paper_id": paper.id, "question_count": paper.paper_questions.count(), "shortages": shortages},
        started_at=timezone.now(), finished_at=timezone.now(),
    )
    now = timezone.now()
    AgentStepRun.objects.bulk_create([
        AgentStepRun(workflow=workflow, agent_key="supervisor", step_name="校验组卷约束", status="SUCCESS", input_summary={"target_score": float(paper.target_score)}, output_summary={"valid": True}, started_at=now, finished_at=now),
        AgentStepRun(workflow=workflow, agent_key="paper_selector", step_name="按覆盖率和难度选题", status="SUCCESS", input_summary={"rule_count": len(paper.config.get("type_config", []))}, output_summary={"question_count": paper.paper_questions.count(), "shortage_count": len(shortages)}, started_at=now, finished_at=now),
    ])
    create_artifact(workflow, "PAPER_SELECTION_REPORT", "paper_selector", workflow.result)
    return workflow


def record_paper_quality_workflow(paper, report):
    workflow = AgentWorkflowRun.objects.create(
        workflow_type="PAPER_QUALITY", business_type="paper", business_id=paper.id,
        status="SUCCESS", priority=70, progress=100, current_agent="paper_evaluator",
        quality_mode="STANDARD", thread_id=str(uuid.uuid4()), input_data={"paper_id": paper.id}, result=report,
        started_at=timezone.now(), finished_at=timezone.now(),
    )
    AgentStepRun.objects.create(workflow=workflow, agent_key="paper_evaluator", step_name="评估试卷结构与覆盖率", status="SUCCESS", input_summary={"question_count": paper.paper_questions.count()}, output_summary={"quality_score": report.get("total_score"), "issue_count": len(report.get("issues", []))}, started_at=timezone.now(), finished_at=timezone.now())
    create_artifact(workflow, "PAPER_QUALITY_REPORT", "paper_evaluator", report)
    return workflow
