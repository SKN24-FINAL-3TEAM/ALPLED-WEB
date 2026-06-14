from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import redirect, render

from common.models import Code, YesNoChoices
from common.signals import ensure_initial_reference_data
from users.models import User

from .models import Project, ProjectUserRole


def _next_sn(model):
    current_max = model.objects.aggregate(max_sn=Max("sn"))["max_sn"] or 0
    return current_max + 1


def _get_admin_user():
    return User.objects.filter(user_id="admin").first()


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


def _build_project_rows(projects):
    rows = []
    for project in projects[:10]:
        manager_role = (
            ProjectUserRole.objects.filter(project=project, role_id="ROLE_MANAGER")
            .select_related("user")
            .order_by("sn")
            .first()
        )
        if manager_role is None:
            manager_role = (
                ProjectUserRole.objects.filter(project=project)
                .select_related("user")
                .order_by("sn")
                .first()
            )

        rows.append(
            {
                "sn": project.sn,
                "project_id": f"PRJ{project.sn:03d}",
                "name": project.name,
                "manager_name": manager_role.user.name if manager_role else "미지정",
                "created_at": project.created_at,
                "is_deleted": project.is_deleted,
            }
        )
    return rows


def _parse_user_ids(raw_value):
    if not raw_value:
        return []
    return [value.strip() for value in raw_value.split(",") if value.strip()]


@transaction.atomic
def _create_project(request):
    project_name = request.POST.get("project_name", "").strip()
    manager_user_ids = list(dict.fromkeys(_parse_user_ids(request.POST.get("manager_user_ids", ""))))
    member_user_ids = list(dict.fromkeys(_parse_user_ids(request.POST.get("member_user_ids", ""))))

    if not project_name:
        messages.error(request, "프로젝트명을 입력하세요.")
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
        role_manager, _ = Code.objects.get_or_create(code="ROLE_MANAGER", defaults={"name": "관리자"})
        role_member, _ = Code.objects.get_or_create(code="ROLE_MEMBER", defaults={"name": "멤버"})
        admin_user = _get_admin_user()

        project = Project.objects.create(
            sn=_next_sn(Project),
            name=project_name,
            is_deleted=YesNoChoices.NO,
            created_by=admin_user,
            updated_by=admin_user,
        )

        next_role_sn = _next_sn(ProjectUserRole)
        for user_id in manager_user_ids:
            ProjectUserRole.objects.create(
                sn=next_role_sn,
                project=project,
                user=users_by_id[user_id],
                role=role_manager,
                created_by=admin_user,
                updated_by=admin_user,
            )
            next_role_sn += 1

        for user_id in member_user_ids:
            ProjectUserRole.objects.create(
                sn=next_role_sn,
                project=project,
                user=users_by_id[user_id],
                role=role_member,
                created_by=admin_user,
                updated_by=admin_user,
            )
            next_role_sn += 1
    except Exception:
        messages.error(request, "프로젝트를 저장할 수 없습니다.")
        return False

    messages.success(request, "프로젝트가 등록되었습니다.")
    return True


@login_required(login_url="home")
def project_list(request):
    ensure_initial_reference_data()

    if request.method == "POST":
        if _create_project(request):
            return redirect("project_list")
        return redirect("project_list")

    query = request.GET.get("q", "").strip()
    search_field = request.GET.get("field", "all")

    projects = Project.objects.all().order_by("sn")
    if query:
        if search_field == "name":
            projects = projects.filter(name__icontains=query)
        elif search_field == "manager":
            projects = projects.filter(user_roles__user__name__icontains=query).distinct()
        else:
            projects = projects.filter(
                Q(name__icontains=query) | Q(user_roles__user__name__icontains=query)
            ).distinct()

    project_rows = _build_project_rows(projects)
    search_users, user_active, user_search_field, user_query = _search_users(request)
    open_project_user_search = request.GET.get("open_project_user_search") == "1"
    project_target_role = request.GET.get("project_target_role", "manager")

    context = {
        "active_menu": "projects",
        "projects": project_rows,
        "search_field": search_field,
        "query": query,
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
    }
    return render(request, "projects/project_list.html", context)
