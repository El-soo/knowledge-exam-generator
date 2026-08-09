from rest_framework.response import Response

def api_response(data=None, message="success", code=0, status=200, request=None):
    request_id = getattr(request, "request_id", "") if request else ""
    return Response({"code": code, "message": message, "data": data, "request_id": request_id}, status=status)
