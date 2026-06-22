from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from common.project_selection import get_safe_next_url

from common.models import Code, YesNoChoices
from common.signals import ensure_initial_reference_data
from users.models import User

from .models import Project, ProjectUserRole


DEFAULT_DOCUMENT_CODE = "DOC_SRS"


def _get_admin_user():
    return User.objects.filter(user_id="admin").first()


def _get_default_redirect_url():
    return f"{reverse('doc_history_list')}?docs_cd={DEFAULT_DOCUMENT_CODE}"


def _get_project_redirect_url(request):
    next_url = get_safe_next_url(request)
    if next_url and next_url != "/":
        return next_url
    return reverse("project_list")


def _redirect_non_admin(request):
    messages.error(request, "관리자만 접근할 수 있습니다.")
    return redirect(_get_default_redirect_url())


def _search_users(request):
    active = request.GET.get("user_active", "all")
    search_field = request.GET.get("user_field", "all")
    query = request.GET.get("user_q", "").strip()

    users = User.objects.all().order_by("sn")
    if active in {"Y", "N"}:
        users = users.filter(use_yn=active)

    if query:
        if search_field == "user_id":
            users = users.filter(user_id__icontains=query)
        elif search_field == "name":
            users = users.filter(name__icontains=query)
        elif search_field == "position":
            users = users.filter(position__icontains=query)
        elif search_field == "department":
            users = users.filter(department__icontains=query)
        else:
            users = users.filter(
                Q(user_id__icontains=query)
                | Q(name__icontains=query)
                | Q(position__icontains=query)
                | Q(department__icontains=query)
            )

    return list(users[:10]), active, search_field, query


def _build_project_rows(projects, preserved_querystring=""):
    rows = []
    for project in projects[:10]:
        manager_names = list(
            ProjectUserRole.objects.filter(project=project, role_id="ROLE_MANAGER")
            .select_related("user")
            .order_by("sn")
            .values_list("user__name", flat=True)
        )
        if not manager_names:
            manager_names = list(
                ProjectUserRole.objects.filter(project=project)
                .select_related("user")
                .order_by("sn")
                .values_list("user__name", flat=True)[:1]
            )
        edit_query = urlencode(
            {
                "open_project_form": "1",
                "project_form_mode": "edit",
                "project_sn": project.sn,
            }
        )
        if preserved_querystring:
            edit_query = f"{preserved_querystring}&{edit_query}"

        rows.append(
            {
                "sn": project.sn,
                "project_id": f"PRJ{project.sn:03d}",
                "name": project.name,
                "manager_name": ", ".join(manager_names) if manager_names else "미지정",
                "created_at": project.created_at,
                "is_deleted": project.is_deleted,
                "edit_url": f"{reverse('project_list')}?{edit_query}",
            }
        )
    return rows


@transaction.atomic
def _delete_project(request):
    project_sn = request.POST.get("project_sn", "").strip()
    target_project = Project.objects.filter(sn=project_sn, is_deleted=YesNoChoices.NO).first()
    if target_project is None:
        messages.error(request, "삭제할 프로젝트를 찾을 수 없습니다.")
        return False

    target_project.is_deleted = YesNoChoices.YES
    target_project.updated_by = request.user
    target_project.save(update_fields=["is_deleted", "updated_by"])
    messages.success(request, "프로젝트가 삭제되었습니다.")
    return True


def _parse_user_ids(raw_value):
    if not raw_value:
        return []
    return [value.strip() for value in raw_value.split(",") if value.strip()]


def _get_project_roles(actor):
    role_manager, _ = Code.objects.get_or_create(
        code="ROLE_MANAGER",
        defaults={"name": "관리자", "created_by": actor, "updated_by": actor},
    )
    role_member, _ = Code.objects.get_or_create(
        code="ROLE_MEMBER",
        defaults={"name": "멤버", "created_by": actor, "updated_by": actor},
    )
    return role_manager, role_member


def _build_selected_user_rows(user_ids):
    users_by_id = User.objects.in_bulk(user_ids, field_name="user_id")
    rows = []
    for user_id in user_ids:
        user = users_by_id.get(user_id)
        if user is None:
            continue
        rows.append(
            {
                "user_id": user.user_id,
                "name": user.name,
                "position": user.position or "",
                "department": user.department or "",
            }
        )
    return rows


def _get_project_form_state(request):
    form_mode = request.GET.get("project_form_mode", "create")
    if form_mode not in {"create", "edit"}:
        form_mode = "create"

    project_sn = request.GET.get("project_sn", "").strip()
    project = Project.objects.filter(sn=project_sn).first() if project_sn else None
    if form_mode == "edit" and project is None:
        form_mode = "create"
        project_sn = ""

    project_name = request.GET.get("project_name", "").strip()
    manager_user_ids = _parse_user_ids(request.GET.get("manager_user_ids", ""))
    member_user_ids = _parse_user_ids(request.GET.get("member_user_ids", ""))

    if form_mode == "edit" and project is not None and not request.GET.get("manager_user_ids") and not request.GET.get("member_user_ids"):
        manager_user_ids = list(
            ProjectUserRole.objects.filter(project=project, role_id="ROLE_MANAGER")
            .select_related("user")
            .order_by("sn")
            .values_list("user__user_id", flat=True)
        )
        member_user_ids = list(
            ProjectUserRole.objects.filter(project=project, role_id="ROLE_MEMBER")
            .select_related("user")
            .order_by("sn")
            .values_list("user__user_id", flat=True)
        )
    if form_mode == "edit" and project is not None and not project_name:
        project_name = project.name

    return {
        "open_project_form": request.GET.get("open_project_form") == "1" or request.GET.get("open_project_user_search") == "1",
        "project_form_mode": form_mode,
        "project_form_project_sn": str(project.sn) if project is not None else project_sn,
        "project_form_project_id": f"PRJ{project.sn:03d}" if project is not None else "",
        "project_form_created_at": project.created_at if project is not None else None,
        "project_form_name": project_name,
        "project_form_manager_user_ids": ",".join(manager_user_ids),
        "project_form_member_user_ids": ",".join(member_user_ids),
        "project_form_manager_users": _build_selected_user_rows(manager_user_ids),
        "project_form_member_users": _build_selected_user_rows(member_user_ids),
        "project_form_title": "프로젝트 상세 / 수정" if form_mode == "edit" else "프로젝트 등록",
        "project_form_subtitle": "프로젝트와 담당 인원을 함께 관리합니다." if form_mode == "edit" else "프로젝트와 담당 인원을 함께 등록합니다.",
        "project_form_submit_label": "수정" if form_mode == "edit" else "프로젝트 등록",
    }


@transaction.atomic
def _save_project(request, *, project=None):
    actor = request.user
    project_name = request.POST.get("project_name", "").strip()
    manager_user_ids = list(dict.fromkeys(_parse_user_ids(request.POST.get("manager_user_ids", ""))))
    member_user_ids = list(dict.fromkeys(_parse_user_ids(request.POST.get("member_user_ids", ""))))

    if not project_name:
        messages.error(request, "프로젝트명을 입력해 주세요.")
        return False

    selected_user_ids = list(dict.fromkeys(manager_user_ids + member_user_ids))
    if not selected_user_ids:
        messages.error(request, "최소 1명의 사용자를 추가해야 합니다.")
        return False

    duplicated_user_ids = sorted(set(manager_user_ids).intersection(member_user_ids))
    if duplicated_user_ids:
        messages.error(request, "이미 추가된 사용자가 포함되어 있습니다.")
        return False

    users_by_id = User.objects.in_bulk(selected_user_ids, field_name="user_id")
    missing_user_ids = [user_id for user_id in selected_user_ids if user_id not in users_by_id]
    if missing_user_ids:
        messages.error(request, "선택한 사용자 정보가 존재하지 않습니다.")
        return False

    try:
        role_manager, role_member = _get_project_roles(actor)

        if project is None:
            project = Project.objects.create(
                name=project_name,
                is_deleted=YesNoChoices.NO,
                created_by=actor,
                updated_by=actor,
            )
        else:
            project.name = project_name
            project.updated_by = actor
            project.save(update_fields=["name", "updated_by"])
            ProjectUserRole.objects.filter(project=project).delete()

        for user_id in manager_user_ids:
            ProjectUserRole.objects.create(
                project=project,
                user=users_by_id[user_id],
                role=role_manager,
                created_by=actor,
                updated_by=actor,
            )

        for user_id in member_user_ids:
            ProjectUserRole.objects.create(
                project=project,
                user=users_by_id[user_id],
                role=role_member,
                created_by=actor,
                updated_by=actor,
            )
    except Exception:
        messages.error(request, "프로젝트를 저장할 수 없습니다.")
        return False

    messages.success(request, "프로젝트가 수정되었습니다." if project and request.POST.get("action") == "update_project" else "프로젝트가 등록되었습니다.")
    return True


@login_required(login_url="home")
def project_list(request):
    ensure_initial_reference_data()

    if not request.user.is_staff:
        return _redirect_non_admin(request)

    if request.method == "POST":
        action = request.POST.get("action", "create_project")
        if action == "delete_project":
            _delete_project(request)
            return redirect(_get_project_redirect_url(request))

        target_project = None
        if action == "update_project":
            project_sn = request.POST.get("project_sn", "").strip()
            target_project = Project.objects.filter(sn=project_sn, is_deleted=YesNoChoices.NO).first()
            if target_project is None:
                messages.error(request, "수정할 프로젝트를 찾을 수 없습니다.")
                return redirect(_get_project_redirect_url(request))
        if _save_project(request, project=target_project):
            return redirect(_get_project_redirect_url(request))
        return redirect(_get_project_redirect_url(request))

    query = request.GET.get("q", "").strip()
    search_field = request.GET.get("field", "all")
    preserved_querystring = urlencode(
        {
            "field": search_field,
            "q": query,
        }
    )

    projects = Project.objects.filter(is_deleted=YesNoChoices.NO).order_by("sn")
    if query:
        if search_field == "name":
            projects = projects.filter(name__icontains=query)
        elif search_field == "manager":
            projects = projects.filter(user_roles__user__name__icontains=query).distinct()
        else:
            projects = projects.filter(
                Q(name__icontains=query) | Q(user_roles__user__name__icontains=query)
            ).distinct()

    project_rows = _build_project_rows(projects, preserved_querystring)
    search_users, user_active, user_search_field, user_query = _search_users(request)
    open_project_user_search = request.GET.get("open_project_user_search") == "1"
    project_target_role = request.GET.get("project_target_role", "manager")
    project_form_state = _get_project_form_state(request)

    context = {
        "active_menu": "projects",
        "projects": project_rows,
        "search_field": search_field,
        "query": query,
        "preserved_querystring": preserved_querystring,
        "page_size": request.GET.get("page_size", "10"),
        "status_filter": request.GET.get("detail_status", "all"),
        "title": "프로젝트 관리",
        "yes_no_choices": YesNoChoices.choices,
        "search_users": search_users,
        "user_active": user_active,
        "user_search_field": user_search_field,
        "user_query": user_query,
        "open_project_user_search": open_project_user_search,
        "project_target_role": project_target_role,
        "admin_user": _get_admin_user(),
        **project_form_state,
    }
    return render(request, "projects/project_list.html", context)
