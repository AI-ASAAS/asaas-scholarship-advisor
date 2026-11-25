"""FastAPI HTTP router for the scoped scholarship advisor assistant."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from core.config import settings
from modules.assistant.schemas import (
    AssistantAskRequest,
    AssistantAskResponse,
    AssistantStatusResponse,
)
from modules.assistant.service import AssistantService
from modules.auth.schemas import StudentPrincipal
from modules.auth.service import get_optional_student, issue_student_session
from modules.llm.client import AsyncLLMClient, LLMError, get_llm
from modules.students.service import StudentService
from utils.rate_limit import RateLimiter, get_client_ip

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

assistant_session_limiter = RateLimiter(
    limit=settings.ASSISTANT_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)
assistant_ip_limiter = RateLimiter(
    limit=settings.ASSISTANT_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)


def _assistant_configured(llm: AsyncLLMClient) -> bool:
    api_key = (settings.LLM_API_KEY or "").strip()
    if api_key and not api_key.startswith("tvly-"):
        return True
    return bool(getattr(llm, "_configured", False))


@router.get("/status", response_model=AssistantStatusResponse)
def get_assistant_status(
    request: Request,
    llm: AsyncLLMClient = Depends(get_llm),
) -> AssistantStatusResponse:
    principal = get_optional_student(request)
    st = StudentService().get_status(principal.session_id if principal else None)
    return AssistantStatusResponse(
        enabled=settings.ASSISTANT_ENABLED,
        configured=_assistant_configured(llm),
        student_authenticated=bool(st["authenticated"]),
        has_consent=bool(st["has_consent"]),
        has_profile=bool(st["profile_exists"]),
    )


@router.post("", response_model=AssistantAskResponse)
async def ask_assistant(
    payload: AssistantAskRequest,
    request: Request,
    response: Response,
    llm: AsyncLLMClient = Depends(get_llm),
) -> AssistantAskResponse:
    if not settings.ASSISTANT_ENABLED or not _assistant_configured(llm):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "المساعد الذكي غير متاح حالياً؛ يرجى التأكد من تفعيله وضبط المزوّد.",
                "code": "ASSISTANT_UNAVAILABLE",
            },
        )

    principal = get_optional_student(request)
    if principal is None or not principal.session_id:
        # Anonymous conversation session (read-only tools until consent; deleted via delete-my-data)
        principal = issue_student_session(response)

    client_ip = get_client_ip(request, settings.trusted_proxies)
    limit = settings.ASSISTANT_RATE_LIMIT_PER_HOUR
    assistant_session_limiter.check(f"assistant:sid:{principal.session_id}", limit=limit, window_seconds=3600)
    assistant_ip_limiter.check(f"assistant:ip:{client_ip}", limit=limit, window_seconds=3600)

    service = AssistantService(llm)
    try:
        return await service.ask(principal, payload)
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "تعذّر الاتصال بخدمة المساعد الذكي حالياً؛ يرجى المحاولة مرة أخرى.",
                "code": "LLM_UNAVAILABLE",
            },
        ) from exc
