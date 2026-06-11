from django.shortcuts import render

from common.project_selection import resolve_current_project
from common.signals import ensure_initial_reference_data

from .models import Document


DOCUMENT_TYPES = [
    {"code": "DOC_SRS", "label": "사용자 요구사항 정의서"},
    {"code": "DOC_ITF", "label": "사용자 인터페이스 설계서"},
    {"code": "DOC_ARCH", "label": "아키텍처 설계서"},
    {"code": "DOC_ERD", "label": "엔티티 관계 모형 설계서"},
    {"code": "DOC_DB", "label": "데이터베이스 설계서"},
    {"code": "DOC_TS", "label": "통합 시험 시나리오"},
]
DOCUMENT_TYPE_MAP = {item["code"]: item for item in DOCUMENT_TYPES}
DEFAULT_DOCUMENT_CODE = DOCUMENT_TYPES[0]["code"]


def _resolve_document_code(raw_code):
    return raw_code if raw_code in DOCUMENT_TYPE_MAP else DEFAULT_DOCUMENT_CODE


def _build_document_history_rows(queryset):
    return [
        {
            "sn": document.sn,
            "type_name": getattr(document.document_type, "name", "-") or "-",
            "creator_name": getattr(document.created_by, "name", "-") or "-",
            "version": document.version or "-",
            "modification_content": document.modification_content or "-",
            "created_at": document.created_at,
        }
        for document in queryset
    ]


def document_history_list(request):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)
    document_code = _resolve_document_code(request.GET.get("docs_cd"))
    selected_document = DOCUMENT_TYPE_MAP[document_code]

    documents = Document.objects.none()
    if current_project is not None:
        documents = (
            Document.objects.filter(
                project=current_project,
                document_type_id=document_code,
            )
            .select_related("document_type", "created_by")
            .order_by("-created_at", "-sn")
        )

    document_rows = _build_document_history_rows(documents)
    context = {
        "active_menu": "doc_history",
        "title": f"{selected_document['label']} 버전 이력",
        "current_project": current_project,
        "documents": document_rows,
        "has_documents": bool(document_rows),
        "selected_document_code": document_code,
        "selected_document_label": selected_document["label"],
    }
    return render(request, "docs/doc_history_list.html", context)
