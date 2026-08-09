import json
import re

def parse_model_json(text):
    if not text or not str(text).strip():
        raise ValueError("模型返回了空内容")
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", str(text).strip(), flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
        if not starts:
            raise ValueError("模型未返回可识别的JSON")
        start = min(starts)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end <= start:
            raise ValueError("模型返回的JSON不完整")
        return json.loads(cleaned[start:end + 1])
