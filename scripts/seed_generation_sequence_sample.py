"""
산출물 생성 흐름을 순차적으로 테스트하기 위한 샘플 데이터 생성 스크립트.

실행 전:
    python manage.py migrate --run-syncdb

실행 예시(CMD/Git Bash):
    set GEN_SAMPLE_STEP=srs
    python -X utf8 manage.py shell -c "exec(open('scripts/seed_generation_sequence_sample.py', encoding='utf-8').read())"

PowerShell:
    $env:GEN_SAMPLE_STEP="arch_input"
    python -X utf8 manage.py shell -c 'exec(open("scripts/seed_generation_sequence_sample.py", encoding="utf-8").read())'

GEN_SAMPLE_STEP 값:
    srs        : RFP/회의록만 넣고 사용자 요구사항 정의서 단계부터 테스트
    itf        : 사용자 요구사항 정의서 확정본까지 넣고 사용자 인터페이스 설계서 단계부터 테스트
    arch_input : 사용자 요구사항 정의서 + 사용자 인터페이스 설계서 확정본까지 넣고 아키텍처 구성요소 입력 단계 테스트
    arch_ready : arch_input 상태에 샘플 아키텍처 구성요소까지 넣고 아키텍처 생성 버튼 테스트

로그인 계정:
    USER001 / abc1234  (프로젝트 관리자)
    USER002 / abc1234  (프로젝트 멤버)
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
from common.storage import build_s3_uri, save_bytes
from docs.models import Document, DocumentApproval, DocumentDetail
from docs.services import (
    build_docx_bytes,
    build_document_detail_path,
    build_document_detail_storage_key,
)
from files.models import ProjectFile
from projects.models import Project, ProjectNet, ProjectUserRole
from users.models import User

SAMPLE_PROJECT_NAME = "SEQ 산출물 생성 샘플"
SAMPLE_PASSWORD = "abc1234"
LOCAL_SAMPLE_BUCKET = "alpled-local"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"
PNG_CONTENT_TYPE = "image/png"

STEP_ORDER = {
    "srs": 1,
    "itf": 2,
    "arch_input": 3,
    "arch_ready": 4,
}

SAMPLE_STEP = os.getenv("GEN_SAMPLE_STEP", "arch_input").strip().lower()
if SAMPLE_STEP not in STEP_ORDER:
    raise ValueError("GEN_SAMPLE_STEP은 srs, itf, arch_input, arch_ready 중 하나여야 합니다.")


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


def _clear_existing_sample_project():
    for project in Project.objects.filter(name=SAMPLE_PROJECT_NAME):
        DocumentApproval.objects.filter(detail__document__project=project).delete()
        DocumentDetail.objects.filter(document__project=project).delete()
        Document.objects.filter(project=project).delete()
        ProjectFile.objects.filter(project=project).delete()
        ProjectNet.objects.filter(project=project).delete()
        ProjectUserRole.objects.filter(project=project).delete()
        project.delete()


def _create_project(manager, member):
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
    return project


def _save_project_file(project, actor, file_code, filename, content_text):
    key = f"sample/project-files/{project.sn}/{filename}"
    payload = content_text.encode("utf-8")
    save_bytes(key, payload, content_type=TEXT_CONTENT_TYPE)
    return ProjectFile.objects.create(
        project=project,
        file_type_id=file_code,
        name=filename,
        path=build_s3_uri(key),
        size=len(payload),
        extension=filename.rsplit(".", 1)[-1].lower(),
        created_by=actor,
        updated_by=actor,
    )


def _create_sample_input_files(project, actor):
    _save_project_file(
        project,
        actor,
        "FILE_RFP",
        "SEQ_RFP_샘플.txt",
        """
AI 기반 SDLC 산출물 자동 생성 서비스를 구축한다.
사용자는 프로젝트를 생성하고 RFP 및 회의록을 업로드할 수 있어야 한다.
시스템은 사용자 요구사항 정의서, 사용자 인터페이스 설계서, 아키텍처 설계서를 순차적으로 생성하여야 한다.
프로젝트 관리자는 산출물 수정본을 검토하고 승인 또는 반려할 수 있어야 한다.
""".strip(),
    )
    _save_project_file(
        project,
        actor,
        "FILE_MEETING",
        "SEQ_회의록_샘플.txt",
        """
회의 결과, 산출물 생성은 요구사항 정의서 → 인터페이스 설계서 → 아키텍처 설계서 순서로 진행한다.
아키텍처 설계서 생성 전에는 웹 UI, Django 애플리케이션, FastAPI Agent, MySQL, S3, Qdrant 구성요소를 입력한다.
아키텍처 구성요소 입력은 산출물 생성 화면에서 처리한다.
""".strip(),
    )


def _create_document(project, actor, document_code, version, title, lines):
    document = Document.objects.create(
        project=project,
        possession_user=None,
        document_type_id=document_code,
        progress_status_id="PRGRS_COMPLETED",
        version=version,
        modification_content="순차 샘플 확정본",
        created_by=actor,
        updated_by=actor,
    )
    detail = DocumentDetail.objects.create(
        document=document,
        path="",
        is_deleted=YesNoChoices.NO,
        created_by=actor,
    )
    content_bytes = build_docx_bytes(title, lines)
    key = build_document_detail_storage_key(project, document.sn, detail.sn)
    save_bytes(key, content_bytes, content_type=DOCX_CONTENT_TYPE)
    detail.path = build_document_detail_path(project, document.sn, detail.sn)
    detail.save(update_fields=["path"])
    return document


def _create_confirmed_srs(project, actor):
    return _create_document(
        project,
        actor,
        "DOC_SRS",
        "1",
        "사용자 요구사항 정의서",
        [
            "SEQ 산출물 생성 샘플 프로젝트의 사용자 요구사항 정의서 확정본입니다.",
            "REQ-001 프로젝트 관리자는 산출물 생성을 순차적으로 진행할 수 있어야 한다.",
            "REQ-002 사용자는 산출물 생성 단계별 입력 자료를 등록할 수 있어야 한다.",
            "REQ-003 아키텍처 설계서 생성 전 시스템 구성요소를 입력할 수 있어야 한다.",
        ],
    )


def _create_confirmed_itf(project, actor):
    return _create_document(
        project,
        actor,
        "DOC_ITF",
        "1",
        "사용자 인터페이스 설계서",
        [
            "SEQ 산출물 생성 샘플 프로젝트의 사용자 인터페이스 설계서 확정본입니다.",
            "화면: 산출물 생성",
            "영역: 생성 진행 현황, 입력 자료 등록, 산출물 생성 버튼",
            "아키텍처 단계에서는 구성요소 입력 폼과 등록 목록을 표시한다.",
        ],
    )


def _create_architecture_components(project, actor):
    rows = [
        {
            "name": "웹 UI",
            "purpose": "프로젝트 생성, 문서 업로드, 산출물 생성 요청, 승인요청 조회",
            "middleware_stack": "HTML, Tailwind CSS, JavaScript",
            "firewall_settings": "HTTPS 443 허용, 관리자/사용자 세션 접근",
            "auth_method": "Django Session",
            "expected_concurrent_users": 50,
            "cloud_yn": YesNoChoices.YES,
            "hardware_spec": "정적 리소스 및 템플릿 렌더링",
            "remarks": "사용자 접점 계층",
        },
        {
            "name": "Django 웹 애플리케이션",
            "purpose": "사용자 요청 처리, 프로젝트/문서/승인 상태 관리",
            "middleware_stack": "Django, ORM, MySQL Client",
            "firewall_settings": "내부 DB 3306, FastAPI 8000 접근 허용",
            "auth_method": "세션 로그인, 프로젝트 역할 기반 권한",
            "expected_concurrent_users": 50,
            "cloud_yn": YesNoChoices.YES,
            "hardware_spec": "2vCPU / 4GB RAM",
            "remarks": "업무 처리 계층",
        },
        {
            "name": "AI Agent 서버",
            "purpose": "SDLC 산출물 생성 오케스트레이션 및 LLM 호출",
            "middleware_stack": "FastAPI, LangGraph, Python, OpenAI Compatible Client",
            "firewall_settings": "Django 서버에서만 API 호출 허용",
            "auth_method": "API Key 또는 서비스 계정",
            "expected_concurrent_users": 20,
            "cloud_yn": YesNoChoices.YES,
            "hardware_spec": "GPU 연계 가능, 4vCPU / 16GB RAM",
            "remarks": "산출물 생성 계층",
        },
        {
            "name": "데이터/스토리지 계층",
            "purpose": "메타데이터, 문서 파일, 벡터 검색 데이터 저장",
            "middleware_stack": "MySQL, S3 Compatible Storage, Qdrant",
            "firewall_settings": "애플리케이션 서버 내부 접근만 허용",
            "auth_method": "DB 계정, S3 Access Key, Qdrant API Key",
            "expected_concurrent_users": 50,
            "cloud_yn": YesNoChoices.YES,
            "hardware_spec": "RDS MySQL, Object Storage, Vector DB",
            "remarks": "영속성 계층",
        },
    ]
    for row in rows:
        ProjectNet.objects.create(project=project, created_by=actor, updated_by=actor, **row)


@transaction.atomic
def run():
    _ensure_bucket_for_local_storage()
    admin = _ensure_reference_data()
    manager = _upsert_user("USER001", "프로젝트 관리자", "PMO", "팀장", admin=admin, is_manager=True)
    member = _upsert_user("USER002", "프로젝트 멤버", "개발팀", "팀원", admin=admin)

    _clear_existing_sample_project()
    project = _create_project(manager, member)
    _create_sample_input_files(project, manager)

    if STEP_ORDER[SAMPLE_STEP] >= STEP_ORDER["itf"]:
        _create_confirmed_srs(project, manager)
    if STEP_ORDER[SAMPLE_STEP] >= STEP_ORDER["arch_input"]:
        _create_confirmed_itf(project, manager)
    if SAMPLE_STEP == "arch_ready":
        _create_architecture_components(project, manager)

    next_urls = {
        "srs": "/docs/generate/?docs_cd=DOC_SRS&resume=1",
        "itf": "/docs/generate/?docs_cd=DOC_ITF&resume=1",
        "arch_input": "/docs/generate/?docs_cd=DOC_ARCH&resume=1&arch_form=1",
        "arch_ready": "/docs/generate/?docs_cd=DOC_ARCH&resume=1",
    }

    print("순차 산출물 생성 샘플 데이터 생성 완료")
    print(f"단계: {SAMPLE_STEP}")
    print(f"프로젝트: {project.name} (sn={project.sn})")
    print(f"관리자 로그인: USER001 / {SAMPLE_PASSWORD}")
    print(f"멤버 로그인: USER002 / {SAMPLE_PASSWORD}")
    print(f"확인 URL: {next_urls[SAMPLE_STEP]}")
    print("브라우저에서 현재 프로젝트를 'SEQ 산출물 생성 샘플'로 선택한 뒤 확인하세요.")


run()
