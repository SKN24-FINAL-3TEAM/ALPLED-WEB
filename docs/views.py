from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from common.project_selection import resolve_current_project
from common.signals import ensure_initial_reference_data
from common.models import YesNoChoices
from files.services import (
    SEARCH_FIELD_CHOICES,
    apply_file_filters,
    build_project_file_rows,
    get_file_type_choices,
)

from .models import Document, DocumentApproval
from .services import (
    ARCHITECTURE_DOCUMENT_CODE,
    INTERFACE_REFERENCE_DOCUMENT_CODE,
    PROGRESS_COMPLETED,
    PROGRESS_FAILED,
    PROGRESS_PENDING,
    PROGRESS_PROCESSING,
    acquire_document_lock,
    add_generation_itf_references,
    apply_approval_filters,
    approve_request,
    build_approval_queryset,
    build_approval_rows,
    build_consistency_review,
    build_document_detail_url,
    build_document_rows,
    build_editor_config,
    build_generation_redirect_url,
    build_history_preview_api_url,
    can_request_approval,
    can_access_initial_generation,
    cancel_approval_request,
    clear_generation_draft_document,
    clear_generation_state,
    confirm_document,
    create_project_net,
    create_approval_request,
    _debug_generation_log,
    download_remote_content,
    extract_text_from_docx,
    find_document_job,
    get_actor,
    get_approval_status_choices,
    get_current_generation_code,
    get_doc_job_poll_interval_seconds,
    get_detail_by_sn,
    get_document_detail_bytes,
    get_document_label,
    get_document_history_queryset,
    get_document_title,
    get_document_type_choices,
    get_document_view_state,
    get_generation_draft_document,
    get_generation_progress_rows,
    get_generation_selected_files,
    get_generation_state,
    get_generation_itf_references,
    get_generation_prerequisite_error,
    get_latest_detail,
    get_project_files,
    get_project_nets,
    get_running_document,
    get_running_history_job,
    get_running_initial_document,
    has_document_version,
    has_active_generation_session,
    is_generation_complete,
    is_latest_detail_for_document,
    is_latest_document_for_type,
    is_project_manager,
    is_project_participant,
    latest_confirmed_document,
    mark_generation_confirmed,
    parse_callback_payload,
    reject_request,
    release_document_lock,
    request_force_save,
    resolve_document_code,
    restore_revision,
    save_generation_state,
    save_revision,
    set_generation_draft_document,
    start_auto_apply_job,
    start_initial_generation_job,
    update_generation_selected_files,
    validate_document_content_token,
    wait_for_new_revision,
    remove_generation_itf_reference,
)


def _get_document_or_404(project, document_sn):
    queryset = Document.objects.select_related(
        "project",
        "document_type",
        "created_by",
        "updated_by",
        "possession_user",
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
            "possession_user",
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


def _approval_detail_redirect(approval, **query):
    base_url = reverse("doc_approval_detail", args=[approval.approval_sn])
    if not query:
        return base_url
    return f"{base_url}?{urlencode(query)}"


def _is_ajax_request(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _legacy_detail_error_message():
    return "This document revision is missing docs_path. Ask an administrator to migrate legacy rows."


def _build_history_help_text(can_generate):
    if can_generate:
        return '"산출물 생성" 버튼을 눌러 최초 산출물 생성을 시작해 주세요.'
    return "최초 생성은 프로젝트 관리자만 진행할 수 있으며, 확정본이 이미 있으면 다시 시작할 수 없습니다."


def _is_generation_resume_request(request):
    return request.GET.get("resume") == "1"


def _get_generation_context(request, current_project, actor, document_code, state=None):
    state = state or get_generation_state(request.session, current_project)
    selected_files = get_generation_selected_files(current_project, state)
    current_code = get_current_generation_code(state)
    current_draft = get_generation_draft_document(current_project, state, current_code)
    if current_draft is not None and current_draft.progress_status_id == PROGRESS_FAILED:
        clear_generation_draft_document(state, current_code)
        save_generation_state(request.session, state)
        current_draft = None

    if request.GET.get("auto_start") == "1" and current_code and current_draft is None:
        prerequisite_error = get_generation_prerequisite_error(current_project, state, current_code)
        if prerequisite_error is None:
            job_result = start_initial_generation_job(current_project, actor, state)
            save_generation_state(request.session, state)
            if job_result["status"] in {"started", "running"} and job_result["document"] is not None:
                messages.success(request, f"{get_document_label(current_code)} 생성을 요청했습니다.")
                return None, redirect(build_generation_redirect_url(document_code=current_code, play=True, resume=True))

    current_code = get_current_generation_code(state)
    current_draft = get_generation_draft_document(current_project, state, current_code)

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


def _build_architecture_form_data(request=None):
    source = request.POST if request is not None else {}
    return {
        "name": source.get("name", "").strip(),
        "purpose": source.get("purpose", "").strip(),
        "middleware_stack": source.get("middleware_stack", "").strip(),
        "firewall_settings": source.get("firewall_settings", "").strip(),
        "auth_method": source.get("auth_method", "").strip(),
        "expected_concurrent_users": source.get("expected_concurrent_users", "").strip(),
        "cloud_yn": YesNoChoices.YES if source.get("cloud_yn") == YesNoChoices.YES else YesNoChoices.NO,
        "hardware_spec": source.get("hardware_spec", "").strip(),
        "remarks": source.get("remarks", "").strip(),
    }


def _build_generation_redirect(document_code, *, resume=True, play=False, auto_start=False, modal=None, arch_form=False):
    base_url = build_generation_redirect_url(
        document_code=document_code,
        play=play,
        auto_start=auto_start,
        resume=resume,
    )
    extra_query = []
    if modal:
        extra_query.append(("modal", modal))
    if arch_form:
        extra_query.append(("arch_form", "1"))
    if not extra_query:
        return base_url
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(extra_query)}"


def _build_job_title(job_kind, document_code):
    label = get_document_label(document_code)
    if job_kind == "auto_apply":
        return f"{label} 회의 내용 자동 적용"
    return f"{label} 생성"


def _build_job_status_url(job_kind, document_code, tracking_document_sn=None):
    query_items = [("job_kind", job_kind), ("docs_cd", document_code)]
    if tracking_document_sn:
        query_items.append(("tracking_document_sn", str(tracking_document_sn)))
    return f"{reverse('doc_job_status')}?{urlencode(query_items)}"


def _get_job_timing(document):
    if document is None or getattr(document, "created_at", None) is None:
        return "", 0
    started_at = timezone.localtime(document.created_at)
    elapsed_seconds = max(int((timezone.now() - document.created_at).total_seconds()), 0)
    return started_at.isoformat(), elapsed_seconds


def _build_job_response(job_kind, document_code, message, *, status, tracking_document_sn=None, redirect_url=""):
    return {
        "status": status,
        "message": message,
        "title": _build_job_title(job_kind, document_code),
        "docs_cd": document_code,
        "job_kind": job_kind,
        "tracking_document_sn": tracking_document_sn,
        "poll_url": _build_job_status_url(job_kind, document_code, tracking_document_sn),
        "poll_interval_ms": get_doc_job_poll_interval_seconds() * 1000,
        "redirect_url": redirect_url,
        "started_at": "",
        "elapsed_seconds": 0,
    }


def _build_document_job_response(job_kind, document_code, message, document, *, status, redirect_url=""):
    started_at, elapsed_seconds = _get_job_timing(document)
    payload = _build_job_response(
        job_kind,
        document_code,
        message,
        status=status,
        tracking_document_sn=getattr(document, "sn", None),
        redirect_url=redirect_url,
    )
    payload["started_at"] = started_at
    payload["elapsed_seconds"] = elapsed_seconds
    return payload


def _serialize_job_status(request, current_project, document_code, job_kind, tracking_document_sn=None):
    if job_kind == "initial":
        generation_state = get_generation_state(request.session, current_project)
        document = find_document_job(
            current_project,
            document_code,
            tracking_document_sn=tracking_document_sn,
            initial_only=True,
        )
        if document is None:
            clear_generation_draft_document(generation_state, document_code)
            save_generation_state(request.session, generation_state)
            return _build_job_response(job_kind, document_code, "진행 중인 생성 작업이 없습니다.", status="idle")

        if document.progress_status_id == PROGRESS_FAILED:
            clear_generation_draft_document(generation_state, document_code)
            save_generation_state(request.session, generation_state)
            return _build_document_job_response(
                job_kind,
                document_code,
                "문서 생성이 실패했습니다. 다시 시도해 주세요.",
                document,
                status="failed",
            )

        set_generation_draft_document(generation_state, document)
        save_generation_state(request.session, generation_state)
    else:
        document = find_document_job(
            current_project,
            document_code,
            tracking_document_sn=tracking_document_sn,
        )
        if document is None:
            return _build_job_response(job_kind, document_code, "진행 중인 자동 적용 작업이 없습니다.", status="idle")
        if document.progress_status_id == PROGRESS_FAILED:
            return _build_document_job_response(
                job_kind,
                document_code,
                "회의 내용 자동 적용이 실패했습니다. 다시 시도해 주세요.",
                document,
                status="failed",
            )

    if document.progress_status_id in {PROGRESS_PENDING, PROGRESS_PROCESSING}:
        return _build_document_job_response(
            job_kind,
            document_code,
            "문서를 생성 중입니다.",
            document,
            status="running",
        )

    if document.progress_status_id == PROGRESS_COMPLETED:
        return _build_document_job_response(
            job_kind,
            document_code,
            "문서가 준비되었습니다.",
            document,
            status="completed",
            redirect_url=reverse("doc_detail", args=[document.sn]),
        )

    return _build_job_response(job_kind, document_code, "작업 상태를 확인할 수 없습니다.", status="idle")


def _build_active_job_context(job_payload):
    if not job_payload or job_payload.get("status") != "running":
        return None
    return {
        "status": job_payload["status"],
        "message": job_payload["message"],
        "title": job_payload["title"],
        "poll_url": job_payload["poll_url"],
        "poll_interval_ms": job_payload["poll_interval_ms"],
        "tracking_document_sn": job_payload["tracking_document_sn"],
        "job_kind": job_payload["job_kind"],
        "docs_cd": job_payload["docs_cd"],
        "started_at": job_payload.get("started_at", ""),
        "elapsed_seconds": job_payload.get("elapsed_seconds", 0),
    }


def _get_document_active_job(request, current_project, document):
    initial_job = get_running_initial_document(
        current_project,
        document.document_type_id,
        tracking_document_sn=document.sn,
    )
    if initial_job is not None:
        return _build_active_job_context(
            _serialize_job_status(
                request,
                current_project,
                document.document_type_id,
                "initial",
                tracking_document_sn=document.sn,
            )
        )

    running_document = get_running_document(
        current_project,
        document.document_type_id,
        tracking_document_sn=document.sn,
    )
    if running_document is not None:
        return _build_active_job_context(
            _serialize_job_status(
                request,
                current_project,
                document.document_type_id,
                "auto_apply",
                tracking_document_sn=document.sn,
            )
        )
    return None


def _can_show_auto_apply(document, actor, current_project, latest_detail):
    if current_project is None or actor is None or document is None or latest_detail is None:
        return False
    return (
        document.project_id == current_project.sn
        and document.possession_user_id == actor.sn
        and is_latest_document_for_type(document)
        and is_latest_detail_for_document(document, latest_detail)
    )


def _create_project_net_from_request(request, current_project, actor):
    form_data = _build_architecture_form_data(request)
    if current_project is None:
        messages.error(request, "현재 선택된 프로젝트가 없습니다.")
        return False, form_data
    if not form_data["name"]:
        messages.error(request, "서버 망 이름을 입력해 주세요.")
        return False, form_data

    expected_concurrent_users = None
    if form_data["expected_concurrent_users"]:
        try:
            expected_concurrent_users = int(form_data["expected_concurrent_users"])
        except ValueError:
            messages.error(request, "예상 동시 접속자 수는 숫자로 입력해 주세요.")
            return False, form_data

    create_project_net(
        project=current_project,
        actor=actor,
        name=form_data["name"],
        purpose=form_data["purpose"],
        middleware_stack=form_data["middleware_stack"],
        firewall_settings=form_data["firewall_settings"],
        auth_method=form_data["auth_method"],
        expected_concurrent_users=expected_concurrent_users,
        cloud_yn=form_data["cloud_yn"],
        hardware_spec=form_data["hardware_spec"],
        remarks=form_data["remarks"],
    )
    messages.success(request, "서버 정보를 추가했습니다.")
    return True, _build_architecture_form_data()


@login_required(login_url="home")
def document_history_list(request):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document_code = resolve_document_code(request.GET.get("docs_cd"))
    selected_document_label = get_document_label(document_code)
    generation_state = get_generation_state(request.session, current_project)

    documents = get_document_history_queryset(current_project, document_code)

    document_rows = build_document_rows(documents)
    can_generate = can_access_initial_generation(current_project, actor, generation_state)
    active_job = None
    active_job_kind, active_job_document = get_running_history_job(current_project, document_code)
    if active_job_document is not None:
        active_job = _build_active_job_context(
            _serialize_job_status(
                request,
                current_project,
                document_code,
                active_job_kind,
                tracking_document_sn=active_job_document.sn,
            )
        )
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
        "active_job": active_job,
    }
    return render(request, "docs/doc_history_list.html", context)


@login_required(login_url="home")
def document_generate(request):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document_code = resolve_document_code(request.GET.get("docs_cd") or request.POST.get("docs_cd"))
    generation_state = get_generation_state(request.session, current_project)
    architecture_form = _build_architecture_form_data()
    open_arch_form = request.GET.get("arch_form") == "1"

    if not can_access_initial_generation(current_project, actor, generation_state):
        messages.error(request, "현재 프로젝트에서는 최초 산출물 생성을 진행할 수 없습니다.")
        return redirect(f"{reverse('doc_history_list')}?docs_cd={document_code}")

    if request.method == "GET" and request.GET.get("apply_selection") == "1":
        state = get_generation_state(request.session, current_project)
        update_generation_selected_files(state, request.GET.getlist("selected_files"))
        save_generation_state(request.session, state)
        return redirect(_build_generation_redirect(document_code, resume=True))

    if request.method == "POST":
        state = get_generation_state(request.session, current_project)
        action = request.POST.get("action")
        current_code = get_current_generation_code(state)

        if action == "reset_generation":
            clear_generation_state(request.session, current_project)
            messages.success(request, "산출물 생성 진행 상태를 초기화했습니다.")
            return redirect(build_generation_redirect_url(document_code=document_code, resume=False))

        if action == "upload_itf_reference":
            if current_code != INTERFACE_REFERENCE_DOCUMENT_CODE:
                messages.error(request, "현재 단계에서는 이미지 참고자료를 업로드할 수 없습니다.")
                return redirect(_build_generation_redirect(document_code, resume=True))

            uploaded_files = request.FILES.getlist("itf_references")
            if not uploaded_files:
                messages.error(request, "업로드할 이미지 파일을 선택해 주세요.")
                return redirect(_build_generation_redirect(document_code, resume=True))

            added_count, errors = add_generation_itf_references(current_project, actor, state, uploaded_files)
            save_generation_state(request.session, state)
            for error in dict.fromkeys(errors):
                messages.error(request, error)
            if added_count:
                messages.success(request, f"참고 이미지 {added_count}건을 업로드했습니다.")
            return redirect(_build_generation_redirect(document_code, resume=True))

        if action == "remove_itf_reference":
            removed = remove_generation_itf_reference(state, request.POST.get("reference_token", ""))
            save_generation_state(request.session, state)
            if removed:
                messages.success(request, "참고 이미지를 제거했습니다.")
            else:
                messages.error(request, "제거할 참고 이미지를 찾지 못했습니다.")
            return redirect(_build_generation_redirect(document_code, resume=True))

        if action == "delete_project_net":
            if current_code != ARCHITECTURE_DOCUMENT_CODE:
                messages.error(request, "현재 단계에서는 서버 정보를 삭제할 수 없습니다.")
                return redirect(_build_generation_redirect(document_code, resume=True))
            if current_project is None:
                messages.error(request, "현재 선택된 프로젝트가 없습니다.")
                return redirect(_build_generation_redirect(document_code, resume=True))
            project_net = get_object_or_404(current_project.nets.all(), sn=request.POST.get("project_net_sn"))
            project_net.delete()
            messages.success(request, "서버 정보를 삭제했습니다.")
            return redirect(_build_generation_redirect(document_code, resume=True))

        if action == "add_project_net":
            if current_code != ARCHITECTURE_DOCUMENT_CODE:
                messages.error(request, "현재 단계에서는 서버 정보를 추가할 수 없습니다.")
                return redirect(_build_generation_redirect(document_code, resume=True))
            created, architecture_form = _create_project_net_from_request(request, current_project, actor)
            open_arch_form = not created
            if created:
                return redirect(_build_generation_redirect(document_code, resume=True))

        if action == "start_current":
            _debug_generation_log(
                "document_generate_start_current_enter",
                request_path=request.path,
                method=request.method,
                is_ajax=_is_ajax_request(request),
                project_sn=getattr(current_project, "sn", None),
                actor_sn=getattr(actor, "sn", None),
                requested_document_code=document_code,
                current_code=current_code,
                posted_selected_file_ids=request.POST.getlist("selected_files"),
                session_selected_file_ids=list(state.get("selected_file_ids", []) or []),
            )
            if current_code not in {INTERFACE_REFERENCE_DOCUMENT_CODE, ARCHITECTURE_DOCUMENT_CODE}:
                update_generation_selected_files(
                    state,
                    request.POST.getlist("selected_files") or state.get("selected_file_ids", []),
                )

            prerequisite_error = get_generation_prerequisite_error(current_project, state, current_code)
            if prerequisite_error:
                _debug_generation_log(
                    "document_generate_start_current_prerequisite_error",
                    current_code=current_code,
                    error=prerequisite_error,
                )
                if _is_ajax_request(request):
                    return JsonResponse({"message": prerequisite_error}, status=400)
                messages.error(request, prerequisite_error)
                if current_code not in {INTERFACE_REFERENCE_DOCUMENT_CODE, ARCHITECTURE_DOCUMENT_CODE}:
                    return redirect(_build_generation_redirect(document_code, resume=True, modal="files"))
                return redirect(_build_generation_redirect(document_code, resume=True, arch_form=current_code == ARCHITECTURE_DOCUMENT_CODE))

            job_result = start_initial_generation_job(current_project, actor, state)
            _debug_generation_log(
                "document_generate_start_current_job_result",
                current_code=current_code,
                job_status=job_result.get("status"),
                document_sn=getattr(job_result.get("document"), "sn", None),
                message=job_result.get("message"),
            )
            save_generation_state(request.session, state)
            draft_document = job_result["document"]
            if job_result["status"] == "error" or draft_document is None:
                if _is_ajax_request(request):
                    return JsonResponse({"message": job_result["message"]}, status=502)
                messages.error(request, "생성할 산출물 단계를 찾지 못했습니다.")
                return redirect(build_generation_redirect_url(document_code=document_code, resume=True))
            if _is_ajax_request(request):
                return JsonResponse(
                    _build_document_job_response(
                        "initial",
                        draft_document.document_type_id,
                        job_result["message"],
                        draft_document,
                        status=job_result["status"],
                    )
                )
            if job_result["status"] == "started":
                messages.success(request, f"{get_document_label(draft_document.document_type_id)} 생성을 요청했습니다.")
            else:
                messages.info(request, job_result["message"])
            return redirect(_build_generation_redirect(draft_document.document_type_id, play=True, resume=True))

        if action != "add_project_net":
            return redirect(_build_generation_redirect(document_code, resume=True))

    generation_context, redirect_response = _get_generation_context(
        request,
        current_project,
        actor,
        document_code,
        state=generation_state,
    )
    if redirect_response is not None:
        return redirect_response

    available_files = get_project_files(current_project, allowed_types=("FILE_RFP", "FILE_MEETING"))
    available_files, file_type, search_field, query = apply_file_filters(request.GET, available_files)
    current_step_code = generation_context["current_code"]
    itf_references = get_generation_itf_references(generation_context["state"])
    architecture_networks = get_project_nets(current_project)
    active_generation_job = None
    can_start_current_generation = False
    start_button_label = f"{generation_context['current_label']} 생성" if generation_context["current_label"] else "산출물 생성"

    if current_step_code == INTERFACE_REFERENCE_DOCUMENT_CODE:
        can_start_current_generation = bool(itf_references and current_step_code and not generation_context["current_draft"])
        start_button_label = "사용자 인터페이스 설계서 생성"
    elif current_step_code == ARCHITECTURE_DOCUMENT_CODE:
        can_start_current_generation = bool(architecture_networks and current_step_code and not generation_context["current_draft"])
        start_button_label = "아키텍처 설계서 초안 생성"
    else:
        can_start_current_generation = bool(
            generation_context["selected_files"] and current_step_code and not generation_context["current_draft"]
        )

    if current_step_code:
        tracking_document_sn = getattr(generation_context["current_draft"], "sn", None)
        active_generation_job = _build_active_job_context(
            _serialize_job_status(
                request,
                current_project,
                current_step_code,
                "initial",
                tracking_document_sn=tracking_document_sn,
            )
        )

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
        "current_step_code": current_step_code,
        "current_draft": generation_context["current_draft"],
        "progress_rows": generation_context["progress_rows"],
        "open_file_modal": request.GET.get("modal") == "files",
        "current_check_url": reverse("doc_detail", args=[generation_context["current_draft"].sn]) if generation_context["current_draft"] else "",
        "is_complete": generation_context["is_complete"],
        "completed_documents": [document for document in generation_context["completed_documents"] if document is not None],
        "has_selected_files": bool(generation_context["selected_files"]),
        "itf_references": itf_references,
        "architecture_networks": architecture_networks,
        "architecture_form": architecture_form,
        "open_arch_form": open_arch_form,
        "show_file_selector": current_step_code not in {INTERFACE_REFERENCE_DOCUMENT_CODE, ARCHITECTURE_DOCUMENT_CODE},
        "show_itf_upload": current_step_code == INTERFACE_REFERENCE_DOCUMENT_CODE,
        "show_architecture_inputs": current_step_code == ARCHITECTURE_DOCUMENT_CODE,
        "can_start_current_generation": can_start_current_generation,
        "start_button_label": start_button_label,
        "has_active_generation_session": has_active_generation_session(generation_context["state"]),
        "active_job": active_generation_job,
    }
    return render(request, "docs/doc_generate.html", context)


@login_required(login_url="home")
def document_job_status(request):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    if current_project is None or not is_project_participant(current_project, actor):
        return JsonResponse({"message": "현재 프로젝트에 접근할 수 없습니다."}, status=404)

    document_code = resolve_document_code(request.GET.get("docs_cd"))
    job_kind = (request.GET.get("job_kind") or "").strip()
    tracking_document_sn = request.GET.get("tracking_document_sn") or None
    if job_kind not in {"initial", "auto_apply"}:
        return JsonResponse({"message": "지원하지 않는 작업 유형입니다."}, status=400)

    return JsonResponse(
        _serialize_job_status(
            request,
            current_project,
            document_code,
            job_kind,
            tracking_document_sn=tracking_document_sn,
        )
    )


@login_required(login_url="home")
def document_detail(request, document_sn):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)

    preferred_mode = "edit" if request.GET.get("mode") == "edit" else "view"
    state, pending_approval = get_document_view_state(document, actor, preferred_mode=preferred_mode)
    latest_detail = get_latest_detail(document)
    try:
        latest_text = extract_text_from_docx(get_document_detail_bytes(latest_detail))
    except ValueError:
        messages.error(request, _legacy_detail_error_message())
        return redirect(f"{reverse('doc_history_list')}?docs_cd={document.document_type_id}")

    preview_detail_sn = request.GET.get("preview_detail")
    preview_detail = get_detail_by_sn(document, preview_detail_sn) if preview_detail_sn else None
    if preview_detail:
        try:
            preview_text = extract_text_from_docx(get_document_detail_bytes(preview_detail))
        except ValueError:
            messages.error(request, _legacy_detail_error_message())
            return redirect(reverse("doc_detail", args=[document.sn]))
    else:
        preview_text = latest_text

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
            "preview_url": build_history_preview_api_url(document, detail.sn),
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
    active_job = _get_document_active_job(request, current_project, document)
    can_cancel_approval = pending_approval is not None and pending_approval.created_by_id == actor.sn
    can_auto_apply = _can_show_auto_apply(document, actor, current_project, latest_detail)

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
        "can_cancel_approval": can_cancel_approval,
        "can_request_approval": state == "view"
        and can_request_approval(
            document,
            actor,
            pending_approval=pending_approval,
            is_generation_draft=is_generation_draft,
        ),
        "can_auto_apply": can_auto_apply,
        "locked_by_name": getattr(document.possession_user, "name", ""),
        "meeting_documents": build_project_file_rows(meeting_files),
        "meeting_file_type": meeting_file_type,
        "meeting_search_field": meeting_search_field,
        "meeting_query": meeting_query,
        "meeting_file_type_choices": get_file_type_choices(allowed_codes=("FILE_MEETING",)),
        "search_field_choices": SEARCH_FIELD_CHOICES,
        "open_history_modal": preview_detail is not None or request.GET.get("modal") == "history",
        "open_meeting_modal": request.GET.get("modal") == "meeting-files",
        "open_approval_request_modal": request.GET.get("modal") == "approval-request",
        "onlyoffice_enabled": bool(settings.ONLYOFFICE_DOCUMENT_SERVER_URL),
        "onlyoffice_document_server_url": settings.ONLYOFFICE_DOCUMENT_SERVER_URL.rstrip("/"),
        "download_url": f"{reverse('doc_content', args=[document.sn])}?download=1",
        "editor_config_url": reverse("doc_editor_config", args=[document.sn]),
        "selected_document_code": document.document_type_id,
        "is_generation_draft": is_generation_draft,
        "generation_return_url": generation_return_url,
        "active_job": active_job,
    }
    return render(request, "docs/doc_detail.html", context)


@login_required(login_url="home")
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


@login_required(login_url="home")
def document_save(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    is_ajax = _is_ajax_request(request)
    if request.method != "POST":
        if is_ajax:
            return JsonResponse({"message": "잘못된 요청입니다."}, status=405)
        return redirect(reverse("doc_detail", args=[document.sn]))
    if document.possession_user_id != actor.sn:
        if is_ajax:
            return JsonResponse({"message": "문서를 점유한 사용자만 저장할 수 있습니다."}, status=403)
        messages.error(request, "문서를 점유한 사용자만 저장할 수 있습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    latest_detail = get_latest_detail(document)
    text_content = request.POST.get("content_text", "").strip()
    saved_detail = latest_detail
    if not text_content and latest_detail is not None:
        try:
            get_document_detail_bytes(latest_detail)
        except ValueError:
            message = _legacy_detail_error_message()
            if is_ajax:
                return JsonResponse({"message": message}, status=409)
            messages.error(request, message)
            return redirect(build_document_detail_url(document, mode="edit"))
    if text_content:
        saved_detail = save_revision(document, actor, text_content=text_content, modification_content="수정 저장")
    elif settings.ONLYOFFICE_DOCUMENT_SERVER_URL:
        baseline_value = request.POST.get("baseline_detail_sn", "").strip()
        baseline_detail_sn = getattr(latest_detail, "sn", None)
        if baseline_value:
            try:
                baseline_detail_sn = int(baseline_value)
            except ValueError:
                baseline_detail_sn = getattr(latest_detail, "sn", None)
        try:
            force_save_result = request_force_save(
                document,
                latest_detail=latest_detail,
                userdata=f"doc-save-{document.sn}-{actor.sn}",
            )
        except Exception:
            message = "OnlyOffice 저장 요청을 전송하지 못했습니다. 환경 설정을 확인해 주세요."
            if is_ajax:
                return JsonResponse({"message": message}, status=502)
            messages.error(request, message)
            return redirect(build_document_detail_url(document, mode="edit"))

        force_save_error = force_save_result.get("error")
        if force_save_error == 0:
            saved_detail = wait_for_new_revision(document, baseline_detail_sn=baseline_detail_sn)
            if saved_detail is None or getattr(saved_detail, "sn", None) == baseline_detail_sn:
                message = "OnlyOffice 저장 결과를 아직 받지 못했습니다. 잠시 후 다시 시도해 주세요."
                if is_ajax:
                    return JsonResponse({"message": message}, status=409)
                messages.error(request, message)
                return redirect(build_document_detail_url(document, mode="edit"))
        elif force_save_error == 4:
            saved_detail = latest_detail
        else:
            error_messages = {
                1: "현재 편집 중인 문서를 찾지 못했습니다.",
                2: "OnlyOffice callback URL 설정이 올바르지 않습니다.",
                3: "OnlyOffice 내부 오류로 저장하지 못했습니다.",
                5: "OnlyOffice 저장 명령 형식이 올바르지 않습니다.",
                6: "OnlyOffice 토큰 검증에 실패했습니다.",
            }
            message = error_messages.get(force_save_error, "OnlyOffice 저장 요청 처리에 실패했습니다.")
            if is_ajax:
                return JsonResponse({"message": message}, status=502)
            messages.error(request, message)
            return redirect(build_document_detail_url(document, mode="edit"))
    release_document_lock(document, actor)
    detail_url = reverse("doc_detail", args=[document.sn])
    if is_ajax:
        return JsonResponse(
            {
                "message": "문서 수정 내용을 저장했습니다.",
                "redirect_url": detail_url,
                "latest_detail_sn": getattr(saved_detail, "sn", None),
            }
        )
    messages.success(request, "문서 수정 내용을 저장했습니다.")
    return redirect(detail_url)


@login_required(login_url="home")
def document_cancel_edit(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method == "POST" and document.possession_user_id == actor.sn:
        release_document_lock(document, actor)
        messages.info(request, "문서 편집을 종료했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


@login_required(login_url="home")
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

    try:
        confirmed_document, _ = confirm_document(document, actor)
    except ValueError:
        messages.error(request, _legacy_detail_error_message())
        return redirect(reverse("doc_detail", args=[document.sn]))
    generation_state = get_generation_state(request.session, current_project)
    if generation_state.get("draft_documents", {}).get(document.document_type_id) == document.sn:
        mark_generation_confirmed(generation_state, document, confirmed_document)
        save_generation_state(request.session, generation_state)
        if is_generation_complete(generation_state):
            messages.success(request, "모든 최초 산출물 생성을 완료했습니다.")
            clear_generation_state(request.session, current_project)
            return redirect(f"{reverse('doc_history_list')}?docs_cd={confirmed_document.document_type_id}")

        messages.success(request, f"{get_document_label(document.document_type_id)} 확정본을 생성했습니다.")
        return redirect(_build_generation_redirect(None, auto_start=True, resume=True))

    messages.success(request, "산출물을 확정했습니다.")
    return redirect(reverse("doc_detail", args=[confirmed_document.sn]))


@login_required(login_url="home")
def document_restore_revision(request, document_sn, detail_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))
    if document.possession_user_id != actor.sn:
        messages.error(request, "문서를 점유한 사용자만 복원할 수 있습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    source_detail = get_detail_by_sn(document, detail_sn)
    if source_detail is None:
        messages.error(request, "복원할 이력을 찾을 수 없습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    try:
        restore_revision(document, actor, source_detail)
    except ValueError:
        messages.error(request, _legacy_detail_error_message())
        return redirect(reverse("doc_detail", args=[document.sn]))
    messages.success(request, "선택한 버전으로 복원했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


@login_required(login_url="home")
def document_auto_apply(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    latest_detail = get_latest_detail(document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))
    if document.possession_user_id != actor.sn:
        if _is_ajax_request(request):
            return JsonResponse({"message": "문서를 점유한 사용자만 회의 내용을 반영할 수 있습니다."}, status=403)
        messages.error(request, "문서를 점유한 사용자만 회의 내용을 반영할 수 있습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))
    if not _can_show_auto_apply(document, actor, current_project, latest_detail):
        if _is_ajax_request(request):
            return JsonResponse({"message": "최신 산출물의 최신 내용에서만 회의 내용을 자동 적용할 수 있습니다."}, status=403)
        messages.error(request, "최신 산출물의 최신 내용에서만 회의 내용을 자동 적용할 수 있습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    selected_file_ids = request.POST.getlist("selected_files")
    selected_files = list(
        get_project_files(current_project, file_ids=selected_file_ids, allowed_types=("FILE_MEETING",))
    )
    if not selected_files:
        if _is_ajax_request(request):
            return JsonResponse({"message": "회의록 파일을 하나 이상 선택해 주세요."}, status=400)
        messages.error(request, "회의록 파일을 하나 이상 선택해 주세요.")
        return redirect(_document_detail_redirect(document, modal="meeting-files"))

    job_result = start_auto_apply_job(current_project, document.document_type_id, selected_files)
    if job_result["status"] == "error" or job_result["document"] is None:
        if _is_ajax_request(request):
            return JsonResponse({"message": job_result["message"]}, status=502)
        messages.error(request, job_result["message"])
        return redirect(_document_detail_redirect(document, modal="meeting-files"))

    if _is_ajax_request(request):
        return JsonResponse(
            _build_document_job_response(
                "auto_apply",
                document.document_type_id,
                job_result["message"],
                job_result["document"],
                status=job_result["status"],
            )
        )

    if job_result["status"] == "started":
        messages.success(request, "회의 내용 자동 적용을 요청했습니다.")
    else:
        messages.info(request, job_result["message"])
    return redirect(reverse("doc_detail", args=[document.sn]))


@login_required(login_url="home")
def document_request_approval(request, document_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST":
        return redirect(reverse("doc_detail", args=[document.sn]))
    _, pending_approval = get_document_view_state(document, actor, preferred_mode="view")
    if not can_request_approval(
        document,
        actor,
        pending_approval=pending_approval,
        is_generation_draft=(document.version == "0"),
    ):
        messages.error(request, "현재 화면에서 승인 요청할 수 없습니다.")
        return redirect(reverse("doc_detail", args=[document.sn]))

    request_content = request.POST.get("request_content", "").strip()
    if not request_content:
        messages.error(request, "승인 요청 내용을 입력해 주세요.")
        return redirect(_document_detail_redirect(document, modal="approval-request"))

    create_approval_request(document, actor, request_content)
    messages.success(request, "프로젝트 관리자에게 승인 요청을 전송했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


@login_required(login_url="home")
def document_history_preview(request, document_sn, detail_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    document = _get_document_or_404(current_project, document_sn)
    _ensure_document_access(current_project, actor, document)

    detail = get_detail_by_sn(document, detail_sn)
    if detail is None:
        return JsonResponse({"message": "Preview revision was not found."}, status=404)
    try:
        preview_text = extract_text_from_docx(get_document_detail_bytes(detail)) or "Document content is empty."
    except ValueError:
        return JsonResponse({"message": _legacy_detail_error_message()}, status=409)

    return JsonResponse(
        {
            "preview_text": preview_text,
            "creator_name": getattr(detail.created_by, "name", "-") or "-",
            "created_at": detail.created_at.strftime("%Y-%m-%d %H:%M"),
        }
    )


def document_content(request, document_sn):
    token = request.GET.get("token", "").strip()
    document = _get_document_by_sn_or_404(document_sn)
    if not validate_document_content_token(document, token):
        current_project, _ = resolve_current_project(request)
        actor = get_actor(request)
        _ensure_document_access(current_project, actor, document)

    latest_detail = get_latest_detail(document)
    try:
        content = get_document_detail_bytes(latest_detail)
    except ValueError:
        return HttpResponse(_legacy_detail_error_message(), status=409, content_type="text/plain; charset=utf-8")
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{get_document_title(document)}"'
    return response


@login_required(login_url="home")
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
            text_content=None if content_bytes else payload.get("content_text") or extract_text_from_docx(get_document_detail_bytes(get_latest_detail(document))),
            modification_content="OnlyOffice 저장",
        )
    return JsonResponse({"error": 0})


@login_required(login_url="home")
def document_cancel_approval(request, approval_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("detail__document__project", "created_by", "approval_status"),
        approval_sn=approval_sn,
    )
    document = approval.detail.document
    _ensure_document_access(current_project, actor, document)
    if request.method == "POST" and approval.created_by_id == actor.sn and approval.approval_status_id == "APRV_REQ":
        cancel_approval_request(approval)
        messages.success(request, "승인 요청을 취소했습니다.")
    return redirect(reverse("doc_detail", args=[document.sn]))


@login_required(login_url="home")
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


@login_required(login_url="home")
def approval_detail(request, approval_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    approval = get_object_or_404(
        DocumentApproval.objects.select_related(
            "detail__document__project",
            "detail__document__document_type",
            "detail__document__created_by",
            "detail__document__possession_user",
            "approval_status",
            "created_by",
        ),
        approval_sn=approval_sn,
    )
    document = approval.detail.document
    _ensure_document_access(current_project, actor, document)

    is_manager = is_project_manager(current_project, actor)
    if not is_manager and approval.created_by_id != actor.sn:
        raise Http404

    previous_document = latest_confirmed_document(current_project, document.document_type_id)
    previous_detail = get_latest_detail(previous_document) if previous_document else None
    try:
        previous_text = extract_text_from_docx(get_document_detail_bytes(previous_detail))
        updated_text = extract_text_from_docx(get_document_detail_bytes(approval.detail))
    except ValueError:
        messages.error(request, _legacy_detail_error_message())
        return redirect(reverse("doc_approval_list"))
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
        "can_take_action": is_manager and approval.approval_status_id == "APRV_REQ",
        "open_approve_modal": request.GET.get("modal") == "approve",
        "open_reject_modal": request.GET.get("modal") == "reject",
    }
    return render(request, "docs/approval_detail.html", context)


@login_required(login_url="home")
def approval_consistency(request, approval_sn):
    if request.method != "POST":
        return redirect(reverse("doc_approval_detail", args=[approval_sn]))
    return redirect(f"{reverse('doc_approval_detail', args=[approval_sn])}?consistency=1")


@login_required(login_url="home")
def approval_approve(request, approval_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("detail__document__project"),
        approval_sn=approval_sn,
    )
    document = approval.detail.document
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST" or not is_project_manager(current_project, actor):
        return redirect(reverse("doc_approval_detail", args=[approval.approval_sn]))
    if approval.approval_status_id != "APRV_REQ":
        messages.error(request, "처리할 수 없는 승인 요청 상태입니다.")
        return redirect(reverse("doc_approval_detail", args=[approval.approval_sn]))

    new_version = request.POST.get("new_version", "").strip()
    if not new_version:
        messages.error(request, "새 버전명을 입력해 주세요.")
        return redirect(_approval_detail_redirect(approval, modal="approve"))
    if has_document_version(document.project, document.document_type_id, new_version):
        messages.error(request, "동일한 산출물 종류에 같은 버전이 이미 존재합니다. 새 버전명을 다시 입력해 주세요.")
        return redirect(_approval_detail_redirect(approval, modal="approve"))

    try:
        approved_document, _ = approve_request(approval, actor, new_version)
    except ValueError:
        messages.error(request, _legacy_detail_error_message())
        return redirect(reverse("doc_approval_detail", args=[approval.approval_sn]))
    messages.success(request, "승인 요청을 반영하고 새 버전을 생성했습니다.")
    return redirect(reverse("doc_detail", args=[approved_document.sn]))


@login_required(login_url="home")
def approval_reject(request, approval_sn):
    current_project, _ = resolve_current_project(request)
    actor = get_actor(request)
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("detail__document__project"),
        approval_sn=approval_sn,
    )
    document = approval.detail.document
    _ensure_document_access(current_project, actor, document)
    if request.method != "POST" or not is_project_manager(current_project, actor):
        return redirect(reverse("doc_approval_detail", args=[approval.approval_sn]))
    if approval.approval_status_id != "APRV_REQ":
        messages.error(request, "처리할 수 없는 승인 요청 상태입니다.")
        return redirect(reverse("doc_approval_detail", args=[approval.approval_sn]))

    reason = request.POST.get("rejection_reason", "").strip()
    if not reason:
        messages.error(request, "반려 사유를 입력해 주세요.")
        return redirect(_approval_detail_redirect(approval, modal="reject"))

    reject_request(approval, actor, reason)
    messages.success(request, "승인 요청을 반려했습니다.")
    return redirect(reverse("doc_approval_detail", args=[approval.approval_sn]))
