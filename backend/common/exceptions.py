import logging
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.views import exception_handler
from .response import api_response

logger = logging.getLogger(__name__)

class BusinessError(Exception):
    def __init__(self, message, code=40001, http_status=400, data=None):
        self.message, self.code, self.http_status, self.data = message, code, http_status, data
        super().__init__(message)

def custom_exception_handler(exc, context):
    request = context.get("request")
    if isinstance(exc, BusinessError):
        return api_response(exc.data, exc.message, exc.code, exc.http_status, request)
    if isinstance(exc, DjangoValidationError):
        return api_response(getattr(exc, "message_dict", None), str(exc), 40002, 400, request)
    response = exception_handler(exc, context)
    if response is not None:
        message = "请求参数不正确"
        if isinstance(response.data, dict):
            detail = response.data.get("detail")
            message = str(detail or next(iter(response.data.values()), message))
        return api_response(response.data, message, 40000 + response.status_code, response.status_code, request)
    logger.exception("未处理异常", exc_info=exc)
    return api_response(None, "系统处理失败，请查看后端日志获取详情。", 50000, status.HTTP_500_INTERNAL_SERVER_ERROR, request)
