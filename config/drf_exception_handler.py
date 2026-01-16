from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        return Response(
            {
                "code": "SERVER_ERROR",
                "message": "An unexpected error occurred.",
                "details": None,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = "SERVER_ERROR"
    message = "An unexpected error occurred."
    details = response.data

    if isinstance(exc, ValidationError):
        code = "VALIDATION_ERROR"
        message = "Validation error."
    elif isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        code = "FORBIDDEN"
        message = "Permission denied."
    elif isinstance(exc, (NotFound, Http404)):
        code = "NOT_FOUND"
        message = "Resource not found."
    elif response.status_code == status.HTTP_400_BAD_REQUEST:
        code = "VALIDATION_ERROR"
        message = "Validation error."
    elif response.status_code == status.HTTP_403_FORBIDDEN:
        code = "FORBIDDEN"
        message = "Permission denied."
    elif response.status_code == status.HTTP_404_NOT_FOUND:
        code = "NOT_FOUND"
        message = "Resource not found."

    response.data = {
        "code": code,
        "message": message,
        "details": details,
    }
    return response
