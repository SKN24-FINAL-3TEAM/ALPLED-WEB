"""
First Project에 사용자 요구사항 정의서(DOC_SRS) 생성 테스트용 입력 파일을 넣는 seed 스크립트입니다.

위치:
    ALPLED-WEB/scripts/seed_first_project_srs_inputs.py

실행 예시(CMD / Anaconda Prompt):
    python -X utf8 manage.py shell -c "exec(open('scripts/seed_first_project_srs_inputs.py', encoding='utf-8').read())"

기존 샘플 입력 파일을 지우고 다시 넣기:
    set "CLEAR_FIRST_SRS_INPUTS=Y" && python -X utf8 manage.py shell -c "exec(open('scripts/seed_first_project_srs_inputs.py', encoding='utf-8').read())"

First Project의 기존 생성 산출물까지 지우고 요구사항 생성 단계부터 테스트하기:
    set "CLEAR_FIRST_SRS_INPUTS=Y" && set "CLEAR_FIRST_GENERATED_DOCS=Y" && python -X utf8 manage.py shell -c "exec(open('scripts/seed_first_project_srs_inputs.py', encoding='utf-8').read())"

로그인 계정:
    USER001 / abc1234
    USER002 / abc1234
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "alpled_web.settings")

try:
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()
except Exception:
    pass

from django.conf import settings
from django.db import transaction

from common.models import Code, YesNoChoices
from common.signals import SEED_CODES, ensure_initial_reference_data
from docs.models import Document, DocumentApproval, DocumentDetail
from docs.services import build_docx_bytes
from files.models import ProjectFile
from files.services import save_project_file_bytes
from projects.models import Project, ProjectUserRole
from users.models import User

PROJECT_NAME = os.getenv("TARGET_PROJECT_NAME", "First Project").strip() or "First Project"
SAMPLE_PASSWORD = "abc1234"
LOCAL_SAMPLE_BUCKET = "alpled-local"
CLEAR_INPUTS = os.getenv("CLEAR_FIRST_SRS_INPUTS", "N").strip().upper() == "Y"
CLEAR_GENERATED_DOCS = os.getenv("CLEAR_FIRST_GENERATED_DOCS", "N").strip().upper() == "Y"

SAMPLE_FILE_NAMES = [
    "FIRST_요구사항_RFP_샘플.docx",
    "FIRST_요구사항_회의록_샘플.docx",
]

RFP_LINES = [
    "1. 사업 개요",
    "본 사업은 프로젝트 산출물 생성 및 승인 관리를 지원하는 AI 기반 SDLC 산출물 작성 서비스를 구축하는 것을 목적으로 한다.",
    "사용자는 프로젝트를 생성하고, RFP 및 회의록 파일을 등록한 뒤 사용자 요구사항 정의서, 화면 설계서, 아키텍처 설계서, ERD, 데이터베이스 설계서, 통합 테스트 시나리오를 순차적으로 생성할 수 있어야 한다.",
    "2. 사용자 및 권한",
    "시스템은 프로젝트 관리자와 프로젝트 멤버 권한을 구분하여야 한다.",
    "프로젝트 관리자는 산출물 승인 요청을 검토하고, 정합성 검증 결과를 확인한 뒤 승인 또는 반려할 수 있어야 한다.",
    "프로젝트 멤버는 산출물을 생성하고 수정 요청을 등록할 수 있어야 한다.",
    "3. 문서 관리",
    "시스템은 RFP 파일과 회의록 파일을 프로젝트별로 등록, 조회, 다운로드, 삭제할 수 있어야 한다.",
    "파일 목록에서는 문서 유형, 파일명, 등록자, 등록일자를 확인할 수 있어야 한다.",
    "4. 사용자 요구사항 정의서 생성",
    "시스템은 선택된 RFP와 회의록을 기반으로 사용자 요구사항 정의서 초안을 생성하여야 한다.",
    "생성 결과는 산출물 목록에서 확인할 수 있어야 하며, 사용자는 OnlyOffice 기반 편집 화면에서 내용을 수정할 수 있어야 한다.",
    "5. 산출물 승인 및 버전 관리",
    "시스템은 산출물 승인 요청 목록을 제공하고, 승인 완료된 산출물은 산출물 버전이력에 등록하여야 한다.",
    "버전이력 화면에서는 산출물명, 버전, 확정자, 확정 일시, 수정 내용, 상태를 확인하고 미리보기 또는 다운로드할 수 있어야 한다.",
]

MEETING_LINES = [
    "회의명: FIRST 프로젝트 요구사항 검토 회의",
    "일시: 2026-06-22 10:00",
    "참석자: 프로젝트 관리자, 요구사항 담당자, 개발 담당자",
    "1. 산출물 생성 흐름은 사용자 요구사항 정의서 → 화면 설계서 → 아키텍처 설계서 → ERD → 데이터베이스 설계서 → 통합 테스트 시나리오 순서로 진행한다.",
    "2. 사용자 요구사항 정의서 생성 단계에서는 RFP와 회의록을 입력으로 사용한다.",
    "3. 화면 설계서 생성 단계에서는 UI 이미지 또는 와이어프레임 이미지를 입력받는다.",
    "4. 아키텍처 설계서 생성 단계에서는 시스템 구성요소 정보를 입력받는다.",
    "5. 산출물 버전이력은 프로젝트 관리자가 산출물을 승인하여 버전을 확정한 경우에만 목록에 표시한다.",
    "6. 산출물 생성 화면의 진행 상태는 생성 대기, 생성 완료, 이전 단계 대기로 구분하되 줄바꿈 없이 표시한다.",
    "7. 승인요청 화면에서는 정합성 자동검토, 승인, 반려 흐름을 제공한다.",
]


def _ensure_bucket_for_local_storage():
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
            tmpr_pswd_yn=YesNoChoices.NO,
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


def _upsert_user(user_id, name, department, position, *, admin, is_manager=False):
    user = User.objects.filter(user_id=user_id).first()
    if user is None:
        user = User.objects.create_user(
            user_id=user_id,
            password=SAMPLE_PASSWORD,
            name=name,
            department=department,
            position=position,
            sys_mngr_yn=YesNoChoices.YES if is_manager else YesNoChoices.NO,
            tmpr_pswd_yn=YesNoChoices.NO,
            use_yn=YesNoChoices.YES,
            created_by=admin,
            updated_by=admin,
        )
    else:
        user.name = name
        user.department = department
        user.position = position
        user.sys_mngr_yn = YesNoChoices.YES if is_manager else YesNoChoices.NO
        user.tmpr_pswd_yn = YesNoChoices.NO
        user.use_yn = YesNoChoices.YES
        user.created_by = user.created_by or admin
        user.updated_by = admin
        user.set_password(SAMPLE_PASSWORD)
        user.save()
    return user


def _get_or_create_first_project(manager):
    project = Project.objects.filter(name=PROJECT_NAME).first()
    if project is None:
        project = Project.objects.create(
            name=PROJECT_NAME,
            is_deleted=YesNoChoices.NO,
            created_by=manager,
            updated_by=manager,
        )
    else:
        project.is_deleted = YesNoChoices.NO
        project.updated_by = manager
        project.save(update_fields=["is_deleted", "updated_by"])
    return project


def _ensure_project_role(project, user, role_id, actor):
    ProjectUserRole.objects.update_or_create(
        project=project,
        user=user,
        defaults={
            "role_id": role_id,
            "created_by": actor,
            "updated_by": actor,
        },
    )


def _clear_existing_inputs(project):
    if not CLEAR_INPUTS:
        return 0
    queryset = ProjectFile.objects.filter(project=project, name__in=SAMPLE_FILE_NAMES)
    count = queryset.count()
    queryset.delete()
    return count


def _clear_generated_documents(project):
    if not CLEAR_GENERATED_DOCS:
        return {"documents": 0, "details": 0, "approvals": 0}
    approvals = DocumentApproval.objects.filter(detail__document__project=project).count()
    details = DocumentDetail.objects.filter(document__project=project).count()
    documents = Document.objects.filter(project=project).count()
    DocumentApproval.objects.filter(detail__document__project=project).delete()
    DocumentDetail.objects.filter(document__project=project).delete()
    Document.objects.filter(project=project).delete()
    return {"documents": documents, "details": details, "approvals": approvals}


def _create_sample_project_file(project, actor, *, file_type_id, filename, title, lines):
    content_bytes = build_docx_bytes(title, lines)
    storage_path = save_project_file_bytes(project, filename, content_bytes)
    return ProjectFile.objects.create(
        project=project,
        file_type_id=file_type_id,
        name=filename,
        path=storage_path,
        size=len(content_bytes),
        extension="docx",
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def run():
    _ensure_bucket_for_local_storage()
    admin = _ensure_reference_data()
    manager = _upsert_user(
        "USER001",
        "프로젝트 관리자",
        "PMO",
        "팀장",
        admin=admin,
        is_manager=True,
    )
    member = _upsert_user(
        "USER002",
        "프로젝트 멤버",
        "개발팀",
        "담당자",
        admin=admin,
        is_manager=False,
    )
    project = _get_or_create_first_project(manager)
    _ensure_project_role(project, manager, "ROLE_MANAGER", manager)
    _ensure_project_role(project, member, "ROLE_MEMBER", manager)

    removed_inputs = _clear_existing_inputs(project)
    removed_docs = _clear_generated_documents(project)

    rfp_file = _create_sample_project_file(
        project,
        manager,
        file_type_id="FILE_RFP",
        filename=SAMPLE_FILE_NAMES[0],
        title="FIRST 프로젝트 RFP 샘플",
        lines=RFP_LINES,
    )
    meeting_file = _create_sample_project_file(
        project,
        manager,
        file_type_id="FILE_MEETING",
        filename=SAMPLE_FILE_NAMES[1],
        title="FIRST 프로젝트 회의록 샘플",
        lines=MEETING_LINES,
    )

    print("FIRST 프로젝트 요구사항 생성 입력 샘플 등록 완료")
    print(f"프로젝트: {project.name} / project_sn={project.sn}")
    print(f"RFP file_sn={rfp_file.sn} / {rfp_file.name}")
    print(f"회의록 file_sn={meeting_file.sn} / {meeting_file.name}")
    print(f"기존 샘플 입력 삭제 수: {removed_inputs}")
    if CLEAR_GENERATED_DOCS:
        print(
            "기존 생성 산출물 삭제 수: "
            f"documents={removed_docs['documents']}, details={removed_docs['details']}, approvals={removed_docs['approvals']}"
        )
    else:
        print("기존 생성 산출물은 삭제하지 않았습니다. 요구사항 단계부터 보려면 CLEAR_FIRST_GENERATED_DOCS=Y로 실행하세요.")
    print("로그인: USER001 / abc1234")
    print("확인 URL: /docs/generate/?docs_cd=DOC_SRS&resume=1")


run()
