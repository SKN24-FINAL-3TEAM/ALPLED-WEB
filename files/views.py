import io
import mimetypes
import os
import zipfile
from urllib.parse import quote

from django.contrib import messages
from django.db import transaction
from django.db.models import Max, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from common.models import ProjectFile
from common.project_selection import resolve_current_project
from common.signals import ensure_initial_reference_data
from users.models import User


MAX_UPLOAD_FILES = 5
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {"docx", "hwp", "pdf"}
FILE_TYPE_MAP = {
    "RFP": "FILE_RFP",
    "MEETING": "FILE_MEETING",
}


def _next_sn(model):
    current_max = model.objects.aggregate(max_sn=Max("sn"))["max_sn"] or 0
    return current_max + 1


def _get_actor():
    return User.objects.filter(user_id="admin").first() or User.objects.order_by("sn").first()


def _build_file_list_redirect_url():
    return reverse("file_list")


def _apply_filters(request, queryset):
    file_type = request.GET.get("file_type", "all")
    search_field = request.GET.get("field", "all")
    query = request.GET.get("q", "").strip()

    if file_type == "RFP":
        queryset = queryset.filter(file_type_id=FILE_TYPE_MAP["RFP"])
    elif file_type == "MEETING":
        queryset = queryset.filter(file_type_id=FILE_TYPE_MAP["MEETING"])

    if query:
        if search_field == "creator":
            queryset = queryset.filter(created_by__name__icontains=query)
        elif search_field == "name":
            queryset = queryset.filter(name__icontains=query)
        else:
            queryset = queryset.filter(
                Q(created_by__name__icontains=query) | Q(name__icontains=query)
            )

    return queryset, file_type, search_field, query


def _build_project_file_rows(queryset):
    rows = []
    for index, document in enumerate(queryset, start=1):
        rows.append(
            {
                "sn": document.sn,
                "display_no": index,
                "name": document.name,
                "type_name": getattr(document.file_type, "name", "-"),
                "creator_name": getattr(document.created_by, "name", "-") or "-",
                "created_at": document.created_at,
            }
        )
    return rows


def _validate_uploaded_files(files):
    if len(files) > MAX_UPLOAD_FILES:
        return f"한 번에 최대 {MAX_UPLOAD_FILES}개 파일까지 등록할 수 있습니다."

    for uploaded_file in files:
        extension = os.path.splitext(uploaded_file.name)[1].lower().lstrip(".")
        if extension not in ALLOWED_EXTENSIONS:
            return "업로드 가능한 파일 형식은 .docx, .hwp, .pdf 입니다."
        if uploaded_file.size > MAX_FILE_SIZE:
            return f"각 파일은 최대 {MAX_FILE_SIZE // (1024 * 1024)}MB까지 업로드할 수 있습니다."

    return None


@transaction.atomic
def _upload_files(request, project):
    if project is None:
        messages.error(request, "먼저 프로젝트를 선택해 주세요.")
        return redirect(_build_file_list_redirect_url())

    actor = _get_actor()
    rfp_files = request.FILES.getlist("rfp_files")
    meeting_files = request.FILES.getlist("meeting_files")
    uploaded_files = [*rfp_files, *meeting_files]

    if not uploaded_files:
        messages.error(request, "업로드할 파일을 선택해 주세요.")
        return redirect(_build_file_list_redirect_url())

    validation_error = _validate_uploaded_files(uploaded_files)
    if validation_error:
        messages.error(request, validation_error)
        return redirect(_build_file_list_redirect_url())

    next_sn = _next_sn(ProjectFile)
    for file_code, files in (
        (FILE_TYPE_MAP["RFP"], rfp_files),
        (FILE_TYPE_MAP["MEETING"], meeting_files),
    ):
        for uploaded_file in files:
            extension = os.path.splitext(uploaded_file.name)[1].lower().lstrip(".")
            ProjectFile.objects.create(
                sn=next_sn,
                project=project,
                file_type_id=file_code,
                name=os.path.basename(uploaded_file.name),
                path=uploaded_file.name[:300],
                content=uploaded_file.read(),
                size=uploaded_file.size,
                extension=extension[:4],
                created_by=actor,
                updated_by=actor,
            )
            next_sn += 1

    messages.success(request, "파일이 등록되었습니다.")
    return redirect(_build_file_list_redirect_url())


@transaction.atomic
def _delete_files(request, project):
    selected_ids = request.POST.getlist("selected_files")
    if not selected_ids:
        messages.error(request, "파일을 하나 이상 선택해 주세요.")
        return redirect(_build_file_list_redirect_url())

    deleted_count, _ = ProjectFile.objects.filter(
        project=project,
        sn__in=selected_ids,
    ).delete()
    if deleted_count:
        messages.success(request, "선택한 파일을 삭제했습니다.")
    else:
        messages.error(request, "삭제할 파일이 없습니다.")

    return redirect(_build_file_list_redirect_url())


def _download_files(request, project):
    selected_ids = request.POST.getlist("selected_files")
    if not selected_ids:
        messages.error(request, "파일을 하나 이상 선택해 주세요.")
        return redirect(_build_file_list_redirect_url())

    files = list(
        ProjectFile.objects.filter(project=project, sn__in=selected_ids).order_by("sn")
    )
    if not files:
        messages.error(request, "다운로드할 파일이 없습니다.")
        return redirect(_build_file_list_redirect_url())

    if len(files) == 1:
        project_file = files[0]
        mime_type = mimetypes.guess_type(project_file.name)[0] or "application/octet-stream"
        response = HttpResponse(project_file.content, content_type=mime_type)
        response["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(project_file.name)}"
        )
        return response

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for project_file in files:
            archive.writestr(project_file.name, project_file.content)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = "attachment; filename=project-files.zip"
    return response


def file_list(request):
    ensure_initial_reference_data()
    current_project, _ = resolve_current_project(request)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "upload":
            return _upload_files(request, current_project)
        if action == "delete":
            return _delete_files(request, current_project)
        if action == "download":
            return _download_files(request, current_project)
        return redirect(_build_file_list_redirect_url())

    documents = ProjectFile.objects.none()
    if current_project is not None:
        documents = (
            ProjectFile.objects.filter(project=current_project)
            .select_related("file_type", "created_by")
            .order_by("-created_at", "-sn")
        )

    documents, file_type, search_field, query = _apply_filters(request, documents)

    context = {
        "active_menu": "files",
        "title": "파일 관리",
        "current_project": current_project,
        "documents": _build_project_file_rows(documents),
        "file_type": file_type,
        "search_field": search_field,
        "query": query,
        "max_upload_files": MAX_UPLOAD_FILES,
        "max_file_size_mb": MAX_FILE_SIZE // (1024 * 1024),
    }
    return render(request, "files/file_list.html", context)
