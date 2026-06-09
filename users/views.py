from django.db.models import Q
from django.shortcuts import render

from projects.models import ProjectUserRole
from .models import User


def _demo_users():
    return [
        {
            "sn": index,
            "user_id": f"USER{index:03d}",
            "name": f"사용자 {index:03d}",
            "department": "개발부서" if index != 3 else "부서001",
            "position": "사원" if index % 2 else "대리",
            "use_yn": "N" if index == 3 else "Y",
        }
        for index in range(1, 11)
    ]


def user_list(request):
    active = request.GET.get("active", "all")
    search_field = request.GET.get("field", "all")
    query = request.GET.get("q", "").strip()

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

    user_rows = list(users[:10]) if users.exists() else _demo_users()
    selected_user = users.first() if users.exists() else None

    if selected_user is not None:
        project_roles = (
            ProjectUserRole.objects.filter(user=selected_user)
            .select_related("project", "role")
            .order_by("sn")
        )
        role_rows = list(project_roles) if project_roles.exists() else []
    else:
        role_rows = [
            {
                "project": {"name": "AI-DLC Project (팀장)"},
                "role": {"code": "MANAGER"},
            },
            {
                "project": {"name": "Camp Project (팀원)"},
                "role": {"code": "MEMBER"},
            },
        ]

    context = {
        "active_menu": "users",
        "users": user_rows,
        "selected_user": selected_user or _demo_users()[0],
        "user_roles": role_rows,
        "active_filter": active,
        "search_field": search_field,
        "query": query,
        "page_size": request.GET.get("page_size", "10"),
        "title": "사용자 관리",
    }
    return render(request, "users/user_list.html", context)
