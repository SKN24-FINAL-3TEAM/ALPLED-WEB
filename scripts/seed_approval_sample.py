"""
산출물 승인요청 화면 테스트용 샘플 데이터 생성 스크립트.

실행:
    python manage.py migrate --run-syncdb
    python manage.py shell < scripts/seed_approval_sample.py

생성되는 계정:
    USER001 / abc1234  (프로젝트 관리자)
    USER002 / abc1234  (프로젝트 멤버, 승인 요청자)
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "alpled_web.settings")

try:
    import django
    from django.apps import apps
    if not apps.ready:
        django.setup()
except Exception:
    # manage.py shell 로 실행하는 경우 이미 초기화되어 있을 수 있습니다.
    pass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.models import Code, YesNoChoices
from common.signals import SEED_CODES, ensure_initial_reference_data
from common.storage import save_bytes
from docs.models import Document, DocumentApproval, DocumentDetail
from docs.services import (
    build_docx_bytes,
    build_document_detail_path,
    build_document_detail_storage_key,
)
from files.models import ProjectFile
from projects.models import Project, ProjectNet, ProjectUserRole
from users.models import User

SAMPLE_PROJECT_NAME = "First Project"
SAMPLE_PASSWORD = "abc1234"
LOCAL_SAMPLE_BUCKET = "alpled-local"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _ensure_bucket_for_local_storage():
    """로컬 파일 저장 모드여도 docs_path는 s3:// 형태라 bucket 값이 필요합니다."""
    if not getattr(settings, "AWS_STORAGE_BUCKET_NAME", ""):
        settings.AWS_STORAGE_BUCKET_NAME = LOCAL_SAMPLE_BUCKET


def _ensure_reference_data():
    ensure_initial_reference_data()
    admin = User.objects.filter(user_id="admin").first()
    if admin is None:
        admin = User.objects.create_user(
            user_id="admin",
            password=SAMPLE_PASSWORD,
            name="관리자",
            department="시스템",
            position="관리자",
            sys_mngr_yn=YesNoChoices.YES,
            use_yn=YesNoChoices.YES,
        )
        admin.created_by = admin
        admin.updated_by = admin
        admin.save(update_fields=["created_by", "updated_by"])

    for code, name, remarks in SEED_CODES:
        Code.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "remarks": remarks,
                "created_by": admin,
                "updated_by": admin,
            },
        )
    return admin


def _upsert_user(user_id, name, department, position, *, is_manager=False, admin):
    user = User.objects.filter(user_id=user_id).first()
    if user is None:
        user = User.objects.create_user(
            user_id=user_id,
            password=SAMPLE_PASSWORD,
            name=name,
            department=department,
            position=position,
            sys_mngr_yn=YesNoChoices.NO,
            tmpr_pswd_yn=YesNoChoices.NO,
            use_yn=YesNoChoices.YES,
            created_by=admin,
            updated_by=admin,
        )
    else:
        user.name = name
        user.department = department
        user.position = position
        user.sys_mngr_yn = YesNoChoices.NO
        user.tmpr_pswd_yn = YesNoChoices.NO
        user.use_yn = YesNoChoices.YES
        user.created_by = user.created_by or admin
        user.updated_by = admin
        user.set_password(SAMPLE_PASSWORD)
        user.save()
    return user


def _clear_existing_sample_project():
    for project in Project.objects.filter(name=SAMPLE_PROJECT_NAME):
        DocumentApproval.objects.filter(detail__document__project=project).delete()
        DocumentDetail.objects.filter(document__project=project).delete()
        Document.objects.filter(project=project).delete()
        ProjectFile.objects.filter(project=project).delete()
        ProjectNet.objects.filter(project=project).delete()
        ProjectUserRole.objects.filter(project=project).delete()
        project.delete()


def _create_detail(document, actor, title, lines):
    detail = DocumentDetail.objects.create(
        document=document,
        path="",
        is_deleted=YesNoChoices.NO,
        created_by=actor,
    )
    content_bytes = build_docx_bytes(title, lines)
    key = build_document_detail_storage_key(document.project, document.sn, detail.sn)
    save_bytes(key, content_bytes, content_type=DOCX_CONTENT_TYPE)
    detail.path = build_document_detail_path(document.project, document.sn, detail.sn)
    detail.save(update_fields=["path"])
    return detail


def _create_document_with_two_revisions(project, requester, doc_code, version, modification_content, before_lines, after_lines):
    doc_type = Code.objects.get(code=doc_code)
    document = Document.objects.create(
        project=project,
        possession_user=None,
        document_type=doc_type,
        progress_status_id="PRGRS_COMPLETED",
        version=version,
        modification_content=modification_content,
        created_by=requester,
        updated_by=requester,
    )
    before_detail = _create_detail(document, requester, doc_type.name, before_lines)
    after_detail = _create_detail(document, requester, doc_type.name, after_lines)
    return document, before_detail, after_detail


def _create_approval(detail, requester, status_code, request_content, rejection_reason=None, updated_by=None, minutes_offset=0):
    approval = DocumentApproval.objects.create(
        detail=detail,
        approval_status_id=status_code,
        request_content=request_content,
        rejection_reason=rejection_reason,
        created_by=requester,
        updated_by=updated_by or requester,
    )
    # 목록 정렬 확인용 시간 보정
    dt = timezone.now() + timezone.timedelta(minutes=minutes_offset)
    DocumentApproval.objects.filter(approval_sn=approval.approval_sn).update(created_at=dt, updated_at=dt)
    return approval


@transaction.atomic
def run():
    _ensure_bucket_for_local_storage()
    admin = _ensure_reference_data()
    manager = _upsert_user("USER001", "프로젝트 관리자", "PMO", "팀장", is_manager=True, admin=admin)
    member = _upsert_user("USER002", "요청자", "개발팀", "팀원", admin=admin)

    _clear_existing_sample_project()

    project = Project.objects.create(
        name=SAMPLE_PROJECT_NAME,
        is_deleted=YesNoChoices.NO,
        created_by=manager,
        updated_by=manager,
    )

    ProjectUserRole.objects.create(
        project=project,
        user=manager,
        role_id="ROLE_MANAGER",
        created_by=manager,
        updated_by=manager,
    )
    ProjectUserRole.objects.create(
        project=project,
        user=member,
        role_id="ROLE_MEMBER",
        created_by=manager,
        updated_by=manager,
    )

    ProjectNet.objects.create(
        project=project,
        name="내부 업무망",
        purpose="AI 산출물 생성 및 승인 검토를 위한 내부 업무망",
        middleware_stack="Django, FastAPI, MySQL, S3, OnlyOffice",
        firewall_settings="관리자망 HTTPS 허용, 내부 API 제한",
        auth_method="세션 로그인, 프로젝트 역할 기반 권한",
        expected_concurrent_users=50,
        cloud_yn=YesNoChoices.YES,
        hardware_spec="2vCPU/4GB, RDS MySQL, S3 호환 스토리지",
        remarks="아키텍처 설계서 샘플 입력",
        created_by=manager,
        updated_by=manager,
    )

    # 1) 대기: 사용자 인터페이스 설계서
    _, _, ui_after = _create_document_with_two_revisions(
        project,
        member,
        "DOC_ITF",
        "1.1",
        "1, 2행 오타 수정",
        [
            "Welcome to ONLYOFFICE Online Editor 화면을 기준으로 UI를 구성한다.",
            "문서 비교 영역은 이전 버전과 수정본을 나란히 표시한다.",
            "승인 요청자는 수정 사유를 입력할 수 있어야 한다.",
        ],
        [
            "Welcome to ONLYOFFICE Online Editor 화면을 기준으로 UI를 구성한다.",
            "문서 비교 영역은 이전 버전과 수정본을 나란히 표시한다.",
            "승인 요청자는 수정 사유를 입력할 수 있어야 한다.",
            "1, 2행 오타를 수정했습니다.",
        ],
    )
    _create_approval(
        ui_after,
        member,
        "APRV_REQ",
        "1, 2행 오타수정했습니다.",
        minutes_offset=3,
    )

    # 2) 승인 완료: 아키텍처 설계서
    _, _, arch_approved_after = _create_document_with_two_revisions(
        project,
        member,
        "DOC_ARCH",
        "1.1",
        "S3 저장소 반영",
        [
            "웹 애플리케이션은 Django로 구성한다.",
            "AI Agent는 FastAPI로 구성한다.",
            "문서 파일은 스토리지에 저장한다.",
        ],
        [
            "웹 애플리케이션은 Django로 구성한다.",
            "AI Agent는 FastAPI로 구성한다.",
            "문서 파일과 산출물은 S3 호환 스토리지에 저장한다.",
            "Qdrant 벡터 저장소는 내부 검증 계층에 배치한다.",
        ],
    )
    _create_approval(
        arch_approved_after,
        member,
        "APRV_COM",
        "S3 저장소 구성을 반영했습니다.",
        updated_by=manager,
        minutes_offset=2,
    )

    # 3) 반려: 아키텍처 설계서
    _, _, arch_rejected_after = _create_document_with_two_revisions(
        project,
        member,
        "DOC_ARCH",
        "1.2",
        "보안 계층 설명 수정",
        [
            "사용자 요청은 웹 UI를 통해 Django 애플리케이션으로 전달된다.",
            "Django는 AI Agent API를 호출한다.",
        ],
        [
            "사용자 요청은 웹 UI를 통해 Django 애플리케이션으로 전달된다.",
            "Django는 AI Agent API를 호출한다.",
            "보안 계층은 별도 영역으로 표시한다.",
        ],
    )
    _create_approval(
        arch_rejected_after,
        member,
        "APRV_RJT",
        "보안 계층 설명을 수정했습니다.",
        rejection_reason="수정 근거가 부족합니다.",
        updated_by=manager,
        minutes_offset=1,
    )

    print("샘플 데이터 생성 완료")
    print(f"프로젝트: {project.name} (sn={project.sn})")
    print(f"관리자 로그인: USER001 / {SAMPLE_PASSWORD}")
    print(f"요청자 로그인: USER002 / {SAMPLE_PASSWORD}")
    print("확인 URL: /docs/approvals/")


run()
