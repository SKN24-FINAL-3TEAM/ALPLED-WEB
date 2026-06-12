from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from common.project_selection import resolve_current_project
from common.signals import ensure_initial_reference_data
from files.services import (
    SEARCH_FIELD_CHOICES,
    apply_file_filters,
    build_project_file_rows,
    get_file_type_choices,
)

from .models import Document, DocumentApproval
from .services import (
    acquire_document_lock,
    apply_approval_filters,
    apply_meeting_notes,
    approve_request,
    build_approval_queryset,
    build_approval_rows,
    build_consistency_review,
    build_document_detail_url,
    build_document_rows,
    build_editor_config,
    build_generation_redirect_url,
    build_generation_steps,
    build_history_preview_url,
    can_access_initial_generation,
    cancel_approval_request,
    clear_generation_state,
    confirm_document,
    create_approval_request,
    download_remote_content,
    ensure_generation_draft,
    extract_text_from_docx,
    get_actor,
    get_approval_status_choices,
    get_current_generation_code,
    get_detail_by_sn,
    get_document_label,
    get_document_type_choices,
    get_document_view_state,
    get_generation_progress_rows,
    get_generation_selected_files,
    get_generation_state,
    get_latest_detail,
    get_project_files,
    is_generation_complete,
    is_project_manager,
    is_project_participant,
    latest_confirmed_document,
    mark_generation_confirmed,
    parse_callback_payload,
    reject_request,
    release_document_lock,
    resolve_document_code,
    restore_revision,
    save_generation_state,
    save_revision,
    update_generation_selected_files,
    validate_document_content_token,
)


def _get_document_or_404(project, document_sn):
    queryset = Document.objects.select_related(
        "project",
        "document_type",
        "created_by",
        "updated_by",
        "user",
    )
    if project is not None:
        queryset = queryset.filter(project=project)
    return get_object_or_404(queryset, sn=document_sn)


def _get_document_by_sn_or_404(document_sn):
    return get_object_or_404(
        Document.objects.select_related(
            "project",
            "document_type",
            "created_by",
            "updated_by",
            "user",
        ),
        sn=document_sn,
    )


def _ensure_document_access(project, actor, document):
    if project is None or document.project_id != project.sn:
        raise Http404
    if not is_project_participant(project, actor):
        raise Http404


def _collect_prefixed_filters(request, prefix):
    return {
        "file_type": request.GET.get(f"{prefix}file_type", "all"),
        "field": request.GET.get(f"{prefix}field", "all"),
        "q": request.GET.get(f"{prefix}q", "").strip(),
    }


def _document_detail_redirect(document, **query):
    base_url = reverse("doc_detail", args=[document.sn])
    if not query:
        return base_url
    return f"{base_url}?{urlencode(query)}"


def _build_history_help_text(can_generate):
    if can_generate:
        return '"산출물 생성" 버튼을 눌러 최초 산출물 생성을 시작해 주세요.'
    return "최초 생성은 프로젝트 관리자만 진행할 수 있으며, 확정본이 이미 있으면 다시 시작할 수 없습니다."


def _is_generation_resume_request(request):
    return request.GET.get("resume") == "1"


def _build_empty_generation_state(current_project):
    return {
        "project_sn": current_project.sn if current_project else None,
        "selected_file_ids": [],
        "draft_documents": {},
        "confirmed_documents": {},
    }


def _get_generation_context(request, current_project, actor, document_code, state=None):
    state = state or get_generation_state(request.session, current_project)
    selected_files = get_generation_selected_files(current_project, state)
    current_code = get_current_generation_code(state)
    current_draft = None

    if current_code and state.get("draft_documents", {}).get(current_code):
        current_draft = get_object_or_404(
            Document.objects.select_related("project", "document_type"),
            sn=state["draft_documents"][current_code],
            project=current_project,
        )

    if request.GET.get("auto_start") == "1" and selected_files and current_code and current_draft is None:
        draft_document, created = ensure_generation_draft(current_project, actor, state)
        save_generation_state(request.session, state)
        if created and draft_document:
            messages.success(request, f"{get_document_label(current_code)} 초안을 생성했습니다.")
            return None, redirect(build_generation_redirect_url(document_code=current_code, play=True, resume=True))

    current_code = get_current_generation_code(state)
    if current_code and state.get("draft_documents", {}).get(current_code):
        current_draft = get_object_or_404(
            Document.objects.select_related("project", "document_type"),
            sn=state["draft_documents"][current_code],
            project=current_project,
        )

    progress_rows = get_generation_progress_rows(state)
    return {
        "state": state,
        "selected_files": selected_files,
        "current_code": current_code,
        "current_label": get_document_label(current_code) if current_code else "",
        "current_draft": current_draft,
        "progress_rows": progress_rows,
        "is_complete": is_generation_complete(state),
        "completed_documents": [
            Document.objects.filter(sn=document_sn).select_related("document_type").first()
            for document_sn in state.get("confirmed_documents", {}).values()
        ],
        "requested_document_code": document_code,
    }, None


def document_history_list(request):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document_code = resolve_document_code(request.GET.get("docs_cd"))
    selected_document_label = get_document_label(document_code)
    generation_state = get_generation_state(request.session, current_project)

    documents = Document.objects.none()
    if current_project is not None:
        documents = (
            Document.objects.filter(project=current_project, document_type_id=document_code)
            .select_related("document_type", "created_by", "user")
            .order_by("-created_at", "-sn")
        )

    document_rows = build_document_rows(documents)
    can_generate = can_access_initial_generation(current_project, actor, generation_state)
    context = {
        "active_menu": "doc_history",
        "title": f"{selected_document_label} 버전 이력",
        "current_project": current_project,
        "documents": document_rows,
        "has_documents": bool(document_rows),
        "selected_document_code": document_code,
        "selected_document_label": selected_document_label,
        "can_generate": can_generate,
        "generation_help_text": _build_history_help_text(can_generate),
    }
    return render(request, "docs/doc_history_list.html", context)


def document_generate(request):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document_code = resolve_document_code(request.GET.get("docs_cd") or request.POST.get("docs_cd"))

    is_resume_request = _is_generation_resume_request(request)

    if request.method == "GET" and request.GET.get("apply_selection") != "1" and not is_resume_request:
        clear_generation_state(request.session, current_project)

    generation_state = (
        get_generation_state(request.session, current_project)
        if is_resume_request or request.method != "GET" or request.GET.get("apply_selection") == "1"
        else _build_empty_generation_state(current_project)
    )

    if not can_access_initial_generation(current_project, actor, generation_state):
        messages.error(request, "현재 프로젝트에서는 최초 산출물 생성을 진행할 수 없습니다.")
        return redirect(f"{reverse('doc_history_list')}?docs_cd={document_code}")

    if request.method == "GET" and request.GET.get("apply_selection") == "1":
        state = get_generation_state(request.session, current_project)
        update_generation_selected_files(state, request.GET.getlist("selected_files"))
        save_generation_state(request.session, state)
        return redirect(build_generation_redirect_url(document_code=document_code, resume=True))

    if request.method == "POST":
        state = get_generation_state(request.session, current_project)
        action = request.POST.get("action")
        if action == "start_current":
            update_generation_selected_files(
                state,
                request.POST.getlist("selected_files") or state.get("selected_file_ids", []),
            )
            selected_files = get_generation_selected_files(current_project, state)
            if not selected_files:
                messages.error(request, "생성에 사용할 문서를 먼저 선택해 주세요.")
                return redirect(f"{build_generation_redirect_url(document_code=document_code, resume=True)}&modal=files")

            draft_document, created = ensure_generation_draft(current_project, actor, state)
            save_generation_state(request.session, state)
            if draft_document is None:
                messages.error(request, "생성할 산출물 단계를 찾지 못했습니다.")
                return redirect(build_generation_redirect_url(document_code=document_code, resume=True))
            if created:
                messages.success(request, f"{get_document_label(draft_document.document_type_id)} 초안을 생성했습니다.")
            return redirect(build_generation_redirect_url(document_code=draft_document.document_type_id, play=True, resume=True))

        return redirect(build_generation_redirect_url(document_code=document_code, resume=True))

    generation_context, redirect_response = _get_generation_context(
        request,
        current_project,
        actor,
        document_code,
        state=generation_state,
    )
    if redirect_response is not None:
        return redirect_response

    if request.method == "GET" and request.GET.get("apply_selection") != "1" and not is_resume_request:
        generation_context = {
            **generation_context,
            "state": generation_state,
            "selected_files": [],
            "current_draft": None,
            "progress_rows": get_generation_progress_rows(generation_state),
            "is_complete": is_generation_complete(generation_state),
            "completed_documents": [],
        }

    available_files = get_project_files(current_project, allowed_types=("FILE_RFP", "FILE_MEETING"))
    available_files, file_type, search_field, query = apply_file_filters(request.GET, available_files)

    context = {
        "active_menu": "doc_history",
        "title": "산출물 생성",
        "current_project": current_project,
        "selected_document_code": generation_context["requested_document_code"],
        "documents": build_project_file_rows(available_files),
        "file_type": file_type,
        "search_field": search_field,
        "query": query,
        "file_type_choices": get_file_type_choices(),
        "search_field_choices": SEARCH_FIELD_CHOICES,
        "selected_file_ids": generation_context["state"].get("selected_file_ids", []),
        "selected_files": generation_context["selected_files"],
        "current_document_code": generation_context["current_code"],
        "current_document_label": generation_context["current_label"],
        "current_draft": generation_context["current_draft"],
        "generation_steps": build_generation_steps(generation_context["current_code"]) if generation_context["current_code"] else [],
        "progress_rows": generation_context["progress_rows"],
        "open_file_modal": request.GET.get("modal") == "files",
        "show_generation_sequence": request.GET.get("play") == "1" and generation_context["current_draft"] is not None,
        "current_check_url": reverse("doc_detail", args=[generation_context["current_draft"].sn]) if generation_context["current_draft"] else "",
        "is_complete": generation_context["is_complete"],
        "completed_documents": [document for document in generation_context["completed_documents"] if document is not None],
        "has_selected_files": bool(generation_context["selected_files"]),
    }
    return render(request, "docs/doc_generate.html", context)


def document_detail(request, document_sn):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)

    preferred_mode = "edit" if request.GET.get("mode") == "edit" else "view"
    state, pending_approval = get_document_view_state(document, actor, preferred_mode=preferred_mode)
    latest_detail = get_latest_detail(document)
    latest_text = extract_text_from_docx(latest_detail.content if latest_detail else None)

    preview_detail_sn = request.GET.get("preview_detail")
    preview_detail = get_detail_by_sn(document, preview_detail_sn) if preview_detail_sn else None
    preview_text = extract_text_from_docx(preview_detail.content) if preview_detail else latest_text

    meeting_files = get_project_files(current_project, allowed_types=("FILE_MEETING",))
    meeting_filter_params = _collect_prefixed_filters(request, "meeting_")
    meeting_files, meeting_file_type, meeting_search_field, meeting_query = apply_file_filters(
        meeting_filter_params,
        meeting_files,
        default_file_type="all",
        allowed_file_types=("FILE_MEETING",),
    )

    revisions = (
        document.details.filter(is_deleted="N")
        .select_related("created_by")
        .order_by("-created_at", "-sn")
    )
    revision_rows = [
        {
            "sn": detail.sn,
            "created_at": detail.created_at,
            "creator_name": getattr(detail.created_by, "name", "-") or "-",
            "preview_url": build_history_preview_url(document, detail.sn),
            "restore_url": reverse("doc_restore_revision", args=[document.sn, detail.sn]),
        }
        for detail in revisions
    ]

    generation_state = get_generation_state(request.session, current_project)
    current_generation_code = get_current_generation_code(generation_state)
    is_generation_draft = (
        document.version == "0"
        and generation_state.get("draft_documents", {}).get(document.document_type_id) == document.sn
    )
    generation_return_url = (
        build_generation_redirect_url(document_code=current_generation_code, resume=True)
        if generation_state.get("selected_file_ids")
        else ""
    )

    context = {
        "active_menu": "doc_history",
        "title": get_document_label(document.document_type_id),
        "current_project": current_project,
        "document": document,
        "document_state": state,
        "pending_approval": pending_approval,
        "latest_detail": latest_detail,
        "latest_text": latest_text,
        "preview_detail": preview_detail,
        "preview_text": preview_text,
        "revision_rows": revision_rows,
        "can_confirm": is_generation_draft and (is_project_manager(current_project, actor) or document.created_by_id == actor.sn),
        "can_edit": state == "view" and pending_approval is None,
        "locked_by_name": getattr(document.user, "name", ""),
        "meeting_documents": build_project_file_rows(meeting_files),
        "meeting_file_type": meeting_file_type,
        "meeting_search_field": meeting_search_field,
        "meeting_query": meeting_query,
        "meeting_file_type_choices": get_file_type_choices(allowed_codes=("FILE_MEETING",)),
        "search_field_choices": SEARCH_FIELD_CHOICES,
        "open_history_modal": preview_detail is not None or request.GET.get("modal") == "history",
        "open_meeting_modal": request.GET.get("modal") == "meeting-files",
        "onlyoffice_enabled": bool(settings.ONLYOFFICE_DOCUMENT_SERVER_URL),
        "onlyoffice_document_server_url": settings.ONLYOFFICE_DOCUMENT_SERVER_URL.rstrip("/"),
        "download_url": f"{reverse('doc_content', args=[document.sn])}?download=1",
        "editor_config_url": reverse("doc_editor_config", args=[document.sn]),
        "selected_document_code": document.document_type_id,
        "is_generation_draft": is_generation_draft,
        "generation_return_url": generation_return_url,
    }
    return render(request, "docs/doc_detail.html", context)


def document_lock(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))

    if acquire_document_lock(document, actor):
        messages.success(request, "문서 수정 권한을 확보했습니다.")
    else:
        messages.error(request, "다른 사용자가 이미 문서를 수정 중입니다.")
    return redirect(build_document_detail_url(document, mode="edit"))


def document_save(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))
    if document.user_id != actor.sn:
        messages.error(request, "문서를 점유한 사용자만 저장할 수 있습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    text_content = request.POST.get("content_text", "").strip()
    if text_content:
        save_revision(document, actor, text_content=text_content, modification_content="수정 저장")
    release_document_lock(document, actor)
    messages.success(request, "문서 수정 내용을 저장했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


def document_cancel_edit(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method == "POST" and document.user_id == actor.sn:
        release_document_lock(document, actor)
        messages.info(request, "문서 편집을 종료했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


def document_confirm(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))
    if not (is_project_manager(current_project, actor) or document.created_by_id == actor.sn):
        messages.error(request, "문서를 확정할 권한이 없습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    confirmed_document, _ = confirm_document(document, actor)
    generation_state = get_generation_state(request.session, current_project)
    if generation_state.get("draft_documents", {}).get(document.document_type_id) == document.sn:
        mark_generation_confirmed(generation_state, document, confirmed_document)
        save_generation_state(request.session, generation_state)
        if is_generation_complete(generation_state):
            messages.success(request, "모든 최초 산출물 생성을 완료했습니다.")
            clear_generation_state(request.session, current_project)
            return redirect(f"{reverse('doc_history_list')}?docs_cd={confirmed_document.document_type_id}")

        messages.success(request, f"{get_document_label(document.document_type_id)} 확정본을 생성했습니다.")
        return redirect(build_generation_redirect_url(auto_start=True, resume=True))

    messages.success(request, "산출물을 확정했습니다.")
    return redirect(reverse("doc_detail", args=[confirmed_document.sn]))


def document_restore_revision(request, document_sn, detail_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))
    if document.user_id != actor.sn:
        messages.error(request, "문서를 점유한 사용자만 복원할 수 있습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    source_detail = get_detail_by_sn(document, detail_sn)
    if source_detail is None:
        messages.error(request, "복원할 이력을 찾을 수 없습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    restore_revision(document, actor, source_detail)
    messages.success(request, "선택한 버전으로 복원했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


def document_auto_apply(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))
    if document.user_id != actor.sn:
        messages.error(request, "문서를 점유한 사용자만 회의 내용을 반영할 수 있습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    selected_file_ids = request.POST.getlist("selected_files")
    selected_files = list(
        get_project_files(current_project, file_ids=selected_file_ids, allowed_types=("FILE_MEETING",))
    )
    if not selected_files:
        messages.error(request, "회의록 파일을 하나 이상 선택해 주세요.")
        return redirect(_document_detail_redirect(document, modal="meeting-files"))

    apply_meeting_notes(document, actor, selected_files)
    messages.success(request, "회의 내용을 문서에 자동 반영했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


def document_request_approval(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))
    if document.user_id != actor.sn:
        messages.error(request, "문서를 점유한 사용자만 승인 요청할 수 있습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    request_content = request.POST.get("request_content", "").strip()
    if not request_content:
        messages.error(request, "승인 요청 내용을 입력해 주세요.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    create_approval_request(document, actor, request_content)
    messages.success(request, "프로젝트 관리자에게 승인 요청을 전송했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


def document_content(request, document_sn):
    token = request.GET.get("token", "").strip()
    document = _get_document_by_sn_or_404(document_sn)
    if not validate_document_content_token(document, token):
        current_project, _ = resolve_current_project(request)
        actor = get_actor(request)
        _ensure_document_access(current_project, actor, document)

    latest_detail = get_latest_detail(document)
    content = latest_detail.content if latest_detail else b""
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{get_document_title(document)}"'
    return response


def document_editor_config(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)

    state, _ = get_document_view_state(document, actor, preferred_mode=request.GET.get("mode"))
    mode = "edit" if state == "edit" else "view"
    return JsonResponse(build_editor_config(request, document, actor, mode))


@csrf_exempt
def document_callback(request, document_sn):
    document = _get_document_by_sn_or_404(document_sn)
    if request.method != "POST":
        return JsonResponse({"error": 0})

    payload = parse_callback_payload(request)
    status = payload.get("status")
    if status in {2, 6}:
        content_bytes = None
        if payload.get("url"):
            try:
                content_bytes = download_remote_content(payload["url"])
            except Exception:
                content_bytes = None
        save_revision(
            document,
            document.updated_by or document.created_by,
            content_bytes=content_bytes,
            text_content=None if content_bytes else payload.get("content_text") or extract_text_from_docx(get_latest_detail(document).content),
            modification_content="OnlyOffice 저장",
        )
    return JsonResponse({"error": 0})


def document_cancel_approval(request, approval_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("detail__document__project", "created_by", "approval_status"),
        sn=approval_sn,
    )
    document = approval.detail.document
    _ensure_document_access(current_project, actor, document)
    if request.method == "POST" and approval.created_by_id == actor.sn and approval.approval_status_id == "APRV_REQ":
        cancel_approval_request(approval)
        messages.success(request, "승인 요청을 취소했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


def approval_list(request):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)

    approvals = DocumentApproval.objects.none()
    document_code = "all"
    approval_status = "all"
    requester_query = ""
    include_requester = current_project is not None and is_project_manager(current_project, actor)

    if current_project is not None and is_project_participant(current_project, actor):
        approvals = build_approval_queryset(current_project, actor)
        approvals, document_code, approval_status, requester_query = apply_approval_filters(
            request.GET,
            approvals,
            include_requester=include_requester,
        )

    context = {
        "active_menu": "approvals",
        "title": "산출물 승인요청",
        "current_project": current_project,
        "documents": build_approval_rows(approvals),
        "document_type_choices": get_document_type_choices(include_all=True),
        "approval_status_choices": get_approval_status_choices(include_all=True),
        "selected_document_code": document_code,
        "selected_status": approval_status,
        "requester_query": requester_query,
        "include_requester_search": include_requester,
        "is_manager": include_requester,
    }
    return render(request, "docs/approval_list.html", context)


def approval_detail(request, approval_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    approval = get_object_or_404(
        DocumentApproval.objects.select_related(
            "detail__document__project",
            "detail__document__document_type",
            "detail__document__created_by",
            "detail__document__user",
            "approval_status",
            "created_by",
        ),
        sn=approval_sn,
    )
    document = approval.detail.document
    _ensure_document_access(current_project, actor, document)

    is_manager = is_project_manager(current_project, actor)
    if not is_manager and approval.created_by_id != actor.sn:
        raise Http404

    previous_document = latest_confirmed_document(current_project, document.document_type_id)
    previous_detail = get_latest_detail(previous_document) if previous_document else None
    previous_text = extract_text_from_docx(previous_detail.content if previous_detail else None)
    updated_text = extract_text_from_docx(approval.detail.content)
    review = build_consistency_review(approval) if request.GET.get("consistency") == "1" else None

    context = {
        "active_menu": "approvals",
        "title": "산출물 승인 상세",
        "current_project": current_project,
        "approval": approval,
        "document": document,
        "is_manager": is_manager,
        "previous_document": previous_document,
        "previous_text": previous_text,
        "updated_text": updated_text,
        "review": review,
        "requester_name": getattr(approval.created_by, "name", "-") or "-",
    }
    return render(request, "docs/approval_detail.html", context)


def approval_consistency(request, approval_sn):
    if request.method != "POST":
        return redirect(reverse("doc_approval_detail", args=[approval_sn]))
    return redirect(f"{reverse('doc_approval_detail', args=[approval_sn])}?consistency=1")


def approval_approve(request, approval_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("detail__document__project"),
        sn=approval_sn,
    )
    document = approval.detail.document
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST" or not is_project_manager(current_project, actor):
        return redirect(reverse("doc_approval_detail", args=[approval.sn]))

    new_version = request.POST.get("new_version", "").strip()
    if not new_version:
        messages.error(request, "새 버전명을 입력해 주세요.")
        return redirect(reverse("doc_approval_detail", args=[approval.sn]))

    approved_document, _ = approve_request(approval, actor, new_version)
    messages.success(request, "승인 요청을 반영하고 새 버전을 생성했습니다.")
    return redirect(reverse("doc_detail", args=[approved_document.sn]))


def approval_reject(request, approval_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("detail__document__project"),
        sn=approval_sn,
    )
    document = approval.detail.document
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST" or not is_project_manager(current_project, actor):
        return redirect(reverse("doc_approval_detail", args=[approval.sn]))

    reason = request.POST.get("rejection_reason", "").strip()
    if not reason:
        messages.error(request, "반려 사유를 입력해 주세요.")
        return redirect(reverse("doc_approval_detail", args=[approval.sn]))

    reject_request(approval, actor, reason)
    messages.success(request, "승인 요청을 반려했습니다.")
    return redirect(reverse("doc_approval_detail", args=[approval.sn]))
