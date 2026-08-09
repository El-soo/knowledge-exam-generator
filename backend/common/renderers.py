from rest_framework.renderers import JSONRenderer

class UnifiedJSONRenderer(JSONRenderer):
    """为DRF默认的增删改查响应补上统一信封，已封装的响应保持不变。"""
    def render(self, data, accepted_media_type=None, renderer_context=None):
        if not (isinstance(data, dict) and {"code", "message", "data", "request_id"}.issubset(data.keys())):
            context = renderer_context or {}
            request = context.get("request")
            status_code = getattr(context.get("response"), "status_code", 200)
            data = {"code": 0 if status_code < 400 else 40000 + status_code, "message": "success" if status_code < 400 else "request failed", "data": data, "request_id": getattr(request, "request_id", "")}
        return super().render(data, accepted_media_type, renderer_context)
