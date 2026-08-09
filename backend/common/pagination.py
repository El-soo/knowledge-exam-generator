from rest_framework.pagination import PageNumberPagination
from .response import api_response

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    def get_paginated_response(self, data):
        return api_response({"items": data, "total": self.page.paginator.count, "page": self.page.number, "page_size": self.get_page_size(self.request), "pages": self.page.paginator.num_pages}, request=self.request)
