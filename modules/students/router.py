"""FastAPI HTTP router for anonymous student identity, consent, profile, export, and deletion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from modules.auth.schemas import StudentPrincipal
from modules.auth.service import (
    clear_student_cookie,
    get_optional_student,
    issue_student_session,
    require_student,
)
from modules.students.schemas import (
    ConsentRecordRequest,
    StudentDeleteResponse,
    StudentExportResponse,
    StudentProfileResponse,
    StudentProfileUpsertRequest,
    StudentSessionStartRequest,
    StudentSessionStatusResponse,
)
from modules.students.service import ConsentRequiredError, StudentService

router = APIRouter(prefix="/api/students", tags=["students"])
_service = StudentService()


@router.post("/session", response_model=StudentSessionStatusResponse)
def start_student_session(
    request: Request,
    response: Response,
    payload: StudentSessionStartRequest | None = None,
) -> StudentSessionStatusResponse:
    """Create or resume an HttpOnly opaque student session; optionally record consent."""
    principal = get_optional_student(request)
    if principal is None or not principal.session_id:
        principal = issue_student_session(response)

    if payload and payload.consent_accepted:
        _service.record_consent(
            principal.session_id,  # type: ignore[arg-type]
            consent_version=payload.consent_version,
            scopes=payload.scopes,
        )

    st = _service.get_status(principal.session_id)
    return StudentSessionStatusResponse(**st)


@router.get("/me", response_model=StudentSessionStatusResponse)
def get_student_session_status(request: Request) -> StudentSessionStatusResponse:
    """Return current student session, consent, and profile existence state."""
    principal = get_optional_student(request)
    st = _service.get_status(principal.session_id if principal else None)
    return StudentSessionStatusResponse(**st)


@router.post("/consent", response_model=StudentSessionStatusResponse)
def accept_student_consent(
    payload: ConsentRecordRequest,
    request: Request,
    response: Response,
) -> StudentSessionStatusResponse:
    """Record explicit privacy consent; initializes a student session if needed."""
    principal = get_optional_student(request)
    if principal is None or not principal.session_id:
        principal = issue_student_session(response)

    _service.record_consent(
        principal.session_id,  # type: ignore[arg-type]
        consent_version=payload.consent_version,
        scopes=payload.scopes,
    )
    st = _service.get_status(principal.session_id)
    return StudentSessionStatusResponse(**st)


@router.get("/profile", response_model=StudentProfileResponse)
def get_student_profile(
    student: StudentPrincipal = Depends(require_student),
) -> StudentProfileResponse:
    profile = _service.get_profile(student.session_id)  # type: ignore[arg-type]
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "لم تقم بحفظ ملفك الشخصي بعد.",
                "code": "PROFILE_NOT_FOUND",
            },
        )
    return profile


@router.put("/profile", response_model=StudentProfileResponse)
def upsert_student_profile(
    payload: StudentProfileUpsertRequest,
    request: Request,
    response: Response,
) -> StudentProfileResponse:
    """Create or update the student profile; requires active or inline consent."""
    principal = get_optional_student(request)
    if principal is None or not principal.session_id:
        if payload.consent_accepted is not True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "يجب الموافقة الصريحة على سياسة الخصوصية قبل حفظ الملف.",
                    "code": "CONSENT_REQUIRED",
                },
            )
        principal = issue_student_session(response)

    try:
        return _service.save_profile(principal.session_id, payload)  # type: ignore[arg-type]
    except ConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": str(exc), "code": "CONSENT_REQUIRED"},
        )


@router.get("/export", response_model=StudentExportResponse)
def export_student_data(
    student: StudentPrincipal = Depends(require_student),
) -> StudentExportResponse:
    return _service.export_data(student.session_id)  # type: ignore[arg-type]


@router.delete("/data", response_model=StudentDeleteResponse)
def delete_student_data(
    response: Response,
    student: StudentPrincipal = Depends(require_student),
) -> StudentDeleteResponse:
    result = _service.delete_data(student.session_id)  # type: ignore[arg-type]
    clear_student_cookie(response)
    return result
