from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.signals import ensure_initial_reference_data
from common.models import YesNoChoices
from common.project_selection import get_safe_next_url
from projects.models import ProjectUserRole

from .models import User


TEMP_PASSWORD = "abc1234"


def login_view(request):
    ensure_initial_reference_data()

    if request.user.is_authenticated:
        return redirect("user_list")

    if request.method == "POST":
        user_id = request.POST.get("user_id", "").strip()
        password = request.POST.get("password", "")

        if not user_id or not password:
            messages.error(request, "아이디와 비밀번호를 입력해 주세요.")
        else:
            user = authenticate(request, user_id=user_id, password=password)
            if user is not None and user.is_active:
                login(request, user)
                next_url = get_safe_next_url(request)
                if next_url in {"", "/", reverse("home"), reverse("login")}:
                    next_url = reverse("user_list")
                return redirect(next_url)
            messages.error(request, "아이디 또는 비밀번호가 올바르지 않습니다.")

    return render(
        request,
        "users/login.html",
        {
            "title": "로그인",
            "next_url": request.POST.get("next") or request.GET.get("next") or "",
        },
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


def _demo_users():
    return [
        {
            "sn": index,
            "user_id": f"USER{index:03d}",
            "name": f"사용자{index:03d}",
            "department": "개발부서" if index != 3 else "부서01",
            "position": "사원" if index % 2 else "대리",
            "use_yn": "N" if index == 3 else "Y",
        }
        for index in range(1, 11)
    ]


def _next_sn(model):
    current_max = model.objects.aggregate(max_sn=Max("sn"))["max_sn"] or 0
    return current_max + 1


def _get_actor():
    return User.objects.filter(user_id="admin").first() or User.objects.order_by("sn").first()


def _build_create_form_data(request=None):
    source = request.POST if request is not None else {}
    return {
        "user_id": source.get("user_id", "").strip(),
        "name": source.get("name", "").strip(),
        "department": source.get("department", "").strip(),
        "position": source.get("position", "").strip(),
        "use_yn": source.get("use_yn", YesNoChoices.YES),
    }


@transaction.atomic
def _create_user(request):
    form_data = _build_create_form_data(request)

    if not form_data["user_id"]:
        messages.error(request, "사원번호를 입력해 주세요.")
        return False, form_data

    if not form_data["name"]:
        messages.error(request, "이름을 입력해 주세요.")
        return False, form_data

    if form_data["use_yn"] not in {YesNoChoices.YES, YesNoChoices.NO}:
        messages.error(request, "활성화 여부 값이 올바르지 않습니다.")
        return False, form_data

    if User.objects.filter(user_id=form_data["user_id"]).exists():
        messages.error(request, "이미 존재하는 사원번호입니다.")
        return False, form_data

    actor = _get_actor()
    User.objects.create_user(
        sn=_next_sn(User),
        user_id=form_data["user_id"],
        password=TEMP_PASSWORD,
        name=form_data["name"],
        department=form_data["department"] or None,
        position=form_data["position"] or None,
        sys_mngr_yn=YesNoChoices.NO,
        tmpr_pswd_yn=YesNoChoices.YES,
        use_yn=form_data["use_yn"],
        created_by=actor,
        updated_by=actor,
    )
    messages.success(request, "사용자를 추가했습니다.")
    return True, _build_create_form_data()


@login_required(login_url="home")
def user_list(request):
    ensure_initial_reference_data()
    create_form = _build_create_form_data()
    open_user_create_modal = False

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_user":
            created, create_form = _create_user(request)
            if created:
                return redirect("user_list")
            open_user_create_modal = True

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
                "project": {"name": "AI-DLC Project (예시)"},
                "role": {"code": "MANAGER"},
            },
            {
                "project": {"name": "Camp Project (예시)"},
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
        "create_user_form": create_form,
        "open_user_create_modal": open_user_create_modal,
        "temp_password": TEMP_PASSWORD,
    }
    return render(request, "users/user_list.html", context)
