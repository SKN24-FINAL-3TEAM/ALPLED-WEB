from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.models import YesNoChoices
from common.project_selection import get_safe_next_url
from common.signals import ensure_initial_reference_data
from projects.models import ProjectUserRole

from .models import User


DEFAULT_DOCUMENT_CODE = "DOC_SRS"
TEMP_PASSWORD = "abc1234"
TEMP_PASSWORD_REDIRECT_SESSION_KEY = "temp_password_redirect_url"


def _get_authenticated_home_url(user):
    if getattr(user, "is_staff", False):
        return reverse("user_list")
    return f"{reverse('doc_history_list')}?docs_cd={DEFAULT_DOCUMENT_CODE}"


def _redirect_non_admin(request):
    messages.error(request, "관리자만 접근할 수 있습니다.")
    return redirect(_get_authenticated_home_url(request.user))


def _require_admin(request):
    if getattr(request.user, "is_staff", False):
        return None
    return _redirect_non_admin(request)


def login_view(request):
    ensure_initial_reference_data()

    if request.user.is_authenticated:
        if request.user.tmpr_pswd_yn == YesNoChoices.YES:
            return redirect("temp_password_notice")
        return redirect(_get_authenticated_home_url(request.user))

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
                    next_url = _get_authenticated_home_url(user)
                if user.tmpr_pswd_yn == YesNoChoices.YES:
                    request.session[TEMP_PASSWORD_REDIRECT_SESSION_KEY] = next_url
                    request.session.modified = True
                    return redirect("temp_password_notice")
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
            "name": f"사용자 {index:03d}",
            "department": "개발부서" if index != 3 else "부서1",
            "position": "사원" if index % 2 else "대리",
            "use_yn": "N" if index == 3 else "Y",
            "tmpr_pswd_yn": "N",
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


def _build_profile_form_data(user, request=None):
    source = request.POST if request is not None else {}
    return {
        "user_id": user.user_id,
        "tmpr_pswd_yn": user.tmpr_pswd_yn,
        "name": source.get("name", user.name).strip(),
        "department": source.get("department", user.department or "").strip(),
        "position": source.get("position", user.position or "").strip(),
        "new_password": source.get("new_password", ""),
        "new_password_confirm": source.get("new_password_confirm", ""),
    }


def _pop_temp_password_redirect_url(request):
    next_url = request.session.pop(TEMP_PASSWORD_REDIRECT_SESSION_KEY, "")
    if next_url:
        request.session.modified = True
    return next_url or _get_authenticated_home_url(request.user)


def _update_profile(request, user):
    form_data = _build_profile_form_data(user, request)

    if not form_data["name"]:
        messages.error(request, "이름을 입력해 주세요.")
        return False, form_data

    password_change_requested = bool(form_data["new_password"] or form_data["new_password_confirm"])
    force_password_change = user.tmpr_pswd_yn == YesNoChoices.YES
    if force_password_change and not password_change_requested:
        messages.error(request, "임시 비밀번호 사용자에게는 새 비밀번호 입력이 필요합니다.")
        return False, form_data

    if password_change_requested:
        if not form_data["new_password"]:
            messages.error(request, "새 비밀번호를 입력해 주세요.")
            return False, form_data
        if form_data["new_password"] != form_data["new_password_confirm"]:
            messages.error(request, "새 비밀번호와 비밀번호 확인이 일치하지 않습니다.")
            return False, form_data

    user.name = form_data["name"]
    user.department = form_data["department"] or None
    user.position = form_data["position"] or None
    user.updated_by = user

    password_updated = False
    if password_change_requested:
        user.set_password(form_data["new_password"])
        user.tmpr_pswd_yn = YesNoChoices.NO
        password_updated = True

    user.save()
    if password_updated:
        update_session_auth_hash(request, user)
        messages.success(request, "개인 정보와 비밀번호를 변경했습니다.")
    else:
        messages.success(request, "개인 정보를 수정했습니다.")
    return True, _build_profile_form_data(user)


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
        messages.error(request, "활성 여부 값이 올바르지 않습니다.")
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


@transaction.atomic
def _reset_user_password(request):
    raw_user_sn = request.POST.get("user_sn", "").strip()
    if not raw_user_sn.isdigit():
        messages.error(request, "초기화할 사용자를 찾을 수 없습니다.")
        return

    target_user = User.objects.filter(sn=int(raw_user_sn)).first()
    if target_user is None:
        messages.error(request, "초기화할 사용자를 찾을 수 없습니다.")
        return

    target_user.set_password(TEMP_PASSWORD)
    target_user.tmpr_pswd_yn = YesNoChoices.YES
    target_user.updated_by = request.user
    target_user.save(update_fields=["password", "tmpr_pswd_yn", "updated_by", "updated_at"])

    if target_user.sn == request.user.sn:
        update_session_auth_hash(request, target_user)

    messages.success(request, f"{target_user.name} 계정의 임시 비밀번호를 초기화했습니다.")


@login_required(login_url="home")
def temp_password_notice(request):
    if request.user.tmpr_pswd_yn != YesNoChoices.YES:
        return redirect(_pop_temp_password_redirect_url(request))
    return render(
        request,
        "users/temp_password_notice.html",
        {
            "title": "임시 비밀번호 안내",
            "profile_url": reverse("user_profile"),
        },
    )


@login_required(login_url="home")
def user_profile(request):
    ensure_initial_reference_data()
    profile_form = _build_profile_form_data(request.user)
    force_password_change = request.user.tmpr_pswd_yn == YesNoChoices.YES

    if request.method == "POST":
        updated, profile_form = _update_profile(request, request.user)
        force_password_change = request.user.tmpr_pswd_yn == YesNoChoices.YES
        if updated:
            return redirect(_pop_temp_password_redirect_url(request))

    context = {
        "active_menu": "",
        "title": "개인 정보 수정",
        "profile_form": profile_form,
        "force_password_change": force_password_change,
    }
    return render(request, "users/profile.html", context)


@login_required(login_url="home")
def user_list(request):
    ensure_initial_reference_data()
    admin_redirect = _require_admin(request)
    if admin_redirect is not None:
        return admin_redirect

    create_form = _build_create_form_data()
    open_user_create_modal = False

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_user":
            created, create_form = _create_user(request)
            if created:
                return redirect("user_list")
            open_user_create_modal = True
        elif action == "reset_user_password":
            _reset_user_password(request)
            return redirect("user_list")

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
            {"project": {"name": "AI-DLC Project (예시)"}, "role": {"code": "MANAGER"}},
            {"project": {"name": "Camp Project (예시)"}, "role": {"code": "MEMBER"}},
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
