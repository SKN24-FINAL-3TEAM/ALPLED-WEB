from django.db.models import Q
from django.shortcuts import render

from common.models import YesNoChoices
from .models import Project, ProjectUserRole


def project_list(request):
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

    project_rows = []
    if projects.exists():
        for project in projects[:10]:
            manager_role = (
                ProjectUserRole.objects.filter(project=project)
                .select_related("user", "role")
                .order_by("sn")
                .first()
            )
            project_rows.append(
                {
                    "sn": project.sn,
                    "project_id": f"PRJ{project.sn:03d}",
                    "name": project.name,
                    "manager_name": manager_role.user.name if manager_role else "관리자 미지정",
                    "created_at": project.created_at,
                    "is_deleted": project.is_deleted,
                }
            )
    else:
        project_rows = []

    context = {
        "active_menu": "projects",
        "projects": project_rows,
        "search_field": search_field,
        "query": query,
        "page_size": request.GET.get("page_size", "10"),
        "status_filter": request.GET.get("detail_status", "all"),
        "title": "프로젝트 관리",
        "yes_no_choices": YesNoChoices.choices,
        "search_users": [
            {"user_id": "USER003", "name": "사용자 3", "position": "사원", "department": "부서001", "use_yn": "Y", "created_at": "YYYY-MM-DD HH24:MI"},
        ],
    }
    return render(request, "projects/project_list.html", context)
