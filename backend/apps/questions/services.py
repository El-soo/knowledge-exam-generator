import hashlib
import json
import logging
import re
from collections import Counter
from difflib import SequenceMatcher
from django.db import transaction
from django.utils import timezone
from common.constants import DIFFICULTIES, QUESTION_TYPES
from common.exceptions import BusinessError
from apps.ai_service.services import OllamaService, get_config, get_prompt
from apps.knowledge.services import VectorService
from .models import Question, QuestionOption, QuestionReview

logger = logging.getLogger("generation")

MATERIAL_REFERENCE_PATTERN = re.compile(
    r"(?:这本书|本书|教材中|资料中|文中|本文|上述内容|"
    r"根据上下文|上下文中|知识库中|原文中|本章介绍)"
)
SINGLE_MULTI_ANSWER_STEM_PATTERN = re.compile(r"(?:包括哪些|以下哪些|哪些是|所有正确|全部正确)")
EMBEDDED_CHOICE_LABEL_PATTERN = re.compile(r"(?:^|\s)A[.．、:：]\s*.+?\s+B[.．、:：]\s*.+?\s+C[.．、:：]\s*.+?\s+D[.．、:：]", re.DOTALL)
MATH_DELIMITER_PATTERN = re.compile(r"\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|\\\([\s\S]*?\\\)|\$(?!\$)[^$\n]+?\$")
RAW_MATH_PATTERN = re.compile(
    r"\\(?:frac|sqrt|tan|sin|cos|log|ln|theta|alpha|beta|pi|in|notin|leq|geq|neq|cdot|times|sum|prod|lim|vec|overline|begin|end)\b|"
    r"(?<![A-Za-z0-9])[A-Za-z](?:\([^\n()]{0,30}\))?\s*[\^_]\s*(?:\{[^{}]+\}|[-+A-Za-z0-9]+)|"
    r"[A-Za-z](?:\([^()\n]{1,30}\))?\s*[=<>≤≥]\s*[-+A-Za-z0-9(]|[A-Za-z][²³⁴]|"
    r"(?<![A-Za-z])[A-Za-z]\([^()\n]{1,20}\)|[\[(][-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?[\])]"
)
CHOICE_LABEL_ONLY_ANSWER_PATTERN = re.compile(
    r"^\s*[A-F](?:\s*[,，、/|;；]?\s*[A-F])*\s*$",
    re.IGNORECASE,
)
TEXT_ANSWER_QUESTION_TYPES = {
    "term_explanation", "short_answer", "essay", "calculation", "programming", "case_analysis",
}
HIGH_SCHOOL_MATH_PATTERN = re.compile(
    r"(?:高中|高一|高二|高三|必修|选择性必修|高考|普通高中).*数学|"
    r"数学.*(?:高中|高一|高二|高三|必修|选择性必修|高考|普通高中)"
)
DEFINITION_ONLY_STEM_PATTERN = re.compile(
    r"(?:什么是|定义是|概念是|含义是|称为|主要概念|基本概念|核心概念|下列关于.+(?:概念|定义).+正确)"
)
ANSWER_LEAK_PATTERN = re.compile(
    r"(?:(?<![A-Za-z])answer(?![A-Za-z])|final\s+answer|参考答案|正确答案|答案)\s*[:：]",
    re.IGNORECASE,
)

GENERATION_HARD_RULES = """
这些规则为强制规则：
1. 题干直接考查概念、原理、技术、方法、计算或应用，必须是脱离资料原文仍能独立作答的正式试题。
2. 题干禁止使用“本书”、“这本书”、“教材中”、“资料中”、“文中”、“上述内容”、“上下文中”、“知识库中”或“原文中”等资料指代语。
3. 严格按 type_counts 给出每种题型的数量，不得擅自改换题型。
4. 每道题必须有非空 answer 和非空 analysis；编程设计题的 answer 必须包含参考代码。
5. 保持精简：客观题 analysis 限制1至2句且不超过80个汉字，source_summary 不超过50个汉字，选项不写无关背景。只有简答、论述、计算、编程和案例题才输出 scoring_points。
6. 题目可以考查相同知识点，也可以采用相似结构，但题干、条件数据和最终设问不能与“禁止重复题干”完全相同；同一批候选不得生成完全一样的题目。
7. 名词解释题必须直接询问概念的定义、含义、核心特征或作用；options 必须为空数组，answer 必须是完整的中文文字解释，绝对不能填 A、B、C、D 等选项字母。
8. requirements.subject_instruction 是当前课程的学科命题规范，必须执行；知识库用于提供考点、公式、定理和典型方法，不要求照抄原文或原题数值。
9. 选择题的stem只能写题干，严禁把A/B/C/D选项拼进stem；所有选项只能写入options数组。
10. 知识库例题只能用于确认考点和方法，禁止照抄。新题至少改变“参数数据、表达形式、问题情境、条件组合、设问角度”中的两项，同时保持课程范围、解题依据和目标难度不变。
11. stem中只能出现题目条件和设问，严禁写入“answer:”、“答案：”、“参考答案：”或任何解题结果；答案只能放在answer字段。
12. 凡使用LaTeX，必须保证分隔符、花括号、left/right以及begin/end环境成对且可完整渲染；矩阵必须写成完整的`\\begin{bmatrix}...\\end{bmatrix}`。
""".strip()

HIGH_SCHOOL_MATH_INSTRUCTION = """
按中国普通高中数学教材、校内考试和高考常见风格命题：
1. 除非用户明确选择“名词解释题”或“判断题”，禁止把“什么是、定义、概念、性质是什么”作为题目主体。
2. 题目必须给出具体且充分的数学条件，要求考生求值、求范围、解方程或不等式、研究函数性质、证明结论、分析图形或解决实际问题。
3. 单选题和多选题也必须经过计算、推理、数形结合或条件判断才能作答，不能只凭背诵教材原句作答；干扰项应对应常见运算或推理错误。
4. 填空题答案应是数值、集合、区间、解析式、坐标、概率或明确结论；计算题和解答题必须给出关键步骤，不能只写最终答案。
5. 必须严格执行 requirements.difficulty_instruction。当前整体难度已上调：简单题也不能是直接套公式的一步题，中等题须达到原困难题水平，困难题须达到压轴或特难题水平。
6. 可以在不改变考点和解法依据的前提下重新设计数字、函数或情境，但必须自行验算，保证条件充分、答案唯一或完整。
7. 所有数学变量、函数、算式、区间和符号必须统一写在 LaTeX 行内标记 `\\(...\\)` 中，例如“已知函数 \\(f(x)=x^2-4x+3\\)，求其最小值。”；禁止直接输出 x^2，禁止裸露 \\frac、\\tan、\\underline 或 \\hspace。
8. 输出前必须独立重算一遍，并把最终答案代回原条件检查；解析中应体现关键验算。若普通题需要复杂近似值才能作答，应重新选择参数，使结果能用整数、分数、根式、常用角或简洁区间准确表示。
9. 不得混淆连续变化与离散变化、增长率与增长倍数、“至少”与“至多”、定义域与值域。实际应用题必须明确模型和取值范围；若知识片段不足以保证情境严谨，改出纯数学题。
10. 教材提供的是知识边界和典型方法，不是待复制的题库。每道新题至少采用两种变式方式，例如换参数并换设问、换表示并增加条件、换情境并调整推理路径；不得仅替换一个数字后复述教材例题。
11. 题型格式统一：选择题题干只写设问，选项只放入 options；填空题题干末尾只保留一个“________。”；解答题直接写“求、证明或解答”，不得添加括号空白或 LaTeX 下划线命令。
""".strip()

DIFFICULTY_INSTRUCTIONS = {
    "简单": "达到过去中等题水平：至少需要2个有效步骤，必须理解条件后选择方法，不能直接背概念或一步代入公式。",
    "较易": "介于新的简单与中等之间：至少2至3步推理，并包含一次条件转换、辨析或计算检查。",
    "中等": "达到过去困难题水平：至少3个有效步骤，综合同章或相邻的2个知识点，设置有质量的干扰条件或隐含转换。直接求集合交并、直接代入、直接求普通二次函数最值、只套一个排列组合公式，一律判为简单题，不得生成。",
    "较难": "接近压轴题水平：至少3至4步推理，包含分类讨论、参数分析、数形结合、实验数据综合或复杂情境迁移。",
    "困难": "达到特难题或压轴题水平：至少4个相互关联的关键步骤，综合多个知识点并设置关键突破口；必须包含参数讨论、分类讨论、存在性、综合建模或多问递进之一，难但必须严谨可解，不超出课程范围。",
}

GENERAL_DIFFICULTY_INSTRUCTIONS = {
    "简单": "达到过去中等题水平：需要理解知识后完成至少一次判断、解释、操作或应用，不能只凭关键词背诵作答。",
    "较易": "至少包含两个相关判断点，或要求把知识用于代码、材料、案例、实验现象和具体情境。",
    "中等": "达到过去困难题水平：选择题应结合代码、材料、案例、数据或条件关系进行分析；主观题应包含比较、解释原因、纠错、设计或迁移应用。名词解释题应回答定义、核心特征及适用边界，不能只写一句同义改写。",
    "较难": "接近综合题水平：综合两个相关知识点，包含多条件分析、方案比较、故障定位、因果推理或复杂情境迁移。",
    "困难": "达到压轴或综合实践题水平：综合多个知识点，要求完成方案设计、论证评价、复杂调试、实验设计或多问递进；难但必须有充分材料且不超出课程范围。",
}

VARIATION_STRATEGIES = [
    "改变设问方向：不要再求同一个量，改为求参数范围、成立条件、反推条件或判断结论。",
    "改变信息呈现：把直接公式改成图像、表格、分段条件、文字关系或多个对象比较。",
    "改变推理路径：设计需要分类讨论、数形结合、逆向推理或反证排除的题目。",
    "改变条件组合：加入一个同章知识点形成两步以上综合，不得只替换系数或常数。",
    "改变任务类型：围绕常见错误设置辨析、纠错、补充条件或选择正确推导过程。",
    "改变应用情境：把知识放入真实但数据完整的情境，并要求建立模型后求解。",
    "改变对象关系：从单个对象求值改为比较两个对象、研究变化或讨论存在性与唯一性。",
    "改变结论层次：先得到中间结论，再利用它解决第二问或选择最终结论。",
]

DIFFICULTY_COMPLEXITY_THRESHOLDS = {
    "简单": 18,
    "较易": 26,
    "中等": 34,
    "较难": 44,
    "困难": 54,
}

GENERAL_DIFFICULTY_COMPLEXITY_THRESHOLDS = {
    "简单": 12,
    "较易": 16,
    "中等": 20,
    "较难": 28,
    "困难": 36,
}

SHALLOW_QUESTION_PATTERN = re.compile(
    r"(?:集合.+(?:交集|并集|元素个数).*(?:多少|等于)|"
    r"函数.+(?:ax\^?2|x\^?2|二次函数).*(?:最大值|最小值)(?:为|是|多少)|"
    r"直接代入|根据定义可知|下列哪项是.+定义)"
)


def question_complexity_score(data):
    """用稳定的结构特征估计题目实际思考量，防止模型虚标难度。"""
    stem = str(data.get("stem", "")).strip()
    qtype = data.get("type") or data.get("question_type")
    compact = normalize_question_text(stem)
    score = min(20, 5 + len(compact) // 4)
    options = data.get("options") or []
    option_text = " ".join(str(item.get("content", "")) for item in options)
    # 非数学选择题的思考量经常主要体现在代码、材料和四个判断项中，
    # 不能只按一句简短的题干评分。
    if data.get("_subject_style") != "high_school_math" and option_text:
        average_option_length = sum(len(normalize_question_text(item.get("content", ""))) for item in options) // max(1, len(options))
        score += min(14, average_option_length // 3)
        score += min(10, len(re.findall(r"(?:代码|输出|运行|错误|原因|影响|适用|比较|案例|材料|数据|结果|方案|实验|情境)", option_text)) * 2)
    condition_count = len(re.findall(r"(?:若.+?则|且|同时|满足|其中|并且|分别|给出|在.+?条件下|当.+?时)", stem))
    score += min(18, condition_count * 6)
    relation_count = len(re.findall(r"(?:=|<|>|≤|≥|∈|∉|\\leq|\\geq|\\neq)", stem))
    score += min(15, relation_count * 3)
    score += min(12, len(MATH_DELIMITER_PATTERN.findall(stem)) * 4)
    advanced_count = len(re.findall(
        r"(?:参数|取值范围|恒成立|存在性|唯一性|任意|所有|至少|至多|分类讨论|数形结合|反证|证明|"
        r"比较|评价|纠错|补充条件|推导过程|建立模型|实验设计|数据分析|方案设计|原因及影响|进一步)",
        stem,
    ))
    score += min(24, advanced_count * 8)
    subtask_count = len(re.findall(r"(?:（[一二三四五六七八九十\d]+）|\([一二三四五六七八九十\d]+\))", stem))
    score += min(12, subtask_count * 5)
    if qtype in {"calculation", "case_analysis", "programming", "essay"}:
        score += 8
    elif qtype == "short_answer":
        score += 5
    if SHALLOW_QUESTION_PATTERN.search(stem):
        score -= 16
    if DEFINITION_ONLY_STEM_PATTERN.search(stem) and qtype not in {"term_explanation", "judge"}:
        score -= 20
    return max(0, min(100, score))


def difficulty_quality_issues(data):
    requested = str(data.get("_requested_difficulty") or "")
    qtype = data.get("type") or data.get("question_type")
    # 名词解释和判断题由题型本身限制了题干结构，难度主要体现在答案维度
    # 或判断边界中，不能用题干长度、公式数量等指标硬性拦截。
    if qtype in {"term_explanation", "judge"}:
        return []
    thresholds = (
        DIFFICULTY_COMPLEXITY_THRESHOLDS
        if data.get("_subject_style") == "high_school_math"
        else GENERAL_DIFFICULTY_COMPLEXITY_THRESHOLDS
    )
    threshold = thresholds.get(requested)
    if threshold is None:
        return []
    score = question_complexity_score(data)
    if score >= threshold:
        return []
    return [f"题目实际复杂度{score}分，未达到{requested}题最低要求{threshold}分；需要增加条件综合、设问变化或推理步骤"]


def difficulty_instruction_for(difficulty, subject_style, question_type):
    instructions = DIFFICULTY_INSTRUCTIONS if subject_style == "high_school_math" else GENERAL_DIFFICULTY_INSTRUCTIONS
    instruction = instructions.get(difficulty, instructions["中等"])
    if question_type == "term_explanation":
        instruction += " 当前题型是名词解释，题干可以直接询问术语，但答案必须覆盖定义、核心特征、作用或适用边界，不得只写一句同义改写。"
    elif question_type == "judge":
        instruction += " 当前题型是判断题，应考查容易混淆的适用条件或结论边界，并在解析中指出成立或不成立的关键依据。"
    return instruction

GENERAL_EXAM_INSTRUCTION = """
按当前学科的正式课程考试风格命题，知识库用于确定考点和解题依据，不得把段落直接改写成概念问答：
1. 除非用户选择名词解释题或判断题，题目必须提供问题、任务、材料、数据、代码、实验现象或具体情境，要求分析、推理、计算、比较、设计、纠错或应用。
2. 单选题和多选题也要让考生运用知识作答；干扰项应对应常见误解、错误步骤或不完整结论，不能只考查某句话是否背熟。
3. 中等及以上难度至少包含两个有意义的思考步骤，可合理综合同章或相邻知识点，但不得引入课程范围外的偏题怪题。
4. 答案必须从题干条件和知识依据中推出；输出前独立作答并检查题干、答案、解析三者一致，不能虚构知识库没有提供的事实。
5. 如果检索内容只有定义，应把该知识放入应用场景、辨析任务或具体问题中考查；证据不足以支持复杂题时应降低复杂度，而不是编造材料。
""".strip()

PROGRAMMING_EXAM_INSTRUCTION = """
这是计算机或编程课程。优先命制代码阅读、运行结果分析、补全代码、调试纠错、算法设计、复杂度比较和真实需求实现题。题干提供必要代码、输入和约束；答案应可执行或可验证。除名词解释题外，不得只问术语定义或语法作用。
""".strip()

SCIENCE_EXAM_INSTRUCTION = """
这是理工或实验类课程。优先命制计算、实验设计、数据/图表分析、现象解释、条件变化推理和综合应用题。必须给全单位、条件和有效数据，答案要验算或核对量纲；除名词解释题外，不得只问公式或概念的原文表述。
""".strip()

HUMANITIES_EXAM_INSTRUCTION = """
这是语言或人文社科课程。优先提供短材料、语境、史料、观点或案例，要求概括、比较、论证、评价、因果分析或迁移应用。答案必须引用题干材料并结合知识依据形成分析，不能只让考生复述定义。
""".strip()

LANGUAGE_EXAM_INSTRUCTION = """
这是语文或外语课程。优先命制语境辨析、阅读理解、信息提取、表达效果分析、语言运用、翻译或写作任务。题干应提供完成任务所需的语段或语境；客观题干扰项应对应常见理解偏差，主观题答案应给出依据和表达要点。
""".strip()

MEDICAL_EXAM_INSTRUCTION = """
这是医学、护理、药学或健康类课程。优先使用信息充分的病例、操作流程、指标变化或用药情境，考查判断依据、机制分析、步骤选择和风险识别。不得编造知识库之外的诊疗事实；题目仅用于课程学习与考试，不替代真实医疗决策。
""".strip()

PRACTICAL_EXAM_INSTRUCTION = """
这是实践、职业技能或工程操作类课程。优先命制流程排序、故障排查、方案选择、规范操作、安全判断、质量评价和真实任务设计题。题干必须给出必要条件和约束，答案应可检查、可执行或可按评分点评价。
""".strip()

TYPE_GENERATION_RULES = {
    "single_choice": {"options_example": [{"label": "A", "content": "选项A"}, {"label": "B", "content": "选项B"}, {"label": "C", "content": "选项C"}, {"label": "D", "content": "选项D"}], "answer_example": ["B"], "correct_answer_count": 1, "math_rule": "必须通过计算或推理选择结果，不能直接询问概念定义"},
    "multiple_choice": {"options_example": [{"label": "A", "content": "选项A"}, {"label": "B", "content": "选项B"}, {"label": "C", "content": "选项C"}, {"label": "D", "content": "选项D"}], "answer_example": ["A", "C"], "minimum_correct_answers": 2},
    "judge": {"options": [], "answer_allowed": [["正确"], ["错误"]]},
    "fill_blank": {"options": [], "answer": "每个空格对应一个数组元素", "math_rule": "填写数值、区间、解析式或明确数学结论"},
    "term_explanation": {
        "options": [],
        "stem_rule": "直接询问一个名词或概念的定义、含义、特征或作用",
        "answer_example": ["用完整的文字说明概念定义、核心特征及必要的适用范围。"],
        "forbidden_answer_examples": [["A"], ["A", "B"], ["ABCD"]],
    },
    "calculation": {"options": [], "answer": "必须包含完整结果", "analysis": "必须给出关键计算、推理或证明步骤"},
    "short_answer": {"options": [], "answer": "必须给出完整结论", "math_rule": "数学课程中按解答题或证明题命制并给出步骤"},
    "programming": {"options": [], "answer": "必须包含可读的参考代码"},
}


def is_high_school_math_course(course_or_name, grade=""):
    """根据课程名称、年级和简介识别中国高中数学课程。"""
    if hasattr(course_or_name, "name"):
        text = " ".join(
            str(value or "")
            for value in (
                course_or_name.name,
                getattr(course_or_name, "grade", ""),
                getattr(course_or_name, "description", ""),
            )
        )
    else:
        text = f"{course_or_name or ''} {grade or ''}"
    compact = re.sub(r"\s+", "", text)
    return bool(HIGH_SCHOOL_MATH_PATTERN.search(compact) or ("数学" in compact and any(token in compact for token in ("函数", "几何", "代数", "概率", "必修"))))


def course_profile_text(course_or_name, grade=""):
    if hasattr(course_or_name, "name"):
        values = (course_or_name.name, getattr(course_or_name, "grade", ""), getattr(course_or_name, "description", ""), getattr(course_or_name, "major", ""))
    else:
        values = (course_or_name, grade)
    return re.sub(r"\s+", "", " ".join(str(value or "") for value in values)).lower()


def resolve_subject_style(config, course):
    requested = str(config.get("subject_style", "auto") or "auto").lower()
    if requested in {"high_school_math", "gaokao_math"}:
        return "high_school_math"
    if requested in {"general", "exam_oriented", "knowledge"}:
        return "exam_oriented"
    return "high_school_math" if is_high_school_math_course(course) else "exam_oriented"


def subject_instruction_for(course, subject_style):
    if subject_style == "high_school_math":
        return HIGH_SCHOOL_MATH_INSTRUCTION
    text = course_profile_text(course)
    instruction = GENERAL_EXAM_INSTRUCTION
    if any(token in text for token in ("python", "java", "c++", "编程", "程序", "算法", "数据结构", "软件", "计算机", "人工智能", "机器学习", "agent")):
        instruction += "\n\n" + PROGRAMMING_EXAM_INSTRUCTION
    elif any(token in text for token in ("医学", "临床", "护理", "药学", "药理", "病理", "解剖", "生理", "健康", "康复")):
        instruction += "\n\n" + MEDICAL_EXAM_INSTRUCTION
    elif any(token in text for token in ("物理", "化学", "生物", "电子", "电路", "机械", "工程", "统计", "线性代数", "科学", "实验")):
        instruction += "\n\n" + SCIENCE_EXAM_INSTRUCTION
    elif any(token in text for token in ("语文", "英语", "日语", "俄语", "法语", "德语", "外语", "语言", "文学", "写作", "阅读")):
        instruction += "\n\n" + LANGUAGE_EXAM_INSTRUCTION
    elif any(token in text for token in ("职业", "技能", "实训", "工艺", "操作", "维修", "安全", "施工", "制造", "设计")):
        instruction += "\n\n" + PRACTICAL_EXAM_INSTRUCTION
    elif any(token in text for token in ("历史", "政治", "地理", "经济", "管理", "法律", "法学", "哲学", "社会", "教育", "心理")):
        instruction += "\n\n" + HUMANITIES_EXAM_INSTRUCTION
    return instruction


def build_course_question_blueprint(course, retrieved, config):
    """根据当前课程资料建立专属命题蓝图，而不是让所有课程共用一套题路。"""
    desired_count = min(15, max(6, int(config.get("count", 1)) // 8))
    evidence, seen = [], set()
    for item in retrieved:
        content = re.sub(r"\s+", " ", str(item.get("content", ""))).strip()
        signature = normalize_question_text(content[:160])
        if not content or not signature or signature in seen:
            continue
        seen.add(signature)
        evidence.append({"chunk_id": item.get("chunk_id"), "file_name": item.get("file_name", ""), "content": content[:900]})
        if len(evidence) >= 18:
            break
    schema = {
        "type": "object",
        "properties": {
            "course_identity": {"type": "string"},
            "learning_goals": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 8},
            "topic_plans": {
                "type": "array", "minItems": desired_count, "maxItems": desired_count,
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "knowledge_scope": {"type": "string"},
                        "question_approaches": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
                    },
                    "required": ["topic", "knowledge_scope", "question_approaches"],
                },
            },
        },
        "required": ["course_identity", "learning_goals", "topic_plans"],
    }
    prompt = {
        "course": {"name": course.name, "grade": getattr(course, "grade", ""), "major": getattr(course, "major", ""), "description": getattr(course, "description", "")},
        "desired_topic_count": desired_count,
        "requirements": [
            "只从课程资料提炼互不重复、可以独立命题的课程主题",
            "每个主题给出该课程特有的命题思路，不写适用于所有课程的空泛表述",
            "覆盖资料中的不同章节、方法、任务或能力，禁止多个主题围绕同一个术语",
            "命题思路说明怎样设置材料、数据、代码、实验、案例、计算、比较、纠错或设计任务",
        ],
        "evidence": evidence,
    }
    try:
        return OllamaService().chat_json(
            [{"role": "system", "content": "你是课程命题负责人。根据当前课程资料制定该课程独有的命题蓝图，输出严格JSON。"}, {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            config["chat_model"], "course_question_blueprint", schema,
        )
    except Exception as exc:
        logger.warning("课程%s命题蓝图生成失败，使用资料片段轮换方案: %s", course.id, exc)
        plans = [{"topic": f"课程主题{index + 1}", "knowledge_scope": item["content"][:120], "question_approaches": ["根据该资料片段设置具体应用任务", "改变条件和设问形成不同变式"]} for index, item in enumerate(evidence[:desired_count])]
        while len(plans) < desired_count:
            plans.append({"topic": f"课程主题{len(plans) + 1}", "knowledge_scope": course.name, "question_approaches": ["理解与应用", "分析与判断"]})
        return {"course_identity": course.name, "learning_goals": ["理解课程知识", "运用课程知识解决问题"], "topic_plans": plans}


def generation_correction_instruction(question_type):
    """按当前题型给模型补充纠错规则。

    过去这里无论用户选什么题型，都会追加“单选题必须有ABCD”，
    会误导小模型把名词解释题也生成字母答案。
    """
    common = "本批只能生成一种题型，每道题的type必须与requirements.type完全一致。"
    rules = {
        "single_choice": "必须有A、B、C、D四个非空且不重复的选项，answer只能包含一个正确选项字母，题干不得暗示多个正确答案。",
        "multiple_choice": "必须有A、B、C、D四个非空且不重复的选项，answer至少包含两个正确选项字母。",
        "judge": "options必须为空数组，answer只能是[“正确”]或[“错误”]。",
        "fill_blank": "options必须为空数组，answer按空格顺序填写明确的文字答案。",
        "term_explanation": "名词解释题应直接询问概念的定义、含义、特征或作用；options必须为空数组；answer必须填完整的文字解释，禁止使用A、B、C、D或ABCD等选项字母。",
        "programming": "options必须为空数组，answer必须包含可读的参考代码，scoring_points必须给出评分要点。",
    }
    fallback = "options必须为空数组，answer必须是完整的文字答案，不能使用选项字母代替。"
    return f"{common}{rules.get(question_type, fallback)}"

def question_batch_schema(question_type, count):
    """为Ollama构造题型级JSON Schema，从请求层限制选项和答案数量。"""
    choice = question_type in {"single_choice", "multiple_choice"}
    option_schema = {
        "type": "array",
        "minItems": 4 if choice else 0,
        "maxItems": 4 if choice else 0,
        "items": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": ["A", "B", "C", "D"]},
                "content": {"type": "string", "minLength": 1},
            },
            "required": ["label", "content"],
        },
    }
    answer_schema = {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}
    if question_type == "single_choice":
        answer_schema.update({"maxItems": 1, "uniqueItems": True})
        answer_schema["items"] = {"type": "string", "enum": ["A", "B", "C", "D"]}
    elif question_type == "multiple_choice":
        answer_schema.update({"minItems": 2, "maxItems": 4, "uniqueItems": True})
        answer_schema["items"] = {"type": "string", "enum": ["A", "B", "C", "D"]}
    elif question_type == "judge":
        answer_schema.update({"maxItems": 1})
        answer_schema["items"] = {"type": "string", "enum": ["正确", "错误"]}
    elif question_type == "term_explanation":
        # 名词解释应是完整文字，不是一个选项字母。
        answer_schema["items"] = {"type": "string", "minLength": 4}
    question_schema = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": [question_type]},
            "stem": {"type": "string", "minLength": 1},
            "options": option_schema,
            "answer": answer_schema,
            "analysis": {"type": "string", "minLength": 1},
            "scoring_points": {"type": "array", "items": {"type": "string"}},
            "difficulty": {"type": "string", "enum": list(DIFFICULTIES)},
            "score": {"type": "number", "exclusiveMinimum": 0},
            "knowledge_point": {"type": "string"},
            "chapter": {"type": "string"},
            "source_summary": {"type": "string"},
            "source_chunk_ids": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["type", "stem", "options", "answer", "analysis", "scoring_points", "difficulty", "score", "knowledge_point", "chapter", "source_summary", "source_chunk_ids"],
    }
    return {
        "type": "object",
        "properties": {"questions": {"type": "array", "minItems": count, "maxItems": count, "items": question_schema}},
        "required": ["questions"],
    }

def normalize_question_text(stem):
    """统一题干用于去重。

    空格、中英文标点和填空下划线不应让同一道题逃过 Hash 检查。
    """
    return re.sub(r"[\W_]+", "", str(stem).lower(), flags=re.UNICODE)


def question_hash(stem):
    normalized = normalize_question_text(stem)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def question_text_similarity(first, second):
    """计算题干的字符级相似度，用于拦截只换少量词语的近似题。"""
    left, right = normalize_question_text(first), normalize_question_text(second)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def strip_embedded_choice_options(stem, options):
    """移除模型偶尔附加在题干末尾的 A/B/C/D 选项文本。"""
    text = str(stem or "").strip()
    option_map = {str(item.get("label", "")).upper(): str(item.get("content", "")).strip() for item in (options or [])}
    if not all(option_map.get(label) for label in "ABCD"):
        return text
    pieces = []
    for label in "ABCD":
        content_pattern = r"\s*".join(re.escape(part) for part in re.split(r"\s+", option_map[label]) if part)
        marker = rf"(?:{label}[.．、:：]|\({label}\)|（{label}）)"
        pieces.append(rf"{marker}\s*{content_pattern}")
    suffix = re.compile(r"\s*" + r"\s+".join(pieces) + r"\s*$", re.IGNORECASE | re.DOTALL)
    match = suffix.search(text)
    if not match:
        return text
    return text[:match.start()].rstrip(" ：:")


def repair_latex_escapes(text):
    """修复模型在JSON字符串中把LaTeX反斜杠误解为控制字符的情况。"""
    value = str(text or "")
    replacements = {
        "\x0crac": r"\frac",
        "\x08egin": r"\begin",
        "\x08eta": r"\beta",
        "\tan": r"\tan",
        "\text": r"\text",
        "\times": r"\times",
        "\theta": r"\theta",
        "\neq": r"\neq",
        "\nu": r"\nu",
        "\right": r"\right",
        "\rho": r"\rho",
        "\x0b ec": r"\vec",
    }
    for broken, repaired in replacements.items():
        value = value.replace(broken, repaired)
    return value


def latex_structure_issues(text):
    """检查会导致KaTeX直接显示原始命令的结构错误。"""
    value = repair_latex_escapes(text)
    if not re.search(r"\$|\\(?:\(|\)|\[|\]|begin\b|end\b|left\b|right\b)", value):
        return []

    issues = []
    outside_math = MATH_DELIMITER_PATTERN.sub("", value)
    if "$" in outside_math or re.search(r"\\(?:\(|\)|\[|\])", outside_math):
        issues.append("LaTeX数学分隔符不成对")

    environments = []
    environment_broken = False
    for match in re.finditer(r"\\(begin|end)\s*\{([^{}]+)\}", value):
        action, environment = match.groups()
        if action == "begin":
            environments.append(environment)
        elif not environments or environments.pop() != environment:
            environment_broken = True
            break
    if environments or environment_broken:
        issues.append("LaTeX的begin/end环境不完整或不匹配")

    if len(re.findall(r"\\left\b", value)) != len(re.findall(r"\\right\b", value)):
        issues.append("LaTeX的left/right括号不成对")

    brace_depth = 0
    braces_broken = False
    for match in re.finditer(r"(?<!\\)[{}]", value):
        if match.group(0) == "{":
            brace_depth += 1
        elif brace_depth == 0:
            braces_broken = True
            break
        else:
            brace_depth -= 1
    if brace_depth or braces_broken:
        issues.append("LaTeX花括号不成对")
    return issues


def normalize_fill_blank_stem(stem):
    """将模型的括号、LaTeX下划线等填空占位统一成一种展示格式。"""
    value = str(stem or "").strip()
    value = re.sub(
        r"\\underline\s*\{\s*\\hspace\s*\{[^{}]*\}\s*\}",
        "________",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\\\(\s*([^=()]+?)\s*=\s*________\s*\\\)", r"\\(\1\\) = ________", value)
    value = re.sub(r"(?:\\\(|\$)\s*_{3,}\s*(?:\\\)|\$)", "________", value)
    value = re.sub(r"[（(]\s*(?:_{0,12}|　*)\s*[）)](?=\s*[。．.!！?？]?$)", "________", value)
    value = re.sub(r"_{3,}", "________", value)
    if "________" not in value:
        value = value.rstrip("。．.!！?？ ") + "________"
    return value.rstrip("。．.!！?？ ") + "。"


def has_undelimited_math(text):
    """识别没有放入 LaTeX 分隔符的命令、上下标表达式。"""
    value = str(text or "")
    outside_math = MATH_DELIMITER_PATTERN.sub("", value)
    return bool(RAW_MATH_PATTERN.search(outside_math))


def normalize_math_delimiters(text):
    """把高中数学题中常见的 `$...$` 和裸公式统一成 `\(...\)`。"""
    value = repair_latex_escapes(text)
    protected = []

    def protect(match):
        token = match.group(0)
        if token.startswith("$$") or token.startswith(r"\["):
            expression = token[2:-2].strip()
            replacement = rf"\({expression}\)"
        elif token.startswith("$"):
            replacement = rf"\({token[1:-1].strip()}\)"
        else:
            replacement = token
        protected.append(replacement)
        return f"§{len(protected) - 1}§"

    value = MATH_DELIMITER_PATTERN.sub(protect, value)
    candidate_pattern = re.compile(r"[A-Za-z0-9\\{}\[\](),.，+\-*/^_=<>≤≥∈∉∪∩∞π√|°\s]+")

    def wrap_candidate(match):
        candidate = match.group(0)
        core = candidate.strip(" ,，")
        if not core:
            return candidate
        formula_like = bool(
            RAW_MATH_PATTERN.search(core)
            or re.search(r"[A-Za-z0-9)}\]]\s*(?:∈|∉|∪|∩|≤|≥|=|<|>)\s*", core)
            or re.search(r"[A-Za-z]\s*[+\-*/]\s*[A-Za-z0-9]", core)
        )
        if not formula_like:
            return candidate
        start = candidate.find(core)
        return f"{candidate[:start]}\\({core}\\){candidate[start + len(core):]}"

    value = candidate_pattern.sub(wrap_candidate, value)
    for index, token in enumerate(protected):
        value = value.replace(f"§{index}§", token)
    return value


def resembles_source_exercise(stem, evidence_items, threshold=0.9):
    """检测题干是否照抄知识库中的例题或只做了极轻微改写。"""
    candidate = normalize_question_text(stem)
    if len(candidate) < 16:
        return False
    for item in evidence_items or []:
        content = str(item.get("content", "")) if isinstance(item, dict) else str(item or "")
        normalized_content = normalize_question_text(content)
        if candidate in normalized_content:
            return True
        segments = re.split(r"[\n。！？!?；;]", content)
        for segment in segments:
            normalized_segment = normalize_question_text(segment)
            if not normalized_segment or not (len(candidate) * 0.55 <= len(normalized_segment) <= len(candidate) * 1.8):
                continue
            if SequenceMatcher(None, candidate, normalized_segment).ratio() >= threshold:
                return True
    return False


def candidate_quality_score(data, evidence_items=None, subject_style="general"):
    """使用确定性规则给候选题排序，先过滤明显问题，再让优质候选入库。"""
    item = normalize_generated_question({**data, "_subject_style": subject_style})
    score = 100.0
    score -= len(validate_question_structure(item)) * 30
    stem = str(item.get("stem", "")).strip()
    analysis = str(item.get("analysis", "")).strip()
    if resembles_source_exercise(stem, evidence_items or []):
        score -= 100
    if EMBEDDED_CHOICE_LABEL_PATTERN.search(stem):
        score -= 80
    if DEFINITION_ONLY_STEM_PATTERN.search(stem) and item.get("type") not in {"term_explanation", "judge"}:
        score -= 50
    if 18 <= len(stem) <= 260:
        score += 8
    if len(analysis) >= 25:
        score += 6
    if re.search(r"(?:已知|若|设|根据|给出|计算|求|证明|分析|判断|设计|编写|比较|解释|改正)", stem):
        score += 8
    return score


def rank_generation_candidates(items, evidence_items=None, subject_style="general"):
    normalized = [normalize_generated_question(item) for item in (items or []) if isinstance(item, dict)]
    return sorted(
        normalized,
        key=lambda item: candidate_quality_score(item, evidence_items, subject_style),
        reverse=True,
    )


def _symbolic_expression(value):
    text = repair_latex_escapes(value).strip().strip("$")
    text = text.replace("−", "-").replace("×", "*").replace("÷", "/").replace("π", "pi")
    text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", text)
    text = text.replace("^", "**")
    text = re.sub(r"(?<=\d)[，,。；;].*$", "", text)
    return text.strip()


def symbolic_answers_equivalent(first, second):
    """用SymPy比较数字、分数、根式和代数式；无法解析时安全返回False。"""
    left, right = _symbolic_expression(first), _symbolic_expression(second)
    if normalize_question_text(left) == normalize_question_text(right):
        return True
    try:
        from sympy import simplify
        from sympy.parsing.sympy_parser import (
            convert_xor,
            implicit_multiplication_application,
            parse_expr,
            standard_transformations,
        )
        transformations = standard_transformations + (implicit_multiplication_application, convert_xor)
        return simplify(parse_expr(left, transformations=transformations) - parse_expr(right, transformations=transformations)) == 0
    except Exception:
        return False


def independent_answers_consistent(question_type, expected, independent):
    expected_items = [str(value).strip() for value in (expected if isinstance(expected, list) else [expected]) if str(value).strip()]
    independent_items = [str(value).strip() for value in (independent if isinstance(independent, list) else [independent]) if str(value).strip()]
    if not expected_items or not independent_items:
        return False
    if question_type in {"single_choice", "multiple_choice"}:
        return {value.upper() for value in expected_items} == {value.upper() for value in independent_items}
    if question_type == "judge":
        return expected_items == independent_items
    if len(expected_items) == len(independent_items) and all(
        symbolic_answers_equivalent(left, right) for left, right in zip(expected_items, independent_items)
    ):
        return True
    left = normalize_question_text(" ".join(expected_items))
    right = normalize_question_text(" ".join(independent_items))
    return bool(left and right and SequenceMatcher(None, left, right).ratio() >= 0.82)


def question_variation_template(stem):
    """忽略开场措辞和具体数字，识别“只换说法/只换数字”的同模板题。"""
    text = repair_latex_escapes(stem).lower()
    text = MATH_DELIMITER_PATTERN.sub(lambda match: match.group(0).strip("$"), text)
    text = re.sub(r"(?<![a-z])(?:已知|若|设|给定|假设)(?![a-z])", "", text)
    text = re.sub(r"\d+(?:\.\d+)?", "#", text)
    text = re.sub(r"\\(?:left|right)", "", text)
    return normalize_question_text(text)


def question_core_text(stem):
    """去掉代码块和通用命题套话，保留题目真正要求完成的核心任务。"""
    text = repair_latex_escapes(stem).lower()
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(
        r"(?:下列|以下)(?:哪一?|哪个|哪种|哪项)(?:个)?(?:选项|说法|实现|描述|代码)?(?:是|能|可以)?(?:正确|合理|可行|满足要求)(?:的)?",
        "",
        text,
    )
    text = re.sub(r"^(?:已知|假设|给定|考虑|现有|在定义|若要|需要|请)(?:一个|两个|以下)?", "", text)
    text = re.sub(r"(?:请选择|选择正确答案|判断下列说法|最合适的是|正确的是)[。．.!！?？]*$", "", text)
    return normalize_question_text(text)


def question_core_similarity(first, second):
    """比较核心任务；最长公共片段可识别“同题外面多包一段背景/代码”的情况。"""
    left, right = question_core_text(first), question_core_text(second)
    if not left or not right or min(len(left), len(right)) < 14:
        return 0.0, 0.0
    matcher = SequenceMatcher(None, left, right)
    return matcher.ratio(), matcher.find_longest_match().size / min(len(left), len(right))


def find_generation_duplicate(stem, course_id, question_type, threshold=0.92, template_threshold=0.96, exclude_id=None, exact_only=False):
    """拦截完全相同、只换措辞或只换数字的同模板题，允许真正的变式题。"""
    digest = question_hash(stem)
    queryset = Question.objects.filter(
        course_id=course_id,
        question_type=question_type,
        is_deleted=False,
    )
    if exclude_id:
        queryset = queryset.exclude(pk=exclude_id)
    exact = queryset.filter(content_hash=digest).only("id", "stem").first()
    if exact:
        return {"question_id": exact.id, "stem": exact.stem, "similarity": 1.0, "match_type": "HASH"}
    if exact_only:
        return None
    best = None
    candidate_template = question_variation_template(stem)
    for question in queryset.only("id", "stem").order_by("-id")[:2000]:
        score = question_text_similarity(stem, question.stem)
        existing_template = question_variation_template(question.stem)
        template_score = SequenceMatcher(None, candidate_template, existing_template).ratio() if candidate_template and existing_template else 0.0
        core_score, core_containment = question_core_similarity(stem, question.stem)
        if score < threshold and template_score < template_threshold and core_score < 0.86 and core_containment < 0.78:
            continue
        metric = max(score, template_score, core_score, core_containment)
        if best is None or metric > best["metric"]:
            if template_score >= template_threshold:
                match_type = "TEMPLATE"
            elif core_score >= 0.86 or core_containment >= 0.78:
                match_type = "CORE_TASK"
            else:
                match_type = "TEXT"
            best = {
                "question_id": question.id,
                "stem": question.stem,
                "similarity": round(score, 4),
                "template_similarity": round(template_score, 4),
                "core_similarity": round(core_score, 4),
                "core_containment": round(core_containment, 4),
                "match_type": match_type,
                "metric": metric,
            }
    if best:
        best.pop("metric", None)
    return best


def generation_batch_budget(total, quality_mode, max_retries=2):
    """候选被质量校验淘汰是正常现象，为深度模式保留足够的换题与补题次数。"""
    multiplier = {"FAST": 2, "STANDARD": 3, "DEEP": 4}.get(str(quality_mode).upper(), 3)
    return min(400, max(10, int(total) * multiplier + int(max_retries) + 5))


def rotating_context(retrieved, batch_index, max_chars, window_size=8):
    """从较大的检索结果池中轮换取片段，避免每批都围绕同一小段文字出题。"""
    if not retrieved:
        return []
    size = min(len(retrieved), max(1, int(window_size)))
    start = (batch_index * size) % len(retrieved)
    ordered = [retrieved[(start + offset) % len(retrieved)] for offset in range(size)]
    selected, used_chars = [], 0
    for item in ordered:
        content = str(item.get("content", ""))
        if selected and used_chars + len(content) > max_chars:
            break
        selected.append(item)
        used_chars += len(content)
    return selected


def generation_topic_queries(config, course_name, course_grade=""):
    """把用户的多主题补充要求拆成可独立检索的查询。"""
    explicit = [config.get("knowledge_point_name"), config.get("chapter_name")]
    supplement = str(config.get("supplement", ""))
    supplement = re.sub(r"[【】\[\]]", "", supplement)
    supplement = re.sub(r"^需要", "", supplement.strip())
    supplement = re.sub(r"的相关(?:单项|多项|选择|判断|填空|简答|编程)?题$", "", supplement)
    parts = [*explicit, *re.split(r"[、，,;；\n]+", supplement)]
    topics = []
    for part in parts:
        topic = re.sub(r"\s+", " ", str(part or "")).strip(" ：:。")
        if 1 < len(topic) <= 40 and topic not in topics:
            topics.append(topic)
    resolved_style = str(config.get("resolved_subject_style") or config.get("subject_style") or "").lower()
    math_mode = resolved_style in {"high_school_math", "gaokao_math"}
    exam_mode = resolved_style in {"exam_oriented", "general", "knowledge"}
    math_mode = math_mode or (str(config.get("subject_style", "auto")).lower() == "auto" and is_high_school_math_course(course_name, course_grade))
    if topics:
        if math_mode:
            queries = []
            for topic in topics[:15]:
                queries.extend([f"{topic} 典型例题 求解 证明", f"{topic} 练习题 计算 解答"])
            return queries[:30]
        if exam_mode:
            queries = []
            for topic in topics[:15]:
                queries.extend([f"{topic} 典型例题 案例 应用", f"{topic} 练习题 分析 推理 实践"])
            return queries[:30]
        return topics[:30]
    if math_mode:
        return [
            f"{course_name} 典型例题 已知 求 解 证明",
            f"{course_name} 练习题 选择题 填空题 解答题",
            f"{course_name} 函数 方程 不等式 图像 最值",
        ]
    return [f"{course_name} 典型例题 案例 应用 练习题 分析推理 实验代码 材料数据 实践任务"]


def select_course_topic(topic_plans, question_type, target_count, topic_type_progress, topic_failure_counts, batch_index):
    """按题型配额选择下一个课程主题；重复或失败后优先切换到其他主题。"""
    topics = [str(plan.get("topic", "")).strip() for plan in topic_plans if str(plan.get("topic", "")).strip()]
    if not topics:
        return "", 0
    quota = max(1, (int(target_count) + len(topics) - 1) // len(topics))
    progress = topic_type_progress.get(question_type, {})
    failures = topic_failure_counts.get(question_type, {})

    def priority(item):
        index, topic = item
        completed = int(progress.get(topic, 0))
        failed = int(failures.get(topic, 0))
        rotation = (index - batch_index) % len(topics)
        return (completed >= quota, failed >= 3, completed, failed, rotation)

    _, topic = min(enumerate(topics), key=priority)
    return topic, quota


def focused_generation_context(retrieved, batch_index, max_chars, fallback_window_size=6, preferred_topic="", preferred_round=None):
    """每批聚焦一个检索主题，避免小模型在多个不相关片段中反复选最简单的题。"""
    if preferred_topic:
        topic_items = [item for item in retrieved if preferred_topic in str(item.get("retrieval_query", ""))]
        if topic_items:
            selected, used_chars = [], 0
            for item in topic_items:
                content = str(item.get("content", ""))
                if selected and used_chars + len(content) > max_chars:
                    break
                selected.append(item)
                used_chars += len(content)
            return selected, preferred_topic, int(preferred_round or 1)
        return rotating_context(retrieved, batch_index, max_chars, fallback_window_size), preferred_topic, int(preferred_round or 1)
    topic_order = list(dict.fromkeys(item.get("retrieval_query") for item in retrieved if item.get("retrieval_query")))
    if not topic_order:
        return rotating_context(retrieved, batch_index, max_chars, fallback_window_size), "课程核心内容", 1
    topic = topic_order[batch_index % len(topic_order)]
    topic_items = [item for item in retrieved if item.get("retrieval_query") == topic]
    selected, used_chars = [], 0
    for item in topic_items:
        content = str(item.get("content", ""))
        if selected and used_chars + len(content) > max_chars:
            break
        selected.append(item)
        used_chars += len(content)
    return selected, topic, batch_index // len(topic_order) + 1

def normalize_generated_question(data):
    """兼容本地模型常见的等价JSON写法，避免因纯格式差异重复调用模型。"""
    normalized = dict(data)
    for field in ("stem", "analysis", "source_summary", "knowledge_point", "chapter"):
        if field in normalized:
            normalized[field] = repair_latex_escapes(normalized[field])
    for field in ("answer", "scoring_points"):
        if isinstance(normalized.get(field), list):
            normalized[field] = [repair_latex_escapes(value) for value in normalized[field]]
    question_type = normalized.get("type") or normalized.get("question_type")
    if question_type == "fill_blank":
        normalized["stem"] = normalize_fill_blank_stem(normalized.get("stem", ""))
    options = normalized.get("options") or []
    if isinstance(options, dict):
        options = [{"label": label, "content": content} for label, content in options.items()]
    normalized_options = []
    for index, option in enumerate(options):
        if isinstance(option, str):
            normalized_options.append({"label": chr(65 + index), "content": option})
        elif isinstance(option, dict):
            normalized_options.append({
                "label": option.get("label") or option.get("标签") or option.get("选项") or chr(65 + index),
                "content": repair_latex_escapes(option.get("content", option.get("内容", option.get("text", option.get("value", ""))))),
            })
    options = normalized_options
    normalized["options"] = options
    if question_type in ("single_choice", "multiple_choice"):
        normalized["stem"] = strip_embedded_choice_options(normalized.get("stem", ""), options)
    if question_type in ("single_choice", "multiple_choice"):
        raw_answers = normalized.get("answer", [])
        if not isinstance(raw_answers, list): raw_answers = [raw_answers]
        answers = []
        for raw_answer in raw_answers:
            for label in re.findall(r"(?<![A-Z])[A-F](?![A-Z])", str(raw_answer).upper()):
                if label not in answers: answers.append(label)
        normalized["answer"] = answers
    elif question_type == "judge":
        normalized["options"] = []
        raw_answer = normalized.get("answer")
        if isinstance(raw_answer, list) and len(raw_answer) == 1: raw_answer = raw_answer[0]
        judge_map = {True: "正确", False: "错误", "对": "正确", "是": "正确", "错": "错误", "否": "错误", "true": "正确", "false": "错误"}
        normalized["answer"] = [judge_map.get(raw_answer, raw_answer)]
    else:
        # 非选择题不保存模型偶尔输出的空选项占位符。
        normalized["options"] = []
    if normalized.get("_subject_style") == "high_school_math":
        for field in ("stem", "analysis", "source_summary"):
            normalized[field] = normalize_math_delimiters(normalized.get(field, ""))
        normalized["options"] = [
            {**option, "content": normalize_math_delimiters(option.get("content", ""))}
            for option in normalized.get("options", [])
        ]
    return normalized

def validate_question_structure(data):
    issues = []
    qtype = data.get("type") or data.get("question_type")
    stem = str(data.get("stem", "")).strip()
    options = data.get("options") or []
    answer = data.get("answer")
    if not stem: issues.append("题干不能为空")
    if MATERIAL_REFERENCE_PATTERN.search(stem): issues.append("题干不能使用“本书、教材、资料或上下文”等来源指代语")
    if ANSWER_LEAK_PATTERN.search(stem): issues.append("题干不能包含answer、答案或参考答案，答案只能放在answer字段")
    latex_fields = [("题干", stem), ("解析", data.get("analysis", ""))]
    latex_fields.extend((f"选项{item.get('label', '')}", item.get("content", "")) for item in options)
    answer_items = answer if isinstance(answer, list) else [answer]
    latex_fields.extend(("答案", item) for item in answer_items if item is not None)
    for field_name, value in latex_fields:
        issues.extend(f"{field_name}{issue}" for issue in latex_structure_issues(value))
    if qtype not in QUESTION_TYPES: issues.append("题型不在支持范围内")
    if data.get("difficulty", "中等") not in DIFFICULTIES: issues.append("难度不合法")
    try:
        if float(data.get("score", 0)) <= 0: issues.append("分值必须大于0")
    except (ValueError, TypeError): issues.append("分值格式不正确")
    if qtype in ("single_choice", "multiple_choice"):
        labels = [str(o.get("label", "")).upper() for o in options]
        contents = [str(o.get("content", "")).strip() for o in options]
        answers = answer if isinstance(answer, list) else [answer]
        if len(options) < 4: issues.append("选择题至少需要四个选项")
        if any(not x for x in contents): issues.append("选项内容不能为空")
        if len(set(contents)) != len(contents): issues.append("选项内容不能重复")
        if any(str(a).upper() not in labels for a in answers): issues.append("答案必须属于已有选项")
        if qtype == "single_choice" and len(answers) != 1: issues.append("单选题只能有一个答案")
        if qtype == "single_choice" and SINGLE_MULTI_ANSWER_STEM_PATTERN.search(stem): issues.append("单选题不能使用“包括哪些”等多答案问法")
        if qtype == "multiple_choice" and len(answers) < 2: issues.append("多选题至少需要两个答案")
        if EMBEDDED_CHOICE_LABEL_PATTERN.search(stem): issues.append("题干中不能重复包含A/B/C/D选项，选项只能保存在options字段")
    if answer is None or answer == "" or answer == [] or (isinstance(answer, list) and not any(str(x).strip() for x in answer)):
        issues.append("必须提供参考答案")
    if not str(data.get("analysis", "")).strip(): issues.append("必须提供题目解析")
    if qtype == "judge" and answer not in (["正确"], ["错误"], "正确", "错误", True, False): issues.append("判断题答案只能是正确或错误")
    if qtype in TEXT_ANSWER_QUESTION_TYPES:
        answer_items = answer if isinstance(answer, list) else [answer]
        if any(CHOICE_LABEL_ONLY_ANSWER_PATTERN.fullmatch(str(item or "")) for item in answer_items):
            issues.append("非选择题必须提供完整文字答案，不能使用A/B/C/D等选项字母")
    if data.get("_subject_style") in {"high_school_math", "exam_oriented"} and qtype not in {"term_explanation", "judge"}:
        if DEFINITION_ONLY_STEM_PATTERN.search(stem):
            issues.append("正式考试题不能只考查概念或定义，必须设置具体任务并要求分析、推理、计算或应用")
    if data.get("_subject_style") == "high_school_math":
        math_fields = [("题干", stem)] + [(f"选项{item.get('label', '')}", item.get("content", "")) for item in options]
        for field_name, value in math_fields:
            if any(ord(char) < 32 and char not in "\n\r" for char in str(value or "")):
                issues.append(f"{field_name}包含损坏的数学转义字符")
            if has_undelimited_math(value):
                issues.append(f"{field_name}中的数学表达式必须统一写在\\(...\\)内")
        if re.search(r"\\(?:underline|hspace)\b", stem):
            issues.append("题干不能使用LaTeX下划线占位命令")
        if qtype == "fill_blank" and stem.count("________") != 1:
            issues.append("填空题题干末尾必须统一保留一个填空横线")
    issues.extend(difficulty_quality_issues(data))
    return issues

def distribute_question_types(question_types, total):
    """把总题数尽量平均分配给用户勾选的题型。"""
    selected = []
    for question_type in question_types or ["single_choice"]:
        if question_type in QUESTION_TYPES and question_type not in selected:
            selected.append(question_type)
    if not selected:
        selected = ["single_choice"]
    base, remainder = divmod(total, len(selected))
    return {question_type: base + (1 if index < remainder else 0) for index, question_type in enumerate(selected)}

def next_type_batch(type_targets, completed_counts, batch_size):
    """每批只生成一种题型，避免本地模型在同一JSON中混用多种结构。"""
    remaining = {key: max(0, target - completed_counts.get(key, 0)) for key, target in type_targets.items()}
    for question_type in type_targets:
        if remaining[question_type] > 0:
            return {question_type: min(batch_size, remaining[question_type])}
    return {}

def snapshot_question(question):
    return {"version": 1, "original_question_id": question.id, "question_type": question.question_type, "stem": question.stem, "options": [{"label": o.label, "content": o.content, "is_correct": o.is_correct} for o in question.options.all()], "answer": question.answer, "analysis": question.analysis, "scoring_points": question.scoring_points, "difficulty": question.difficulty, "score": float(question.score), "knowledge_point": question.knowledge_point.name if question.knowledge_point else "", "chapter": question.chapter.name if question.chapter else "", "source_summary": question.source_summary, "source_chunk_ids": question.source_chunk_ids}

@transaction.atomic
def create_question(course, data, task=None, source_type="AI"):
    if source_type == "AI": data = normalize_generated_question(data)
    issues = validate_question_structure(data)
    if issues: raise BusinessError(f"题目结构校验失败：{'；'.join(issues)}", 40041, data={"issues": issues})
    answer = data.get("answer", [])
    if not isinstance(answer, list): answer = [answer]
    question = Question.objects.create(course=course, chapter_id=data.get("chapter_id"), knowledge_point_id=data.get("knowledge_point_id"), generation_task=task, question_type=data.get("type") or data.get("question_type"), stem=data["stem"].strip(), answer=sorted(answer) if data.get("type") == "multiple_choice" else answer, analysis=data.get("analysis", ""), scoring_points=data.get("scoring_points", []), difficulty=data.get("difficulty", "中等"), score=data.get("score", 1), source_type=source_type, source_summary=data.get("source_summary", ""), source_chunk_ids=data.get("source_chunk_ids", []), grounding_score=data.get("grounding_score"), generation_model=task.model_name if task else "", review_status="PENDING" if source_type == "AI" else data.get("review_status", "APPROVED"), content_hash=question_hash(data["stem"]))
    answers = set(str(x).upper() for x in question.answer)
    QuestionOption.objects.bulk_create([QuestionOption(question=question, label=str(o["label"]).upper(), content=o["content"], is_correct=str(o["label"]).upper() in answers, sort_order=i) for i, o in enumerate(data.get("options", []))])
    review_issues = validate_question_structure(data)
    QuestionReview.objects.create(question=question, review_type="RULE", passed=not review_issues, score=100 if not review_issues else max(0, 100 - len(review_issues) * 15), issues=review_issues, suggestions=[])
    return question

def find_similar(stem, course_id=None, threshold=0.88, exclude_id=None):
    digest = question_hash(stem)
    qs = Question.objects.filter(is_deleted=False)
    if course_id: qs = qs.filter(course_id=course_id)
    if exclude_id: qs = qs.exclude(pk=exclude_id)
    exact = qs.filter(content_hash=digest).first()
    if exact: return [{"question_id": exact.id, "stem": exact.stem, "similarity": 1.0, "match_type": "HASH"}]
    matches = []
    for q in qs.only("id", "stem")[:1000]:
        score = question_text_similarity(stem, q.stem)
        if score >= threshold: matches.append({"question_id": q.id, "stem": q.stem, "similarity": round(score, 4), "match_type": "TEXT"})
    return sorted(matches, key=lambda x: -x["similarity"])

class GenerationService:
    def run(self, task):
        config = {**get_config(), **task.config}
        task.status = "RUNNING"; task.heartbeat_at = timezone.now(); task.attempt_count += 1; task.model_name = config["chat_model"]; task.embedding_model = config["embedding_model"]; task.save()
        try:
            subject_style = resolve_subject_style(config, task.course)
            config["resolved_subject_style"] = subject_style
            topic_queries = generation_topic_queries(config, task.course.name, task.course.grade)
            query = config.get("query") or topic_queries[0]
            total = int(task.total_count or config.get("count", 1))
            # 大批量出题需要更大的知识片段池。之后每批会轮换其中的片段，
            # 不再用固定 5 个片段支撑几十道题。
            retrieval_top_k = min(50, max(int(config.get("retrieval_top_k", 5)), total))
            retrieved = task.retrieved_chunks or []
            needs_topic_refresh = len(topic_queries) > 1 and not any(item.get("retrieval_query") for item in retrieved)
            if len(retrieved) < retrieval_top_k or needs_topic_refresh:
                filters = {"course_id": task.course_id, "file_id": config.get("file_id"), "chapter_id": config.get("chapter_id")}
                if len(topic_queries) > 1:
                    refreshed = VectorService().search_many(
                        topic_queries,
                        filters,
                        per_query=max(2, min(4, (retrieval_top_k + len(topic_queries) - 1) // len(topic_queries))),
                        threshold=float(config.get("similarity_threshold", 0.25)),
                        max_results=retrieval_top_k,
                    )
                else:
                    refreshed = VectorService().search(
                        query,
                        filters,
                        retrieval_top_k,
                        float(config.get("similarity_threshold", 0.25)),
                    )
                if refreshed:
                    retrieved = refreshed
            if not retrieved: raise BusinessError("没有检索到足够的知识库内容，请先完成文件解析或放宽检索条件。", 40042)
            if task.config.get("course_blueprint"):
                course_blueprint = task.config["course_blueprint"]
            elif total >= 8:
                course_blueprint = build_course_question_blueprint(task.course, retrieved, {**config, "count": total})
            else:
                course_blueprint = {
                    "course_identity": task.course.name,
                    "learning_goals": ["理解当前考点", "运用当前考点解决问题"],
                    "topic_plans": [],
                }
            topic_plans = course_blueprint.get("topic_plans") or []
            blueprint_queries = [
                f"{plan.get('topic', '')} {plan.get('knowledge_scope', '')} 例题 应用 分析 实践"
                for plan in topic_plans if str(plan.get("topic", "")).strip()
            ]
            if len(blueprint_queries) >= 2:
                blueprint_top_k = min(100, max(retrieval_top_k, len(blueprint_queries) * 3))
                refined = VectorService().search_many(
                    blueprint_queries,
                    {"course_id": task.course_id, "file_id": config.get("file_id"), "chapter_id": config.get("chapter_id")},
                    per_query=3,
                    threshold=float(config.get("similarity_threshold", 0.25)),
                    max_results=blueprint_top_k,
                )
                if refined:
                    retrieved = refined
            task.config = {**task.config, "course_blueprint": course_blueprint}
            config["course_blueprint"] = course_blueprint
            task.retrieved_chunks = retrieved
            task.save(update_fields=["config", "retrieved_chunks"])
            batch_size = int(config.get("batch_size", 5))
            configured_counts = config.get("type_counts") or {}
            if isinstance(configured_counts, dict) and configured_counts:
                type_targets = {key: int(value) for key, value in configured_counts.items() if key in QUESTION_TYPES and int(value) > 0}
            else:
                type_targets = distribute_question_types(config.get("question_types", ["single_choice"]), total)
            # 以实际写入数量为准。模型可能少返题目，Worker 中断后也可能已保存
            # 一部分结果；恢复时只补足缺少数量，不把“已请求”误当成“已成功”。
            task.success_count = min(total, Question.objects.filter(generation_task=task, is_deleted=False).count())
            task.failed_count = max(0, total - task.success_count)
            task.progress = min(99, int(task.success_count / total * 100))
            task.save(update_fields=["success_count", "failed_count", "progress"])
            failure_details = list(task.config.get("failure_details") or [])
            topic_type_progress = dict(task.config.get("topic_type_progress") or {})
            topic_failure_counts = dict(task.config.get("topic_failure_counts") or {})
            batches = 0
            # 正常批次数之外保留定向纠错机会，特别用于最后一道选择题。
            # 客观题为了稳定性最多每批保存2道，不能再用用户设置的大 batch_size
            # 计算总批数，否则“100道单选题”最多只会生成54道。
            # 新API任务都会显式写入质量模式；历史任务缺失该字段时保持旧的快速行为。
            quality_mode = str(config.get("quality_mode", "FAST")).upper()
            max_batches = generation_batch_budget(total, quality_mode, config.get("max_retries", 2))
            stagnant_batches = 0
            candidate_multiplier = {"FAST": 1, "STANDARD": 2, "DEEP": 3}.get(quality_mode, 2)
            while task.success_count < total and batches < max_batches:
                task.refresh_from_db(fields=["cancel_requested"])
                if task.cancel_requested: task.status = "CANCELLED"; task.finished_at = timezone.now(); task.save(); return
                existing_counts = Counter(Question.objects.filter(generation_task=task, is_deleted=False).values_list("question_type", flat=True))
                # 选择题的JSON字段多，2道一批在qwen2.5:7b上比4道一批更快且更稳定；
                # 编程、论述等长答案题也使用小批次。
                complex_types = {"programming", "essay", "calculation", "case_analysis"}
                remaining_by_type = {key: max(0, target - existing_counts.get(key, 0)) for key, target in type_targets.items()}
                pending_type = next((key for key in type_targets if remaining_by_type[key] > 0), None)
                if pending_type in {"single_choice", "multiple_choice"}:
                    effective_batch_size = min(batch_size, 4)
                elif pending_type in complex_types:
                    effective_batch_size = min(batch_size, 2)
                else:
                    effective_batch_size = batch_size
                # 标准/深度模式逐题生成多个候选并择优，避免小模型批量输出时质量快速下降。
                if quality_mode in {"STANDARD", "DEEP"}:
                    effective_batch_size = 1
                requested_types = next_type_batch(type_targets, existing_counts, min(effective_batch_size, total - task.success_count))
                count = sum(requested_types.values())
                if not count: break
                model_type_counts = {key: value * candidate_multiplier for key, value in requested_types.items()}
                # 快速模式只剩1道选择题时仍保留两个候选，避免结构错误导致整批失败。
                for choice_type in ("single_choice", "multiple_choice"):
                    if model_type_counts.get(choice_type) == 1:
                        model_type_counts[choice_type] = 2
                model_count = sum(model_type_counts.values())
                recent_failures = list(dict.fromkeys(item["reason"] for item in failure_details[-5:] if item.get("reason")))
                current_type = next(iter(model_type_counts))
                output_schema = question_batch_schema(current_type, model_count)
                preferred_topic, topic_quota = select_course_topic(
                    topic_plans,
                    current_type,
                    type_targets.get(current_type, 0),
                    topic_type_progress,
                    topic_failure_counts,
                    batches,
                )
                topic_completed = int(topic_type_progress.get(current_type, {}).get(preferred_topic, 0)) if preferred_topic else 0
                topic_failed = int(topic_failure_counts.get(current_type, {}).get(preferred_topic, 0)) if preferred_topic else 0
                batch_context, focus_topic, focus_round = focused_generation_context(
                    retrieved,
                    batches,
                    int(config.get("max_context_chars", 12000)),
                    int(config.get("generation_context_chunks", 6)),
                    preferred_topic,
                    topic_completed + topic_failed + 1,
                )
                current_topic_plan = next(
                    (plan for plan in topic_plans if str(plan.get("topic", "")).strip() and str(plan.get("topic")) in focus_topic),
                    {},
                )
                context = "\n\n".join(f"[片段ID:{x['chunk_id']}] {x['content']}" for x in batch_context)
                task_stems = list(
                    Question.objects.filter(
                        generation_task=task,
                        question_type=current_type,
                        is_deleted=False,
                    ).order_by("id").values_list("stem", flat=True)[:80]
                )
                rejected_stems = [item.get("stem") for item in failure_details[-20:] if item.get("stem")]
                forbidden_stems = list(dict.fromkeys(
                    str(stem)[:220] for stem in [*rejected_stems, *task_stems] if str(stem).strip()
                ))[-80:]
                subject_instruction = subject_instruction_for(task.course, subject_style)
                requested_difficulty = config.get("difficulty", "中等")
                enforced_difficulty = requested_difficulty if "difficulty" in task.config else ""
                variation_strategy = VARIATION_STRATEGIES[(batches + max(0, task.attempt_count - 1) * 3) % len(VARIATION_STRATEGIES)]
                variation_seed = 1009 + task.id * 97 + batches * 53 + task.attempt_count * 211
                user_prompt = json.dumps({"requirements": {"type": current_type, "types": [current_type], "type_counts": model_type_counts, "type_rules": {current_type: TYPE_GENERATION_RULES.get(current_type, {"options": []})}, "count": model_count, "difficulty": requested_difficulty, "difficulty_instruction": difficulty_instruction_for(requested_difficulty, subject_style, current_type), "score": config.get("score", 2), "scenario": config.get("scenario", "课堂练习"), "strict": config.get("strict", True), "subject_style": subject_style, "subject_instruction": subject_instruction, "course_blueprint": {"course_identity": course_blueprint.get("course_identity", task.course.name), "learning_goals": course_blueprint.get("learning_goals", []), "topic_names": [plan.get("topic") for plan in topic_plans]}, "current_topic_plan": current_topic_plan, "topic_quota": topic_quota, "topic_completed": topic_completed, "candidate_instruction": f"这是候选题生成阶段。为实际需要的每1道题生成{candidate_multiplier}个不同候选，后端将按结构、原创性、任务完整性和解析质量择优，只保存最优候选。三个候选必须分别侧重：改变设问、改变条件组合、改变推理路径；禁止只换开场措辞或只替换一个数字。", "generate_answer": True, "generate_analysis": True, "supplement": config.get("supplement", ""), "focus_topic": focus_topic, "focus_round": focus_round, "variation_seed": variation_seed, "required_variation_strategy": variation_strategy, "forbidden_duplicate_stems": forbidden_stems, "diversity_instruction": f"本批只围绕“{focus_topic}”命题，并严格采用current_topic_plan中的课程专属命题思路。该题型在本主题最多保留{topic_quota or '不限'}道，目前已保留{topic_completed}道。若previous_validation_failures出现重复，必须更换任务场景、输入条件和最终设问，不能复述失败题。与已有题相比至少改变条件结构、数据关系、情境、设问目标、解法路径中的两项。本轮强制变式：{variation_strategy} 这是该主题第{focus_round}轮命题。", "previous_validation_failures": recent_failures, "correction_instruction": generation_correction_instruction(current_type)}, "output_schema": output_schema, "knowledge_context": context}, ensure_ascii=False)
                system_prompt = f"{get_prompt('question_generation', '你是严谨的教师。只能根据知识库上下文生成题目，输出严格JSON，不输出Markdown。')}\n\n{GENERATION_HARD_RULES}"
                result = OllamaService().chat_json([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], task.model_name, "question_generation", output_schema)
                generated_items = result.get("questions", [])
                if not isinstance(generated_items, list) or not generated_items:
                    failure_details.append({"batch": batches + 1, "question_type": "", "reason": "模型未返回可用的questions数组"})
                    generated_items = []
                for generated_item in generated_items:
                    if isinstance(generated_item, dict):
                        generated_item["_subject_style"] = subject_style
                        generated_item["_requested_difficulty"] = enforced_difficulty
                generated_items = rank_generation_candidates(generated_items, batch_context, subject_style)
                success_before_batch = task.success_count
                for item in generated_items[:model_count]:
                    question_type = item.get("type") or item.get("question_type")
                    if question_type not in requested_types:
                        failure_details.append({"batch": batches + 1, "question_type": str(question_type or ""), "reason": f"模型返回了未请求的题型：{question_type or '未标注'}"})
                        logger.warning("任务%s忽略非请求题型: %s", task.id, question_type)
                        continue
                    if requested_types[question_type] <= 0:
                        # 只剩1道选择题时会要求模型返回2个候选，用满后的备用题不是失败。
                        continue
                    # 题型数量、难度和分值由用户配置决定，不信任模型偶尔返回的0分或错误难度。
                    item["score"] = config.get("score", 2)
                    item["difficulty"] = config.get("difficulty", "中等")
                    item["_subject_style"] = subject_style
                    item["_requested_difficulty"] = enforced_difficulty
                    item = normalize_generated_question(item)
                    if resembles_source_exercise(item.get("stem", ""), batch_context):
                        failure_details.append({"batch": batches + 1, "question_type": str(question_type), "stem": str(item.get("stem", ""))[:200], "reason": "题目与知识库例题过于相似，未达到举一反三要求"})
                        continue
                    allowed_chunk_ids = {int(x["chunk_id"]) for x in batch_context}
                    model_chunk_ids = []
                    for raw_chunk_id in item.get("source_chunk_ids") or []:
                        try:
                            chunk_id = int(raw_chunk_id)
                        except (TypeError, ValueError):
                            continue
                        if chunk_id in allowed_chunk_ids and chunk_id not in model_chunk_ids:
                            model_chunk_ids.append(chunk_id)
                    item["source_chunk_ids"] = model_chunk_ids or sorted(allowed_chunk_ids)
                    try:
                        duplicate = find_generation_duplicate(
                            item.get("stem", ""),
                            task.course_id,
                            question_type,
                            0.92,
                            exact_only=True,
                        )
                        if duplicate:
                            reason = f"题目与#{duplicate['question_id']}完全相同"
                            failure_details.append({"batch": batches + 1, "question_type": str(question_type), "stem": str(item.get("stem", ""))[:200], "reason": reason})
                            logger.info("任务%s跳过重复题: %s", task.id, item.get("stem", ""))
                            continue
                        create_question(task.course, item, task=task)
                        task.success_count += 1
                        requested_types[question_type] -= 1
                        if preferred_topic:
                            type_progress = topic_type_progress.setdefault(question_type, {})
                            type_progress[preferred_topic] = int(type_progress.get(preferred_topic, 0)) + 1
                    except Exception as exc:
                        failure_details.append({"batch": batches + 1, "question_type": str(question_type or ""), "reason": str(exc)})
                        logger.warning("任务%s题目保存失败: %s", task.id, exc)
                batches += 1
                if task.success_count == success_before_batch:
                    stagnant_batches += 1
                    if preferred_topic:
                        type_failures = topic_failure_counts.setdefault(current_type, {})
                        type_failures[preferred_topic] = int(type_failures.get(preferred_topic, 0)) + 1
                else:
                    stagnant_batches = 0
                    if preferred_topic:
                        topic_failure_counts.setdefault(current_type, {})[preferred_topic] = 0
                task.failed_count = max(0, total - task.success_count)
                task.config = {
                    **task.config,
                    "failure_details": failure_details[-20:],
                    "topic_type_progress": topic_type_progress,
                    "topic_failure_counts": topic_failure_counts,
                }
                task.progress = min(99, int(task.success_count / total * 100)); task.heartbeat_at = timezone.now()
                # 只更新本批的进度字段，避免用Worker内存中的旧值
                # 覆盖API刚写入的cancel_requested=True。
                task.save(update_fields=["success_count", "failed_count", "config", "progress", "heartbeat_at"])
                # 连续多批全是重复题或结构错误时及时停止，避免本地模型无效循环消耗时间。
                stagnant_limit = max(12, min(30, (len(topic_plans) or 6) * 2))
                if stagnant_batches >= stagnant_limit:
                    failure_details.append({"batch": batches, "question_type": str(current_type), "reason": f"已轮换{stagnant_limit}个主题批次仍未产生新题，已停止无效重试"})
                    task.config = {**task.config, "failure_details": failure_details[-20:]}
                    task.save(update_fields=["config"])
                    break
            if task.success_count >= total:
                task.status = "SUCCESS"; task.progress = 100; task.failed_count = 0; task.error_message = ""
            else:
                task.status = "FAILED"
                task.failed_count = max(0, total - task.success_count)
                reason_counts = Counter(item["reason"] for item in failure_details[-20:] if item.get("reason"))
                summary = "；".join(f"{reason}（{count}次）" for reason, count in reason_counts.most_common(3))
                task.error_message = f"要求生成{total}道，已成功{task.success_count}道，还缺{task.failed_count}道。" + (f"最近未通过校验的原因：{summary}。" if summary else "模型未返回足够的合格题目。") + "点击重试只会补齐缺少的题目。"
            task.finished_at = timezone.now(); task.save()
        except Exception as exc:
            task.refresh_from_db(fields=["cancel_requested", "status"])
            if task.cancel_requested or task.status == "CANCELLED":
                task.status = "CANCELLED"
                task.finished_at = task.finished_at or timezone.now()
                task.save(update_fields=["status", "finished_at"])
                return
            task.status = "FAILED"; task.failed_count = max(0, task.total_count - task.success_count); task.error_message = str(exc); task.finished_at = timezone.now(); task.save(); logger.exception("生成任务%s失败", task.id)

def ai_review(question):
    context = "\n".join(__import__("apps.knowledge.models", fromlist=["TextChunk"]).TextChunk.objects.filter(id__in=question.source_chunk_ids).values_list("content", flat=True))
    data = snapshot_question(question)
    result = OllamaService().chat_json([{"role": "system", "content": get_prompt("question_review", "严格根据知识库审核题目，输出passed、score、issues、suggestions和revised_question。")}, {"role": "user", "content": json.dumps({"context": context, "question": data}, ensure_ascii=False)}], get_config()["review_model"], "question_review")
    score = float(result.get("score", 0)); passed = bool(result.get("passed")) and score >= 80
    review = QuestionReview.objects.create(question=question, review_type="AI", passed=passed, score=score, issues=result.get("issues", []), suggestions=result.get("suggestions", []), revised_question=result.get("revised_question"), model_name=get_config()["review_model"])
    question.ai_review_score = score; question.review_status = "PENDING" if passed else "NEEDS_REVISION"; question.save()
    return review
