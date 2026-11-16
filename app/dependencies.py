"""FastAPI dependencies (dependency injection)."""

from fastapi import Request

from app.services.posting_service import PostingService


def get_posting_service(request: Request) -> PostingService:
    """The PostingService is built once at startup (see ``main.lifespan``).

    Tests can replace it with ``app.dependency_overrides[get_posting_service]``.
    """
    return request.app.state.posting_service
