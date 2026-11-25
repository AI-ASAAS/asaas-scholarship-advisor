"""FastAPI HTTP router for profile strengthening (Capability 6) and document help (Capability 7)."""

from __future__ import annotations

import asyncio
import os
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from core.config import settings
from modules.auth.schemas import StudentPrincipal
from modules.auth.service import require_student
from modules.documents.extractor import DocumentExtractionError, extract_text_from_base64_file
from modules.documents.schemas import (
    DocumentDraftUpdateRequest,
    DocumentExtractFileRequest,
    DocumentExtractFileResponse,
    DocumentGenerateRequest,
    DocumentGenerateResponse,
    DocumentSaveRequest,
    SavedDocumentDraftResponse,
    SavedDocumentListResponse,
    StrengtheningRequest,
    StrengtheningResponse,
)
from modules.documents.service import DocumentsService
from modules.llm.client import AsyncLLMClient, LLMError, get_llm
from utils.rate_limit import RateLimiter

router = APIRouter(prefix="/api/documents", tags=["documents"])
_service = DocumentsService()

documents_rate_limiter = RateLimiter(
    limit=settings.DOCUMENTS_RATE_LIMIT_PER_HOUR,
    window_seconds=3600,
)


def _require_consent(student: StudentPrincipal) -> str:
    if not student.session_id or not student.has_consent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "الموافقة الصريحة على الخصوصية مطلوبة لاستخدام أدوات التطوير والمستندات.",
                "code": "CONSENT_REQUIRED",
            },
        )
    return student.session_id


@router.post("/strengthening", response_model=StrengtheningResponse)
async def get_strengthening_plan(
    payload: StrengtheningRequest,
    student: StudentPrincipal = Depends(require_student),
    llm: AsyncLLMClient = Depends(get_llm),
) -> StrengtheningResponse:
    sid = _require_consent(student)
    if getattr(llm, "_configured", False):
        documents_rate_limiter.check(
            f"docs_strengthen:{sid}",
            limit=settings.DOCUMENTS_RATE_LIMIT_PER_HOUR,
            window_seconds=3600,
        )
    try:
        return await _service.strengthen_profile(session_id=sid, request=payload, llm=llm)
    except ValueError as exc:
        if str(exc) == "PROFILE_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "يرجى حفظ ملفك الشخصي أولاً قبل طلب خطة تقوية الملف.",
                    "code": "PROFILE_NOT_FOUND",
                },
            ) from exc
        raise
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "تعذّر الاتصال بمزوّد الذكاء الاصطناعي حالياً؛ يرجى المحاولة لاحقاً.",
                "code": "LLM_UNAVAILABLE",
            },
        ) from exc


@router.post("/extract-file", response_model=DocumentExtractFileResponse)
async def extract_uploaded_document(
    payload: DocumentExtractFileRequest,
    student: StudentPrincipal = Depends(require_student),
) -> DocumentExtractFileResponse:
    sid = _require_consent(student)
    documents_rate_limiter.check(
        f"docs_extract:{sid}",
        limit=settings.DOCUMENTS_RATE_LIMIT_PER_HOUR,
        window_seconds=3600,
    )
    try:
        extracted_text, truncated = await asyncio.to_thread(
            extract_text_from_base64_file,
            payload.filename,
            payload.content_base64,
        )
    except DocumentExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc), "code": "FILE_EXTRACTION_ERROR"},
        ) from exc
    safe_name = os.path.basename(payload.filename.strip()) or "document"
    return DocumentExtractFileResponse(
        doc_type=payload.doc_type,
        filename=safe_name,
        extracted_text=extracted_text,
        char_count=len(extracted_text),
        truncated=truncated,
    )


@router.post("/generate", response_model=DocumentGenerateResponse)
async def generate_document_draft(
    payload: DocumentGenerateRequest,
    student: StudentPrincipal = Depends(require_student),
    llm: AsyncLLMClient = Depends(get_llm),
) -> DocumentGenerateResponse:
    sid = _require_consent(student)
    documents_rate_limiter.check(
        f"docs_generate:{sid}",
        limit=settings.DOCUMENTS_RATE_LIMIT_PER_HOUR,
        window_seconds=3600,
    )
    if not getattr(llm, "_configured", False) and not (settings.LLM_API_KEY or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "خدمة صياغة المستندات غير مهيأة حالياً (مفتاح المزوّد غير مضبوط).",
                "code": "LLM_UNAVAILABLE",
            },
        )
    try:
        return await _service.generate_draft(session_id=sid, request=payload, llm=llm)
    except ValueError as exc:
        if str(exc) == "PROFILE_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "يرجى حفظ ملفك الشخصي أولاً قبل صياغة المستندات.",
                    "code": "PROFILE_NOT_FOUND",
                },
            ) from exc
        raise HTTPException(status_code=422, detail={"message": str(exc), "code": "VALIDATION_ERROR"}) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "المنحة المحددة غير موجودة أو غير منشورة.", "code": "GRANT_NOT_FOUND"},
        ) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "تعذّر توليد المسودة حالياً؛ يرجى إعادة المحاولة.",
                "code": "LLM_UNAVAILABLE",
            },
        ) from exc


@router.get("", response_model=SavedDocumentListResponse)
def list_saved_documents(
    student: StudentPrincipal = Depends(require_student),
) -> SavedDocumentListResponse:
    sid = _require_consent(student)
    drafts = _service.list_saved_drafts(sid)
    return SavedDocumentListResponse(count=len(drafts), drafts=drafts)


@router.post("", response_model=SavedDocumentDraftResponse, status_code=status.HTTP_201_CREATED)
def save_document_draft(
    payload: DocumentSaveRequest,
    student: StudentPrincipal = Depends(require_student),
) -> SavedDocumentDraftResponse:
    sid = _require_consent(student)
    return _service.save_draft(sid, payload)


@router.patch("/{draft_id}", response_model=SavedDocumentDraftResponse)
def update_saved_document(
    draft_id: int,
    payload: DocumentDraftUpdateRequest,
    student: StudentPrincipal = Depends(require_student),
) -> SavedDocumentDraftResponse:
    sid = _require_consent(student)
    updated = _service.update_saved_draft(sid, draft_id, payload)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "المسودة غير موجودة.", "code": "DRAFT_NOT_FOUND"},
        )
    return updated


@router.delete("/{draft_id}")
def delete_saved_document(
    draft_id: int,
    student: StudentPrincipal = Depends(require_student),
) -> dict:
    sid = _require_consent(student)
    if not _service.delete_saved_draft(sid, draft_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "المسودة غير موجودة.", "code": "DRAFT_NOT_FOUND"},
        )
    return {"deleted": True, "id": draft_id}


@router.get("/{draft_id}/export")
def export_saved_document(
    draft_id: int,
    student: StudentPrincipal = Depends(require_student),
) -> Response:
    sid = _require_consent(student)
    exported = _service.get_draft_for_export(sid, draft_id)
    if exported is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "المسودة غير موجودة.", "code": "DRAFT_NOT_FOUND"},
        )
    filename, content = exported
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
