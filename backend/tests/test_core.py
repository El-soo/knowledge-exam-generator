import hashlib
import io
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from apps.ai_service.services import OllamaService
from apps.courses.models import Course
from apps.knowledge.models import KnowledgeFile, ParseTask, TextChunk
from apps.knowledge.services import DocxParser, FileParseService, TaskYield, TextCleaner, VectorService, is_meaningful_chunk, normalize_pdf_text, split_text
from apps.questions.models import GenerationTask, Question
from apps.questions.services import (
    GenerationService,
    build_course_question_blueprint,
    candidate_quality_score,
    create_question,
    distribute_question_types,
    difficulty_quality_issues,
    find_generation_duplicate,
    find_similar,
    focused_generation_context,
    generation_batch_budget,
    generation_correction_instruction,
    generation_topic_queries,
    is_high_school_math_course,
    independent_answers_consistent,
    next_type_batch,
    normalize_generated_question,
    question_batch_schema,
    question_hash,
    rank_generation_candidates,
    repair_latex_escapes,
    resembles_source_exercise,
    rotating_context,
    select_course_topic,
    snapshot_question,
    strip_embedded_choice_options,
    symbolic_answers_equivalent,
    subject_instruction_for,
    validate_question_structure,
)
from apps.papers.models import Paper, PaperSection, PaperQuestion
from apps.papers.services import (
    ExportService,
    coverage_aware_selection,
    find_similar_question_in_paper,
    normalize_paper_rule,
    recalculate_paper,
    rule_generate,
    section_display_title,
    section_score_summary,
)

QUESTION_DATA = {"type":"single_choice", "stem":"Python中用于定义函数的关键字是？", "options":[{"label":"A","content":"class"},{"label":"B","content":"def"},{"label":"C","content":"import"},{"label":"D","content":"return"}], "answer":["B"], "analysis":"使用def定义函数。", "difficulty":"简单", "score":2, "scoring_points":[]}

class CourseApiTests(TestCase):
    def setUp(self): self.client = APIClient()
    def test_course_create_uses_uniform_response(self):
        response = self.client.post("/api/v1/courses/", {"name":"Python程序设计", "code":"PY101"}, format="json")
        self.assertEqual(response.status_code, 201)
        body = response.json(); self.assertEqual(body["code"], 0); self.assertEqual(body["message"], "success"); self.assertIn("request_id", body); self.assertEqual(body["data"]["name"], "Python程序设计")
    def test_course_name_is_required(self):
        response = self.client.post("/api/v1/courses/", {"name":""}, format="json")
        self.assertEqual(response.status_code, 400); self.assertNotEqual(response.json()["code"], 0)

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UploadTests(TestCase):
    def setUp(self): self.client = APIClient(); self.course = Course.objects.create(name="文件测试")
    def test_txt_upload_creates_database_task(self):
        file = SimpleUploadedFile("lesson.txt", "第一章 Python基础".encode(), content_type="text/plain")
        response = self.client.post("/api/v1/knowledge/files/upload/", {"course":self.course.id, "files":[file], "chunk_size":800, "chunk_overlap":120}, format="multipart")
        self.assertEqual(response.status_code, 200); self.assertEqual(KnowledgeFile.objects.count(), 1); self.assertEqual(ParseTask.objects.count(), 1); self.assertEqual(response.json()["data"][0]["status"], "WAITING")
    def test_same_content_is_reported_as_duplicate(self):
        payload = b"same content"
        for _ in range(2):
            file = SimpleUploadedFile("lesson.txt", payload, content_type="text/plain")
            response = self.client.post("/api/v1/knowledge/files/upload/", {"course":self.course.id, "files":[file]}, format="multipart")
        self.assertEqual(KnowledgeFile.objects.count(), 1); self.assertEqual(response.json()["data"][0]["status"], "DUPLICATE")
    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=0)
    def test_disk_backed_temporary_upload_is_supported(self):
        file = SimpleUploadedFile("disk-backed.txt", b"temporary upload", content_type="text/plain")
        response = self.client.post(
            "/api/v1/knowledge/files/upload/",
            {"course": self.course.id, "files": [file]},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"][0]["status"], "WAITING")
        self.assertEqual(KnowledgeFile.objects.count(), 1)

class TextProcessingTests(TestCase):
    def test_pdf_text_normalizes_gbk_math_fonts_and_symbols(self):
        source = "函数犳（狓）=狓，犖、犣、犙、犚；∀前\ue02f后\ue055，狓\ue05b犃，\ue07e。状态独立。"
        normalized = normalize_pdf_text(source)
        self.assertEqual(normalized, "函数f（x）=x，N、Z、Q、R；∀前∀后∃，x∉A，∅。状态独立。")

    def test_pdf_text_normalizes_structure_symbols_and_removes_decorations(self):
        source = "1\ue0102\ue0113，A\ue020B，p\ue03cq，a\ue039b，\u13e6"
        self.assertEqual(normalize_pdf_text(source), "1.2-3，A⊆B，p⇒q，a⇔b，")

    def test_docx_parser_ignores_missing_image_relationship(self):
        document_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:p><w:r><w:t>可正常提取的正文</w:t></w:r></w:p></w:body>
        </w:document>'''.encode("utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "missing-image.docx"
            with zipfile.ZipFile(file_path, "w") as package:
                package.writestr("word/document.xml", document_xml)
                package.writestr(
                    "word/_rels/document.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../NULL"/>'
                    '</Relationships>',
                )
                package.writestr(
                    "[Content_Types].xml",
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                    '</Types>',
                )
                package.writestr(
                    "_rels/.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                    '</Relationships>',
                )
            parsed = DocxParser().parse(file_path)
        self.assertIn("可正常提取的正文", parsed[0]["text"])

    def test_cleaner_removes_page_number_controls_and_duplicate_paragraph(self):
        source = "\x00# 第一章\n\n第 3 页\n重复的长段落用于测试文本去重功能。\n重复的长段落用于测试文本去重功能。"
        cleaned = TextCleaner.clean(source)
        self.assertNotIn("第 3 页", cleaned); self.assertNotIn("\x00", cleaned); self.assertEqual(cleaned.count("重复的长段落"), 1); self.assertIn("第一章", cleaned)
    def test_cleaner_removes_markdown_images_and_base64_payloads(self):
        payload = "A" * 180
        cleaned = TextCleaner.clean(f"CNN通过卷积核提取局部特征。\n![](../assets/cnn.png)\n{payload}")
        self.assertEqual(cleaned, "CNN通过卷积核提取局部特征。")
    def test_generation_chunk_filter_rejects_binary_and_index_noise(self):
        self.assertFalse(is_meaningful_chunk("A" * 300))
        self.assertFalse(is_meaningful_chunk("![](../assets/a.png)\n![](../assets/b.png)"))
        self.assertFalse(is_meaningful_chunk("term, 12, 15, 18, 20, 22, 25, 27, 29, 31, 34"))
        self.assertTrue(is_meaningful_chunk("CNN通过可学习的卷积核提取局部特征，并通过多层结构逐步组合成更高层的语义表示。"))
    def test_splitter_respects_length_and_overlap(self):
        chunks = split_text("甲" * 700 + "。" + "乙" * 700, 800, 120)
        self.assertGreaterEqual(len(chunks), 2); self.assertTrue(all(len(x) <= 800 for x in chunks))
    def test_splitter_rejects_overlap_equal_to_chunk_size(self):
        with self.assertRaises(ValueError): split_text("内容", 800, 800)
    def test_sha256_question_hash_is_whitespace_insensitive(self):
        self.assertEqual(question_hash("A B\nC"), question_hash("abc"))
    def test_question_hash_ignores_punctuation_and_blank_underscores(self):
        self.assertEqual(
            question_hash("Agent调用工具，本质上是调用______。"),
            question_hash("Agent 调用工具本质上是调用？"),
        )
    def test_generation_context_rotates_across_retrieved_chunks(self):
        retrieved = [{"chunk_id": index, "content": f"片段{index}"} for index in range(1, 11)]
        self.assertEqual([item["chunk_id"] for item in rotating_context(retrieved, 0, 1000, 4)], [1, 2, 3, 4])
        self.assertEqual([item["chunk_id"] for item in rotating_context(retrieved, 1, 1000, 4)], [5, 6, 7, 8])
        self.assertEqual([item["chunk_id"] for item in rotating_context(retrieved, 2, 1000, 4)], [9, 10, 1, 2])

    def test_course_topic_quota_rotates_and_skips_repeated_topic(self):
        plans = [{"topic": "函数"}, {"topic": "面向对象"}, {"topic": "异常处理"}]
        progress = {"single_choice": {"函数": 2, "面向对象": 1, "异常处理": 1}}
        failures = {"single_choice": {"面向对象": 3, "异常处理": 0}}
        topic, quota = select_course_topic(plans, "single_choice", 6, progress, failures, 4)
        self.assertEqual(quota, 2)
        self.assertEqual(topic, "异常处理")

    def test_focused_context_can_switch_to_preferred_course_topic(self):
        retrieved = [
            {"chunk_id": 1, "retrieval_query": "函数 参数 返回值", "content": "函数片段"},
            {"chunk_id": 2, "retrieval_query": "异常处理 try except", "content": "异常片段"},
        ]
        selected, topic, round_number = focused_generation_context(
            retrieved, 0, 1000, preferred_topic="异常处理", preferred_round=2,
        )
        self.assertEqual([item["chunk_id"] for item in selected], [2])
        self.assertEqual(topic, "异常处理")
        self.assertEqual(round_number, 2)
    def test_generation_supplement_is_split_into_topic_queries(self):
        queries = generation_topic_queries(
            {"supplement": "需要【Python、PyTorch、CNN\n回归、SVM、PCA】的相关选择题"},
            "人工智能",
        )
        self.assertEqual(queries, ["Python", "PyTorch", "CNN", "回归", "SVM", "PCA"])

    def test_high_school_math_course_uses_example_and_exercise_queries(self):
        self.assertTrue(is_high_school_math_course("普通高中数学必修第一册"))
        queries = generation_topic_queries(
            {"subject_style": "auto", "supplement": "函数的单调性"},
            "高中数学",
            "高一",
        )
        self.assertEqual(queries, ["函数的单调性 典型例题 求解 证明", "函数的单调性 练习题 计算 解答"])

    def test_high_school_math_rejects_definition_only_question(self):
        data = {
            **QUESTION_DATA,
            "stem": "什么是函数的单调性？",
            "_subject_style": "high_school_math",
        }
        self.assertTrue(any("不能只考查概念或定义" in issue for issue in validate_question_structure(data)))

    def test_high_school_math_requires_unified_latex_delimiters(self):
        data = {
            **QUESTION_DATA,
            "stem": "已知函数f(x)=x²-2x，则f(x)在区间[0,2]上的最小值为（ ）。",
            "_subject_style": "high_school_math",
        }
        self.assertTrue(any("数学表达式必须统一" in issue for issue in validate_question_structure(data)))
        data["stem"] = r"已知函数 \(f(x)=x^2-2x\)，则 \(f(x)\) 在区间 \([0,2]\) 上的最小值为（ ）。"
        self.assertEqual(validate_question_structure(data), [])

    def test_medium_difficulty_rejects_one_step_math_and_accepts_parameter_problem(self):
        shallow = {
            **QUESTION_DATA,
            "stem": r"已知函数 \(f(x)=x^2-4x+3\) 在区间 \([0,3]\) 上的最小值为多少？",
            "_subject_style": "high_school_math",
            "_requested_difficulty": "中等",
        }
        complex_problem = {
            **QUESTION_DATA,
            "stem": r"已知函数 \(f(x)=x^2-2ax+1\)，若对任意 \(x\in[0,2]\) 恒有 \(f(x)\ge0\)，且函数在该区间存在唯一零点，求参数 \(a\) 的取值范围并说明理由。",
            "_subject_style": "high_school_math",
            "_requested_difficulty": "中等",
        }
        self.assertTrue(any("未达到中等题" in issue for issue in difficulty_quality_issues(shallow)))
        self.assertEqual(difficulty_quality_issues(complex_problem), [])

    def test_general_subject_difficulty_uses_options_and_exempts_intrinsic_types(self):
        applied_choice = {
            **QUESTION_DATA,
            "stem": "运行下面的函数后发现结果与需求不符，结合参数传递规则判断最合理的修正方案。",
            "options": [
                {"label": "A", "content": "删除返回语句，让函数直接修改所有外部变量"},
                {"label": "B", "content": "检查可变对象的修改位置，并显式返回需要保留的计算结果"},
                {"label": "C", "content": "把每个局部变量都改成同名全局变量"},
                {"label": "D", "content": "只增加一次打印输出，不调整参数和返回值"},
            ],
            "_subject_style": "exam_oriented",
            "_requested_difficulty": "中等",
        }
        term = {
            **QUESTION_DATA,
            "type": "term_explanation",
            "stem": "解释封装的含义。",
            "options": [],
            "answer": ["封装是隐藏对象内部实现并通过明确接口控制访问的机制。"],
            "_subject_style": "exam_oriented",
            "_requested_difficulty": "中等",
        }
        self.assertEqual(difficulty_quality_issues(applied_choice), [])
        self.assertEqual(difficulty_quality_issues(term), [])

    def test_general_exam_mode_retrieves_examples_cases_and_practice(self):
        queries = generation_topic_queries(
            {"resolved_subject_style": "exam_oriented", "supplement": "Python函数"},
            "Python程序设计",
            "本科",
        )
        self.assertEqual(queries, ["Python函数 典型例题 案例 应用", "Python函数 练习题 分析 推理 实践"])

    def test_programming_course_receives_code_exam_instruction(self):
        course = SimpleNamespace(name="Python程序设计", grade="本科", description="程序设计基础", major="计算机")
        instruction = subject_instruction_for(course, "exam_oriented")
        self.assertIn("代码阅读", instruction)
        self.assertIn("调试纠错", instruction)

    def test_other_subject_families_receive_matching_exam_instructions(self):
        language = SimpleNamespace(name="高中英语", grade="高中", description="阅读与写作", major="")
        medical = SimpleNamespace(name="基础护理学", grade="本科", description="临床护理", major="护理")
        practical = SimpleNamespace(name="汽车维修实训", grade="职业教育", description="故障排查", major="汽车维修")
        self.assertIn("阅读理解", subject_instruction_for(language, "exam_oriented"))
        self.assertIn("病例", subject_instruction_for(medical, "exam_oriented"))
        self.assertIn("故障排查", subject_instruction_for(practical, "exam_oriented"))

    @patch("apps.questions.services.OllamaService.chat_json")
    def test_each_course_builds_its_own_question_blueprint(self, chat_json):
        chat_json.return_value = {
            "course_identity": "Python课程设计",
            "learning_goals": ["编写程序", "调试程序"],
            "topic_plans": [
                {"topic": f"主题{index}", "knowledge_scope": f"知识{index}", "question_approaches": ["代码阅读", "调试纠错"]}
                for index in range(1, 7)
            ],
        }
        course = SimpleNamespace(id=9, name="Python课程设计", grade="本科", major="计算机", description="项目实践")
        blueprint = build_course_question_blueprint(
            course,
            [{"chunk_id": 1, "file_name": "课程.md", "content": "函数、类和异常处理的项目实践。"}],
            {"count": 20, "chat_model": "qwen2.5:7b"},
        )
        self.assertEqual(blueprint["course_identity"], "Python课程设计")
        self.assertEqual(len(blueprint["topic_plans"]), 6)
        prompt = chat_json.call_args.args[0][1]["content"]
        self.assertIn("Python课程设计", prompt)
        self.assertIn("函数、类和异常处理", prompt)

    def test_general_exam_mode_rejects_definition_only_choice(self):
        data = {
            **QUESTION_DATA,
            "stem": "什么是Python函数？",
            "_subject_style": "exam_oriented",
        }
        self.assertTrue(any("不能只考查概念或定义" in issue for issue in validate_question_structure(data)))

    def test_generated_choice_removes_options_repeated_in_stem(self):
        options = [
            {"label": "A", "content": "10"}, {"label": "B", "content": "12"},
            {"label": "C", "content": "14"}, {"label": "D", "content": "16"},
        ]
        stem = "若正数x和y满足xy=25，则x+y的最小值为： A. 10 B. 12 C. 14 D. 16"
        self.assertEqual(strip_embedded_choice_options(stem, options), "若正数x和y满足xy=25，则x+y的最小值为")
        normalized = normalize_generated_question({"type": "single_choice", "stem": stem, "options": options, "answer": ["A"]})
        self.assertEqual(normalized["stem"], "若正数x和y满足xy=25，则x+y的最小值为")

        bracket_stem = "若正数x和y满足xy=25，则x+y的最小值为：（A）10 （B）12 （C）14 （D）16"
        self.assertEqual(strip_embedded_choice_options(bracket_stem, options), "若正数x和y满足xy=25，则x+y的最小值为")

    def test_broken_json_latex_escape_is_repaired(self):
        self.assertEqual(repair_latex_escapes("求$x+\x0crac{1}{x}$的最小值"), r"求$x+\frac{1}{x}$的最小值")
        self.assertEqual(repair_latex_escapes("已知\tan(70°)的值"), r"已知\tan(70°)的值")

    def test_fill_blank_placeholder_is_normalized(self):
        normalized = normalize_generated_question({
            "type": "fill_blank",
            "stem": r"已知数列 \(a_n\) 满足递推关系，当 \(n=\underline{\hspace{1cm}}\) 时成立。",
            "answer": ["4"],
        })
        self.assertEqual(normalized["stem"], r"已知数列 \(a_n\) 满足递推关系，当 \(n\) = ________ 时成立。")

    def test_raw_math_is_normalized_before_validation(self):
        normalized = normalize_generated_question({
            **QUESTION_DATA,
            "stem": "已知函数f(x) = x^2 - 3x + 2，在区间[0, 3]上的最大值是（　　）。",
            "_subject_style": "high_school_math",
        })
        self.assertIn(r"\(f(x) = x^2 - 3x + 2\)", normalized["stem"])
        self.assertIn(r"\([0, 3]\)", normalized["stem"])
        self.assertEqual(validate_question_structure(normalized), [])
        dollar = normalize_generated_question({
            **QUESTION_DATA,
            "stem": r"已知函数 $f(x)=x^2-4x+3$，求其最小值。",
            "_subject_style": "high_school_math",
        })
        self.assertEqual(dollar["stem"], r"已知函数 \(f(x)=x^2-4x+3\)，求其最小值。")

    def test_source_exercise_copy_is_detected_but_real_variation_is_allowed(self):
        evidence = [{"content": "例题：若正数x和y满足xy=25，求x+y的最小值。解：由基本不等式可得最小值为10。"}]
        self.assertTrue(resembles_source_exercise("若正数x和y满足xy=25，求x+y的最小值。", evidence))
        self.assertFalse(resembles_source_exercise("已知a>0，函数f(x)=x+a/x在x≥2时取得最小值，求a的取值范围。", evidence))

    def test_sympy_compares_fraction_root_and_algebraic_answers(self):
        self.assertTrue(symbolic_answers_equivalent(r"\frac{1}{2}", "0.5"))
        self.assertTrue(symbolic_answers_equivalent(r"\sqrt{8}", r"2\sqrt{2}"))
        self.assertTrue(symbolic_answers_equivalent("(x+1)^2", "x^2+2x+1"))
        self.assertFalse(symbolic_answers_equivalent("2", "3"))

    def test_independent_answer_comparison_handles_objective_questions(self):
        self.assertTrue(independent_answers_consistent("single_choice", ["B"], ["b"]))
        self.assertTrue(independent_answers_consistent("multiple_choice", ["A", "C"], ["C", "A"]))
        self.assertTrue(independent_answers_consistent("calculation", [r"\frac{3}{2}"], ["1.5"]))
        self.assertFalse(independent_answers_consistent("single_choice", ["A"], ["D"]))

    def test_candidate_ranking_prefers_transformed_problem_over_source_copy(self):
        evidence = [{"content": "若正数x和y满足xy=25，求x+y的最小值。"}]
        copied = {**QUESTION_DATA, "stem": "若正数x和y满足xy=25，求x+y的最小值。"}
        varied = {**QUESTION_DATA, "stem": "已知a>0，函数f(x)=x+a/x在x≥2时取得最小值，求a的取值范围。"}
        ranked = rank_generation_candidates([copied, varied], evidence, "high_school_math")
        self.assertEqual(ranked[0]["stem"], varied["stem"])
        self.assertGreater(candidate_quality_score(varied, evidence, "high_school_math"), candidate_quality_score(copied, evidence, "high_school_math"))
    def test_generation_context_focuses_one_topic_per_batch(self):
        retrieved = [
            {"chunk_id": 1, "content": "CNN片段1", "retrieval_query": "CNN"},
            {"chunk_id": 2, "content": "SVM片段1", "retrieval_query": "SVM"},
            {"chunk_id": 3, "content": "CNN片段2", "retrieval_query": "CNN"},
            {"chunk_id": 4, "content": "SVM片段2", "retrieval_query": "SVM"},
        ]
        first, first_topic, first_round = focused_generation_context(retrieved, 0, 1000)
        second, second_topic, second_round = focused_generation_context(retrieved, 1, 1000)
        third, third_topic, third_round = focused_generation_context(retrieved, 2, 1000)
        self.assertEqual(([item["chunk_id"] for item in first], first_topic, first_round), ([1, 3], "CNN", 1))
        self.assertEqual(([item["chunk_id"] for item in second], second_topic, second_round), ([2, 4], "SVM", 1))
        self.assertEqual(([item["chunk_id"] for item in third], third_topic, third_round), ([1, 3], "CNN", 2))

    def test_vector_search_many_batches_embeddings_and_interleaves_topics(self):
        collection = Mock()
        embeddings = Mock()
        embeddings.embed_documents.return_value = [[1.0], [2.0]]
        collection.query.return_value = {
            "distances": [[0.1, 0.2], [0.05, 0.3]],
            "documents": [
                ["CNN通过卷积核提取局部特征，并逐层组合为高级表示。", "这是一段可被两个主题检索到的共用教学正文内容。"],
                ["SVM通过最大化分类间隔寻找分类超平面，从而提高泛化能力。", "这是一段可被两个主题检索到的共用教学正文内容。"],
            ],
            "metadatas": [[{"chunk_id": 1}, {"chunk_id": 2}], [{"chunk_id": 3}, {"chunk_id": 2}]],
        }
        service = VectorService()
        with patch.object(service, "_collection", return_value=(collection, embeddings)):
            results = service.search_many(["CNN", "SVM"], {"course_id": 1}, per_query=2, max_results=4)
        embeddings.embed_documents.assert_called_once_with(["CNN", "SVM"])
        self.assertEqual(
            [(item["chunk_id"], item["retrieval_query"]) for item in results],
            [(1, "CNN"), (3, "SVM"), (2, "CNN"), (2, "SVM")],
        )

    def test_vector_search_many_uses_keyword_fallback_after_dirty_vector_results(self):
        course = Course.objects.create(name="混合检索课程")
        knowledge_file = KnowledgeFile.objects.create(
            course=course,
            name="cnn.md",
            original_name="cnn.md",
            file="knowledge_files/cnn.md",
            file_type="md",
            content_hash="f" * 64,
            parse_status="SUCCESS",
        )
        useful = TextChunk.objects.create(
            course=course,
            knowledge_file=knowledge_file,
            chunk_index=0,
            content="CNN使用可学习的卷积核提取局部特征，并逐层形成更高层次的语义表示。",
            content_hash="e" * 64,
            vector_id="cnn-useful",
        )
        collection = Mock()
        embeddings = Mock()
        embeddings.embed_documents.return_value = [[1.0]]
        collection.query.return_value = {
            "distances": [[0.01]],
            "documents": [["A" * 300]],
            "metadatas": [[{"chunk_id": 999}]],
        }
        service = VectorService()
        with patch.object(service, "_collection", return_value=(collection, embeddings)):
            results = service.search_many(["CNN"], {"course_id": course.id}, per_query=2, max_results=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["chunk_id"], useful.id)
        self.assertEqual(results[0]["match_type"], "KEYWORD")

    @patch("apps.knowledge.services.VectorService.index")
    def test_vector_only_rebuild_preserves_existing_chunk(self, mocked_index):
        course = Course.objects.create(name="向量恢复测试")
        knowledge_file = KnowledgeFile.objects.create(
            course=course,
            name="lesson.txt",
            original_name="lesson.txt",
            file="knowledge_files/lesson.txt",
            file_type="txt",
            content_hash="a" * 64,
            parse_status="SUCCESS",
        )
        chunk = TextChunk.objects.create(
            course=course,
            knowledge_file=knowledge_file,
            chunk_index=0,
            content="必须保留的原文本块",
            content_hash="b" * 64,
            vector_id="chunk-original",
        )
        completed_chunk = TextChunk.objects.create(
            course=course,
            knowledge_file=knowledge_file,
            chunk_index=1,
            content="已经生成向量的文本块",
            content_hash="c" * 64,
            vector_id="chunk-completed",
            vector_status="SUCCESS",
        )
        task = ParseTask.objects.create(knowledge_file=knowledge_file, current_step="等待重建向量")
        FileParseService().run(task)
        chunk.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(chunk.content, "必须保留的原文本块")
        self.assertEqual(chunk.vector_id, "chunk-original")
        self.assertEqual(task.status, "SUCCESS")
        indexed_chunks = mocked_index.call_args.args[0]
        self.assertEqual([item.id for item in indexed_chunks], [chunk.id])
        completed_chunk.refresh_from_db()
        self.assertEqual(completed_chunk.vector_status, "SUCCESS")
        mocked_index.assert_called_once()

    @patch("apps.knowledge.services.TextChunk.objects.filter")
    @patch("apps.knowledge.services.get_config")
    def test_vector_index_batches_large_input_and_reports_progress(self, mocked_config, mocked_filter):
        mocked_config.return_value = {"embedding_batch_size": 2, "embedding_model": "bge-m3"}
        chunks = [SimpleNamespace(id=i, content=f"文本{i}", vector_id=f"v{i}", course_id=1, knowledge_file_id=2, chapter_id=None, page_number=None) for i in range(5)]
        collection = Mock()
        embeddings = Mock()
        embeddings.embed_documents.side_effect = lambda texts: [[1.0] for _ in texts]
        progress = Mock()
        service = VectorService()
        with patch.object(service, "_collection", return_value=(collection, embeddings)):
            service.index(chunks, progress_callback=progress)
        self.assertEqual(embeddings.embed_documents.call_count, 3)
        self.assertEqual([len(call.args[0]) for call in embeddings.embed_documents.call_args_list], [2, 2, 1])
        self.assertEqual([call.args for call in progress.call_args_list], [(2, 5), (4, 5), (5, 5)])
        self.assertEqual(collection.upsert.call_count, 3)
        self.assertEqual(mocked_filter.call_count, 3)

    @patch("apps.knowledge.services.TextChunk.objects.filter")
    @patch("apps.knowledge.services.get_config")
    def test_vector_index_yields_after_completed_batch(self, mocked_config, _mocked_filter):
        mocked_config.return_value = {"embedding_batch_size": 2, "embedding_model": "bge-m3"}
        chunks = [SimpleNamespace(id=i, content=f"文本{i}", vector_id=f"v{i}", course_id=1, knowledge_file_id=2, chapter_id=None, page_number=None) for i in range(4)]
        collection = Mock()
        embeddings = Mock()
        embeddings.embed_documents.side_effect = lambda texts: [[1.0] for _ in texts]
        service = VectorService()
        with patch.object(service, "_collection", return_value=(collection, embeddings)):
            with self.assertRaises(TaskYield):
                service.index(chunks, yield_callback=lambda: True)
        self.assertEqual(embeddings.embed_documents.call_count, 1)
        self.assertEqual(collection.upsert.call_count, 1)

class JsonAndOllamaTests(TestCase):
    def test_markdown_wrapped_json_is_parsed(self):
        from common.json_utils import parse_model_json
        self.assertEqual(parse_model_json("```json\n{\"ok\":true}\n```"), {"ok":True})
    @patch("apps.ai_service.services.requests.get")
    def test_ollama_model_list(self, mocked_get):
        mocked_get.return_value = Mock(ok=True, json=lambda:{"models":[{"name":"qwen2.5:7b"}]}); mocked_get.return_value.raise_for_status = Mock()
        self.assertEqual(OllamaService().list_models(), ["qwen2.5:7b"])
    @patch("apps.ai_service.services.requests.get", side_effect=Exception("offline"))
    def test_ollama_failure_has_clear_message(self, _):
        with self.assertRaises(Exception): OllamaService().list_models()
    @patch.object(OllamaService, "ensure_model")
    @patch("apps.ai_service.services.requests.post")
    def test_ollama_passes_json_schema_to_format(self, mocked_post, _mocked_model):
        mocked_post.return_value = Mock(json=lambda: {"message": {"content": '{"questions":[]}'}})
        mocked_post.return_value.raise_for_status = Mock()
        schema = {"type": "object", "properties": {"questions": {"type": "array"}}}
        OllamaService().chat_json([{"role": "user", "content": "test"}], schema=schema)
        payload = mocked_post.call_args.kwargs["json"]
        self.assertEqual(payload["format"], schema)
        self.assertEqual(payload["options"]["temperature"], 0)

class QuestionValidationTests(TestCase):
    def setUp(self): self.course = Course.objects.create(name="题目测试"); self.client = APIClient()
    def test_valid_single_choice_has_no_issues(self): self.assertEqual(validate_question_structure(QUESTION_DATA), [])
    def test_single_choice_schema_enforces_four_options_and_one_answer(self):
        schema = question_batch_schema("single_choice", 2)
        question = schema["properties"]["questions"]
        self.assertEqual((question["minItems"], question["maxItems"]), (2, 2))
        self.assertEqual(question["items"]["properties"]["options"]["minItems"], 4)
        self.assertEqual(question["items"]["properties"]["answer"]["maxItems"], 1)
    def test_single_choice_rejects_multiple_answers(self):
        data = {**QUESTION_DATA, "answer":["A","B"]}; self.assertIn("单选题只能有一个答案", validate_question_structure(data))
    def test_single_choice_rejects_multi_answer_wording(self):
        data = {**QUESTION_DATA, "stem": "AI Agent的核心组成包括哪些？"}
        self.assertTrue(any("多答案问法" in issue for issue in validate_question_structure(data)))
    def test_multiple_choice_requires_two_answers(self):
        data = {**QUESTION_DATA, "type":"multiple_choice", "answer":["B"]}; self.assertIn("多选题至少需要两个答案", validate_question_structure(data))
    def test_multiple_choice_answer_string_is_normalized(self):
        data = normalize_generated_question({**QUESTION_DATA, "type": "multiple_choice", "answer": ["A, C"]})
        self.assertEqual(data["answer"], ["A", "C"])
        self.assertEqual(validate_question_structure(data), [])
    def test_choice_option_accepts_chinese_content_key(self):
        data = normalize_generated_question({**QUESTION_DATA, "options": [
            {"label": "A", "content": "class"}, {"label": "B", "content": "def"},
            {"label": "C", "内容": "import"}, {"label": "D", "text": "return"},
        ]})
        self.assertEqual([item["content"] for item in data["options"]], ["class", "def", "import", "return"])
        self.assertEqual(validate_question_structure(data), [])
    def test_judge_synonym_is_normalized(self):
        data = normalize_generated_question({"type": "judge", "stem": "Python是一种编程语言。", "answer": "对", "analysis": "该表述正确。", "difficulty": "简单", "score": 1})
        self.assertEqual(data["answer"], ["正确"])
        self.assertEqual(validate_question_structure(data), [])
    def test_non_choice_discards_model_empty_option_placeholder(self):
        data = normalize_generated_question({"type": "short_answer", "options": [{"label": "A", "content": ""}], "answer": ["参考答案"]})
        self.assertEqual(data["options"], [])
    def test_term_explanation_rejects_choice_letter_answers(self):
        base = {
            "type": "term_explanation", "stem": "请解释注意力机制。", "options": [],
            "analysis": "注意力机制会根据相关性动态分配权重。", "difficulty": "中等", "score": 4,
        }
        for invalid_answer in (["A"], ["A", "B", "C", "D"], ["ABCD"], ["A/B/C/D"]):
            with self.subTest(answer=invalid_answer):
                issues = validate_question_structure({**base, "answer": invalid_answer})
                self.assertTrue(any("完整文字答案" in issue for issue in issues))
    def test_term_explanation_accepts_full_text_answer_and_schema_requests_text(self):
        data = {
            "type": "term_explanation", "stem": "请解释注意力机制。", "options": [],
            "answer": ["注意力机制是根据输入元素的相关性动态分配权重的机制。"],
            "analysis": "它能让模型聚焦于当前任务更重要的信息。", "difficulty": "中等", "score": 4,
        }
        self.assertEqual(validate_question_structure(data), [])
        answer_items = question_batch_schema("term_explanation", 1)["properties"]["questions"]["items"]["properties"]["answer"]["items"]
        self.assertGreaterEqual(answer_items["minLength"], 4)
    def test_term_explanation_uses_its_own_correction_instruction(self):
        instruction = generation_correction_instruction("term_explanation")
        self.assertIn("完整的文字解释", instruction)
        self.assertIn("禁止使用A、B、C、D", instruction)
        self.assertNotIn("四个非空且不重复的选项", instruction)
    def test_generated_stem_rejects_material_reference_wording(self):
        data = {**QUESTION_DATA, "stem": "这本书中介绍的函数定义关键字是什么？"}
        self.assertTrue(any("来源指代语" in issue for issue in validate_question_structure(data)))
    def test_generated_stem_rejects_answer_leak(self):
        data = {
            **QUESTION_DATA,
            "type": "fill_blank",
            "stem": "在Python中，如何修改say_hello方法？ answer: def say_hello(self): print(f'Hello, {self.name}!')________。",
            "options": [],
            "answer": ["def say_hello(self): print(f'Hello, {self.name}!')"],
        }
        self.assertTrue(any("答案只能放在answer字段" in issue for issue in validate_question_structure(data)))
    def test_generated_stem_rejects_broken_latex_matrix(self):
        data = {
            **QUESTION_DATA,
            "stem": r"给定矩阵 \(X=\begin{bmatrix}1&2\\3&4\right)\)，求转置矩阵的维度。",
        }
        issues = validate_question_structure(data)
        self.assertTrue(any("begin/end环境" in issue for issue in issues))
        self.assertTrue(any("left/right括号" in issue for issue in issues))
    def test_generated_stem_accepts_complete_latex_matrix(self):
        data = {
            **QUESTION_DATA,
            "stem": r"给定矩阵 \(X=\begin{bmatrix}1&2\\3&4\end{bmatrix}\)，求转置矩阵的维度。",
        }
        self.assertEqual(validate_question_structure(data), [])
    def test_every_question_requires_answer_and_analysis(self):
        no_answer = {**QUESTION_DATA, "answer": []}
        no_analysis = {**QUESTION_DATA, "analysis": ""}
        self.assertIn("必须提供参考答案", validate_question_structure(no_answer))
        self.assertIn("必须提供题目解析", validate_question_structure(no_analysis))
    def test_question_types_are_distributed_and_batched(self):
        targets = distribute_question_types(["single_choice", "fill_blank", "judge", "programming"], 10)
        self.assertEqual(targets, {"single_choice": 3, "fill_blank": 3, "judge": 2, "programming": 2})
        batch = next_type_batch(targets, {"single_choice": 1, "fill_blank": 1}, 5)
        self.assertEqual(batch, {"single_choice": 2})
    def test_generation_accepts_user_defined_type_counts(self):
        response = self.client.post("/api/v1/generation/tasks/", {
            "course": self.course.id,
            "count": 8,
            "question_types": ["single_choice", "judge", "programming"],
            "type_counts": {"single_choice": 4, "judge": 3, "programming": 1},
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["config"]["type_counts"], {"single_choice": 4, "judge": 3, "programming": 1})

    def test_generation_tasks_are_newest_first(self):
        first = GenerationTask.objects.create(course=self.course, total_count=1, status="SUCCESS")
        second = GenerationTask.objects.create(course=self.course, total_count=1, status="SUCCESS")
        response = self.client.get("/api/v1/generation/tasks/?page_size=100")
        ids = [item["id"] for item in response.json()["data"]["items"]]
        self.assertLess(ids.index(second.id), ids.index(first.id))

    def test_completed_generation_task_can_be_deleted_without_deleting_questions(self):
        task = GenerationTask.objects.create(course=self.course, total_count=1, status="SUCCESS")
        question = create_question(self.course, QUESTION_DATA, task=task)
        response = self.client.delete(f"/api/v1/generation/tasks/{task.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GenerationTask.objects.filter(pk=task.id).exists())
        question.refresh_from_db()
        self.assertIsNone(question.generation_task_id)

    def test_running_generation_task_must_be_cancelled_before_delete(self):
        task = GenerationTask.objects.create(course=self.course, total_count=1, status="RUNNING")
        response = self.client.delete(f"/api/v1/generation/tasks/{task.id}/")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(GenerationTask.objects.filter(pk=task.id).exists())

    def test_cancel_generation_task_updates_status_immediately(self):
        task = GenerationTask.objects.create(course=self.course, total_count=1, status="RUNNING")
        response = self.client.post(f"/api/v1/generation/tasks/{task.id}/cancel/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "CANCELLED")
        task.refresh_from_db()
        self.assertEqual(task.status, "CANCELLED")
        self.assertTrue(task.cancel_requested)
        self.assertIsNotNone(task.finished_at)
    def test_generation_rejects_incorrect_type_count_total(self):
        response = self.client.post("/api/v1/generation/tasks/", {
            "course": self.course.id,
            "count": 8,
            "question_types": ["single_choice", "judge"],
            "type_counts": {"single_choice": 4, "judge": 3},
        }, format="json")
        self.assertEqual(response.status_code, 400)
    def test_exact_and_similar_question_detection(self):
        q = create_question(self.course, QUESTION_DATA, source_type="MANUAL")
        result = find_similar("Python中用于定义函数的关键字是？", self.course.id)
        self.assertEqual(result[0]["question_id"], q.id); self.assertEqual(result[0]["similarity"], 1.0)
    def test_generation_duplicate_detection_is_scoped_to_same_type_and_course(self):
        question = create_question(self.course, QUESTION_DATA, source_type="MANUAL")
        duplicate = find_generation_duplicate("Python中用于定义函数的关键字是。", self.course.id, "single_choice")
        self.assertEqual(duplicate["question_id"], question.id)
        self.assertIsNone(find_generation_duplicate(question.stem, self.course.id, "fill_blank"))
        self.assertIsNone(find_generation_duplicate("Python中用于声明函数的关键字是什么？", self.course.id, "single_choice", 1.0))

    def test_generation_rejects_cosmetic_and_number_only_variants(self):
        geometry = "已知空间中有6个点，其中任何3个点不共线，则过每3个点作一个平面，可以作多少个平面？"
        function = r"已知函数 \(f(x)=x^2-4x+3\) 在区间 \([0,3]\) 上的最小值为多少？"
        create_question(self.course, {**QUESTION_DATA, "stem": geometry}, source_type="MANUAL")
        create_question(self.course, {**QUESTION_DATA, "stem": function}, source_type="MANUAL")
        cosmetic = find_generation_duplicate(
            "若空间中有6个点，其中任何3个点不共线，则过每3个点作一个平面，可以作多少个平面？",
            self.course.id,
            "single_choice",
        )
        number_only = find_generation_duplicate(
            r"已知函数 \(f(x)=2x^2-4x+1\) 在区间 \([0,3]\) 上的最小值为多少？",
            self.course.id,
            "single_choice",
        )
        real_variation = find_generation_duplicate(
            r"设 \(a>0\)，函数 \(g(x)=x+a/x\) 在 \(x\ge2\) 时取得最小值，求 \(a\) 的取值范围。",
            self.course.id,
            "single_choice",
        )
        self.assertIsNotNone(cosmetic)
        self.assertIsNotNone(number_only)
        self.assertIsNone(real_variation)

    def test_generation_rejects_same_core_task_with_extra_background_or_code(self):
        original = "设计一个Time类，计算两个时间点之间的时间差，并以秒为单位返回结果。"
        create_question(self.course, {**QUESTION_DATA, "stem": original}, source_type="MANUAL")
        with_background = "在课程成绩统计程序中，设计一个Time类，计算两个时间点之间的时间差，并以秒为单位返回结果。"
        with_code = "给定以下Time类：```python\nclass Time:\n    pass\n```请计算两个时间点之间的时间差，并以秒为单位返回结果。"
        self.assertEqual(find_generation_duplicate(with_background, self.course.id, "single_choice")["match_type"], "CORE_TASK")
        self.assertIsNotNone(find_generation_duplicate(with_code, self.course.id, "single_choice"))

    def test_generation_allows_similar_variation_when_only_exact_duplicates_are_blocked(self):
        original = "设计一个Time类，计算两个时间点之间的时间差，并以秒为单位返回结果。"
        create_question(self.course, {**QUESTION_DATA, "stem": original}, source_type="MANUAL")
        variation = "在课程成绩统计程序中，设计一个Time类，计算两个时间点之间的时间差，并以秒为单位返回结果。"
        self.assertIsNotNone(find_generation_duplicate(variation, self.course.id, "single_choice"))
        self.assertIsNone(find_generation_duplicate(variation, self.course.id, "single_choice", exact_only=True))
        self.assertIsNotNone(find_generation_duplicate(original, self.course.id, "single_choice", exact_only=True))

    def test_deep_mode_has_enough_budget_to_replace_rejected_candidates(self):
        self.assertGreaterEqual(generation_batch_budget(15, "DEEP", 2), 67)
        self.assertGreater(generation_batch_budget(15, "DEEP", 2), generation_batch_budget(15, "FAST", 2))

    def test_question_snapshot_keeps_score_for_agent_rule_validation(self):
        question = create_question(self.course, QUESTION_DATA, source_type="MANUAL")
        snapshot = snapshot_question(question)
        snapshot["type"] = question.question_type
        self.assertEqual(snapshot["score"], 2.0)
        self.assertNotIn("分值必须大于0", validate_question_structure(snapshot))

    @patch("apps.questions.services.OllamaService.chat_json")
    @patch("apps.questions.services.VectorService.search")
    def test_standard_mode_generates_two_candidates_and_saves_higher_quality_one(self, mocked_search, mocked_chat):
        mocked_search.return_value = [{"chunk_id": 1, "content": "Python函数可以接收参数并返回计算结果。"}]
        definition = {**QUESTION_DATA, "stem": "什么是Python函数？", "source_chunk_ids": [1]}
        application = {**QUESTION_DATA, "stem": "阅读一段包含参数和return语句的Python函数，调用该函数后输出结果的是哪个选项？", "source_chunk_ids": [1]}
        mocked_chat.return_value = {"questions": [definition, application]}
        task = GenerationTask.objects.create(
            course=self.course, total_count=1, status="WAITING",
            config={"count": 1, "type_counts": {"single_choice": 1}, "question_types": ["single_choice"], "quality_mode": "STANDARD", "batch_size": 1},
        )
        GenerationService().run(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "SUCCESS")
        self.assertEqual(task.questions.get().stem, application["stem"])
        schema = mocked_chat.call_args.args[3]
        self.assertEqual(schema["properties"]["questions"]["minItems"], 2)
        prompt = mocked_chat.call_args.args[0][1]["content"]
        self.assertIn("达到过去困难题水平", prompt)

    @patch("apps.questions.services.OllamaService.chat_json")
    @patch("apps.questions.services.VectorService.search")
    def test_generation_skips_duplicate_then_generates_new_question(self, mocked_search, mocked_chat):
        mocked_search.return_value = [
            {"chunk_id": index, "content": f"Python知识片段{index}"}
            for index in range(1, 7)
        ]
        existing = create_question(self.course, QUESTION_DATA, source_type="MANUAL")
        unique = {**QUESTION_DATA, "stem": "Python函数定义后，如何通过函数名执行其中的代码？", "source_chunk_ids": [999, 2]}
        mocked_chat.side_effect = [
            {"questions": [{**QUESTION_DATA, "source_chunk_ids": [1]}]},
            {"questions": [unique]},
        ]
        task = GenerationTask.objects.create(
            course=self.course,
            total_count=1,
            status="WAITING",
            config={"count": 1, "type_counts": {"single_choice": 1}, "question_types": ["single_choice"], "batch_size": 1, "max_retries": 0},
        )

        GenerationService().run(task)

        task.refresh_from_db()
        self.assertEqual(task.status, "SUCCESS")
        self.assertEqual(task.questions.filter(is_deleted=False).count(), 1)
        generated = task.questions.get()
        self.assertEqual(generated.stem, unique["stem"])
        self.assertEqual(generated.source_chunk_ids, [2])
        self.assertTrue(any("完全相同" in item["reason"] for item in task.config["failure_details"]))
        second_prompt = mocked_chat.call_args_list[1].args[0][1]["content"]
        self.assertIn(existing.stem, second_prompt)
        self.assertEqual(mocked_search.call_args.args[2], 5)

    @patch("apps.questions.services.OllamaService.chat_json")
    @patch("apps.questions.services.VectorService.search")
    def test_large_generation_retrieves_a_larger_rag_pool(self, mocked_search, mocked_chat):
        mocked_search.return_value = [{"chunk_id": 1, "content": "Python使用def定义函数。"}]
        mocked_chat.return_value = {"questions": []}
        task = GenerationTask.objects.create(
            course=self.course,
            total_count=20,
            status="WAITING",
            config={"count": 20, "type_counts": {"single_choice": 20}, "question_types": ["single_choice"], "batch_size": 5},
        )
        GenerationService().run(task)
        self.assertEqual(mocked_search.call_args.args[2], 20)
        # 大批量任务会先额外生成一次课程专属命题蓝图；连续空结果时仍会由停滞保护终止，
        # 但不能沿用旧的 5 次限制，否则真实任务做到 14/15 时没有足够补题机会。
        self.assertGreater(mocked_chat.call_count, 6)
        self.assertLessEqual(mocked_chat.call_count, 14)

    @patch("apps.questions.services.OllamaService.chat_json")
    @patch("apps.questions.services.VectorService.search")
    @patch("apps.questions.services.VectorService.search_many")
    def test_multi_topic_generation_uses_focused_rag_context(self, mocked_search_many, mocked_search, mocked_chat):
        mocked_search_many.return_value = [
            {"chunk_id": 1, "content": "CNN使用卷积核提取局部特征。", "retrieval_query": "CNN"},
            {"chunk_id": 2, "content": "SVM通过最大间隔构建分类超平面。", "retrieval_query": "SVM"},
            {"chunk_id": 3, "content": "CNN常用于处理网格结构数据。", "retrieval_query": "CNN"},
            {"chunk_id": 4, "content": "SVM可以通过核函数处理非线性问题。", "retrieval_query": "SVM"},
        ]
        mocked_chat.return_value = {"questions": [
            {**QUESTION_DATA, "stem": "CNN中卷积核的主要作用是什么？", "source_chunk_ids": [1]},
            {**QUESTION_DATA, "stem": "CNN的局部特征提取依赖哪种运算？", "source_chunk_ids": [3]},
        ]}
        task = GenerationTask.objects.create(
            course=self.course,
            total_count=2,
            status="WAITING",
            config={"count": 2, "type_counts": {"single_choice": 2}, "question_types": ["single_choice"], "supplement": "CNN、SVM", "batch_size": 4},
        )
        GenerationService().run(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "SUCCESS")
        mocked_search_many.assert_called_once()
        mocked_search.assert_not_called()
        prompt = mocked_chat.call_args.args[0][1]["content"]
        self.assertIn('"focus_topic": "CNN"', prompt)
        self.assertIn("CNN使用卷积核", prompt)
        self.assertNotIn("SVM通过最大间隔", prompt)
        self.assertEqual(sorted(task.questions.values_list("source_chunk_ids", flat=True)), [[1], [3]])
    @patch("apps.questions.services.OllamaService.chat_json")
    @patch("apps.questions.services.VectorService.search")
    def test_generation_corrects_invalid_choice_and_counts_only_missing_questions(self, mocked_search, mocked_chat):
        mocked_search.return_value = [{"chunk_id": 1, "content": "Python使用def关键字定义函数。"}]
        invalid = {**QUESTION_DATA, "options": QUESTION_DATA["options"][:3]}
        mocked_chat.side_effect = [{"questions": [invalid]}, {"questions": [QUESTION_DATA]}]
        task = GenerationTask.objects.create(
            course=self.course, total_count=1, status="WAITING",
            config={"count": 1, "type_counts": {"single_choice": 1}, "question_types": ["single_choice"], "batch_size": 1, "max_retries": 0},
        )
        GenerationService().run(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "SUCCESS")
        self.assertEqual(task.success_count, 1)
        self.assertEqual(task.failed_count, 0)
        self.assertGreaterEqual(mocked_chat.call_count, 2)

    @patch("apps.questions.services.OllamaService.chat_json")
    @patch("apps.questions.services.VectorService.search")
    def test_generation_uses_user_score_and_difficulty_instead_of_invalid_model_values(self, mocked_search, mocked_chat):
        mocked_search.return_value = [{"chunk_id": 1, "content": "Python使用def关键字定义函数。"}]
        complex_stem = "给出两段实现相同任务的Python程序，若输入规模扩大且内存受到限制，同时要求对任意输入保持输出一致，请比较两种实现的时间复杂度和空间复杂度，进一步分析改进方案的存在性与唯一性并给出推导过程。"
        mocked_chat.return_value = {"questions": [{**QUESTION_DATA, "stem": complex_stem, "score": 0, "difficulty": "不存在的难度"}]}
        task = GenerationTask.objects.create(
            course=self.course, total_count=1, status="WAITING",
            config={"count": 1, "type_counts": {"single_choice": 1}, "question_types": ["single_choice"], "score": 3, "difficulty": "较难", "batch_size": 1},
        )
        GenerationService().run(task)
        question = task.questions.get()
        self.assertEqual(float(question.score), 3)
        self.assertEqual(question.difficulty, "较难")
    def test_generation_retry_preserves_successful_questions_and_progress(self):
        task = GenerationTask.objects.create(
            course=self.course, total_count=2, status="FAILED", success_count=1, failed_count=3,
            config={"count": 2, "type_counts": {"single_choice": 2}, "failure_details": [{"reason": "选择题至少需要四个选项"}]},
        )
        create_question(self.course, QUESTION_DATA, task=task)
        response = self.client.post(f"/api/v1/generation/tasks/{task.id}/retry/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failed_count"], 1)
        self.assertEqual(data["progress"], 50)
        self.assertNotIn("failure_details", data["config"])

    def test_generation_task_hides_soft_deleted_questions_and_retry_refills_them(self):
        task = GenerationTask.objects.create(
            course=self.course,
            total_count=2,
            status="FAILED",
            success_count=2,
            config={"count": 2, "type_counts": {"single_choice": 2}},
        )
        retained = create_question(self.course, {**QUESTION_DATA, "stem": "保留的题目"}, task=task)
        removed = create_question(self.course, {**QUESTION_DATA, "stem": "已软删除的重复题"}, task=task)
        removed.is_deleted = True
        removed.save(update_fields=["is_deleted"])
        detail = self.client.get(f"/api/v1/generation/tasks/{task.id}/").json()["data"]
        self.assertEqual(detail["retained_count"], 1)
        self.assertEqual([item["id"] for item in detail["questions"]], [retained.id])
        retried = self.client.post(f"/api/v1/generation/tasks/{task.id}/retry/", {}, format="json").json()["data"]
        self.assertEqual(retried["success_count"], 1)
        self.assertEqual(retried["failed_count"], 1)

    @patch("apps.questions.services.OllamaService.chat_json")
    @patch("apps.questions.services.VectorService.search")
    def test_generation_batch_save_does_not_overwrite_cancel_request(self, mocked_search, mocked_chat):
        mocked_search.return_value = [{"chunk_id": 1, "content": "Python使用def关键字定义函数。"}]
        task = GenerationTask.objects.create(
            course=self.course, total_count=2, status="WAITING",
            config={"count": 2, "type_counts": {"single_choice": 2}, "question_types": ["single_choice"], "batch_size": 1},
        )
        def request_cancel(*_args, **_kwargs):
            GenerationTask.objects.filter(pk=task.pk).update(cancel_requested=True)
            return {"questions": [{**QUESTION_DATA, "stem": "第一道题"}]}
        mocked_chat.side_effect = request_cancel
        GenerationService().run(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "CANCELLED")
        self.assertTrue(task.cancel_requested)
        self.assertEqual(task.success_count, 1)

class PaperTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.course = Course.objects.create(name="组卷测试")
        self.questions = [create_question(self.course, {**QUESTION_DATA, "stem":f"测试题{i}"}, source_type="MANUAL") for i in range(3)]
        Question.objects.update(review_status="APPROVED")
    def test_rule_generate_and_total_score(self):
        paper, shortages = rule_generate({"course":self.course.id, "name":"规则试卷", "target_score":6, "type_config":[{"type":"single_choice","count":3,"score_each":2}], "difficulty_ratio":{"简单":1.0}})
        self.assertEqual(shortages, []); self.assertEqual(float(paper.total_score), 6); self.assertEqual(paper.paper_questions.count(), 3)
        self.assertEqual(paper.sections.get().title, "第一部分 选择题")
    def test_rule_generate_reports_shortage(self):
        _, shortages = rule_generate({"course":self.course.id, "name":"不足试卷", "type_config":[{"type":"single_choice","count":5,"score_each":2}], "difficulty_ratio":{"简单":1.0}})
        self.assertEqual(shortages[0]["missing"], 2)

    def test_same_paper_rejects_similar_questions_but_question_bank_keeps_both(self):
        first = create_question(self.course, {**QUESTION_DATA, "stem": "设计一个Time类，计算两个时间点之间的时间差，并以秒为单位返回结果。"}, source_type="MANUAL")
        second = create_question(self.course, {**QUESTION_DATA, "stem": "在课程成绩统计程序中，设计一个Time类，计算两个时间点之间的时间差，并以秒为单位返回结果。"}, source_type="MANUAL")
        conflict, score = find_similar_question_in_paper(second, [first])
        self.assertEqual(conflict.id, first.id)
        self.assertGreaterEqual(score, 0.78)
        self.assertEqual(coverage_aware_selection([second], 1, existing_questions=[first]), [])
        self.assertEqual(Question.objects.filter(id__in=[first.id, second.id]).count(), 2)

    def test_manual_paper_creation_rejects_similar_questions_across_sections(self):
        first = create_question(self.course, {**QUESTION_DATA, "stem": "设计一个Time类，计算两个时间点之间的时间差，并以秒为单位返回结果。"}, source_type="MANUAL")
        second = create_question(self.course, {**QUESTION_DATA, "stem": "在项目中设计一个Time类，计算两个时间点之间的时间差，并以秒为单位返回结果。"}, source_type="MANUAL")
        response = self.client.post("/api/v1/papers/manual-generate/", {
            "course": self.course.id,
            "name": "相似题校验试卷",
            "sections": [
                {"title": "第一部分", "questions": [{"question_id": first.id}]},
                {"title": "第二部分", "questions": [{"question_id": second.id}]},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Paper.objects.filter(name="相似题校验试卷").exists())
    def test_ai_rule_accepts_list_ratios_and_chinese_question_types(self):
        normalized = normalize_paper_rule({
            "name": "AI期末试卷",
            "duration": 90,
            "target_score": 10,
            "type_config": [{"题型": "单项选择题", "数量": 5, "每题分值": 2}],
            "difficulty_ratio": [
                {"difficulty": "简单", "percentage": 30},
                {"difficulty": "中等", "percentage": 50},
                {"difficulty": "困难", "percentage": 20},
            ],
            "allow_similar": "false",
        })
        self.assertEqual(normalized["type_config"], [{"type": "single_choice", "count": 5, "score_each": 2}])
        self.assertEqual(normalized["difficulty_ratio"], {"简单": 0.3, "中等": 0.5, "困难": 0.2})
        self.assertFalse(normalized["allow_similar"])
    @patch("apps.papers.services.OllamaService.chat_json")
    def test_ai_rule_api_normalizes_model_output(self, mocked_chat):
        from apps.knowledge.models import Chapter
        chapter = Chapter.objects.create(course=self.course, name="Python基础")
        mocked_chat.return_value = {
            "name": "AI组卷", "duration": 60, "target_score": 6,
            "type_config": [{"question_type": "单选题", "count": 3, "score_each": 2}],
            "difficulty_ratio": [{"简单": 1}],
            "chapter_ids": ["Python基础", "模型猜测但不存在的章节"],
        }
        response = self.client.post("/api/v1/papers/parse-natural-rule/", {"text": "生成一套测试卷", "course_id": self.course.id}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertNotIn("duration", data)
        self.assertEqual(data["paper_type"], "AI辅助组卷")
        self.assertEqual(data["type_config"][0]["type"], "single_choice")
        self.assertEqual(data["difficulty_ratio"], {"简单": 1.0, "中等": 0.0, "困难": 0.0})
        self.assertEqual(data["chapter_ids"], [chapter.id])

    def test_ai_rule_generate_does_not_set_exam_duration(self):
        paper, _ = rule_generate({
            "course": self.course.id,
            "name": "无考试时间的AI试卷",
            "paper_type": "AI辅助组卷",
            "target_score": 6,
            "type_config": [{"type": "single_choice", "count": 3, "score_each": 2}],
            "difficulty_ratio": {"简单": 1.0},
        })
        self.assertEqual(paper.duration, 0)
    def test_paper_delete_returns_uniform_response_and_soft_deletes(self):
        paper = Paper.objects.create(course=self.course, name="待删除试卷")
        response = self.client.delete(f"/api/v1/papers/{paper.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "试卷已删除")
        paper.refresh_from_db()
        self.assertTrue(paper.is_deleted)
        self.assertEqual(self.client.get(f"/api/v1/papers/{paper.id}/").status_code, 404)
    def test_snapshot_is_not_changed_after_question_edit(self):
        q = self.questions[0]; snapshot = snapshot_question(q); old_stem = snapshot["stem"]; q.stem = "修改后的题干"; q.save()
        self.assertEqual(snapshot["stem"], old_stem); self.assertNotEqual(snapshot["stem"], q.stem)
    def test_old_english_section_title_is_localized_and_score_is_summarized(self):
        paper = Paper.objects.create(course=self.course, name="旧试卷", target_score=6)
        section = PaperSection.objects.create(paper=paper, title="第1部分 single_choice")
        for index, question in enumerate(self.questions):
            PaperQuestion.objects.create(paper=paper, section=section, question=question, score=2, sort_order=index, question_snapshot=snapshot_question(question))
        recalculate_paper(paper)
        self.assertEqual(section_display_title(section, 0), "第一部分 选择题")
        self.assertEqual(section_score_summary(section), "共6分，每题2分")
    def test_formal_question_bank_filters_by_all_supported_question_types(self):
        judge_question = create_question(self.course, {
            "type": "judge", "stem": "Python支持函数定义。", "options": [],
            "answer": ["正确"], "analysis": "该说法正确。", "difficulty": "简单",
            "score": 1, "scoring_points": [],
        }, source_type="MANUAL")
        judge_question.review_status = "APPROVED"
        judge_question.save(update_fields=["review_status"])
        response = self.client.get("/api/v1/questions/", {
            "course": self.course.id, "review_status": "APPROVED", "question_type": "judge",
        })
        self.assertEqual(response.status_code, 200)
        items = response.json()["data"]["items"]
        self.assertTrue(items)
        self.assertTrue(all(item["question_type"] == "judge" for item in items))
    @override_settings(MEDIA_ROOT=Path(tempfile.mkdtemp()))
    def test_word_export_creates_nonempty_file(self):
        paper = Paper.objects.create(course=self.course, name="Word导出测试", target_score=2)
        section = PaperSection.objects.create(paper=paper, title="一、选择题")
        PaperQuestion.objects.create(paper=paper, section=section, question=self.questions[0], score=2, question_snapshot=snapshot_question(self.questions[0])); recalculate_paper(paper)
        record = ExportService().export(paper, "student", "docx")
        self.assertEqual(record.status, "SUCCESS"); self.assertGreater(record.file_size, 0); self.assertTrue((Path(tempfile.gettempdir()) / "nonexistent").exists() is False)
    def test_word_export_uses_chinese_section_heading_without_per_question_scores(self):
        from docx import Document
        with tempfile.TemporaryDirectory() as tmp, self.settings(MEDIA_ROOT=Path(tmp)):
            paper = Paper.objects.create(course=self.course, name="中文格式测试", target_score=6)
            section = PaperSection.objects.create(paper=paper, title="第1部分 single_choice")
            for index, question in enumerate(self.questions):
                PaperQuestion.objects.create(paper=paper, section=section, question=question, score=2, sort_order=index, question_snapshot=snapshot_question(question))
            recalculate_paper(paper)
            record = ExportService().export(paper, "student", "docx")
            document = Document(Path(tmp) / record.file_path)
            paragraphs = [paragraph.text for paragraph in document.paragraphs]
            self.assertIn("第一部分 选择题（共6分，每题2分）", paragraphs)
            self.assertFalse(any("single_choice" in text for text in paragraphs))
            question_lines = [text for text in paragraphs if text.startswith(("1. ", "2. ", "3. "))]
            self.assertEqual(len(question_lines), 3)
            self.assertTrue(all("（2分）" not in text and "（2.00分）" not in text for text in question_lines))
    @override_settings(MEDIA_ROOT=Path(tempfile.mkdtemp()))
    def test_pdf_export_creates_nonempty_chinese_file(self):
        paper = Paper.objects.create(course=self.course, name="中文PDF导出测试", target_score=2)
        section = PaperSection.objects.create(paper=paper, title="一、选择题")
        PaperQuestion.objects.create(paper=paper, section=section, question=self.questions[0], score=2, question_snapshot=snapshot_question(self.questions[0])); recalculate_paper(paper)
        record = ExportService().export(paper, "student", "pdf")
        self.assertEqual(record.status, "SUCCESS"); self.assertGreater(record.file_size, 0)
