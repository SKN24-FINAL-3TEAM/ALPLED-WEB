"""
First Project에서 산출물 생성 완료 상태를 단계별로 가정하고 다음 단계 화면을 테스트하는 seed 스크립트입니다.

위치:
    ALPLED-WEB/scripts/seed_first_project_generation_sequence.py

CMD / Anaconda Prompt 예시:
    set "FIRST_GEN_STEP=srs_done" && python -X utf8 manage.py shell -c "exec(open('scripts/seed_first_project_generation_sequence.py', encoding='utf-8').read())"

PowerShell 예시:
    $env:FIRST_GEN_STEP="srs_done"; python -X utf8 manage.py shell -c 'exec(open("scripts/seed_first_project_generation_sequence.py", encoding="utf-8").read())'

FIRST_GEN_STEP 값:
    srs_wait   : RFP/회의록만 넣고 사용자 요구사항 정의서 생성 단계 테스트
    srs_done   : 사용자 요구사항 정의서 생성 완료 → 화면 설계서 입력 단계 테스트
    itf_done   : 화면 설계서 생성 완료 → 아키텍처 구성요소 입력 단계 테스트
    arch_ready : itf_done 상태 + 아키텍처 구성요소 샘플 등록 → 아키텍처 생성 버튼 테스트
    arch_done  : 아키텍처 설계서 생성 완료 → 엔티티관계모형(ERD) 생성 단계 테스트
    erd_done   : ERD 생성 완료 → 데이터베이스 설계서 생성 단계 테스트
    db_done    : 데이터베이스 설계서 생성 완료 → 통합 테스트 시나리오 생성 단계 테스트
    all_done   : 통합 테스트 시나리오까지 전체 산출물 생성 완료 상태 테스트

기본 동작:
    - First Project는 삭제하지 않습니다.
    - First Project의 기존 산출물(Document/Detail/Approval)은 지우고, 선택한 단계까지만 완료본을 다시 만듭니다.
    - RFP/회의록 샘플 입력 파일은 없으면 만들고, 같은 이름이 있으면 다시 만들지 않습니다.

선택 옵션:
    set "TARGET_PROJECT_NAME=First Project"
    set "RESET_FIRST_GENERATED_DOCS=N"  # 기존 산출물을 지우지 않고 추가만 하고 싶을 때
    set "RESET_FIRST_PROJECT_NETS=N"    # 기존 아키텍처 구성요소를 지우지 않고 유지하고 싶을 때

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
from common.storage import save_bytes
from docs.models import Document, DocumentApproval, DocumentDetail
from docs.services import (
    build_docx_bytes,
    build_document_detail_path,
    build_document_detail_storage_key,
)
from files.models import ProjectFile
from files.services import save_project_file_bytes
from projects.models import Project, ProjectNet, ProjectUserRole
from users.models import User

PROJECT_NAME = os.getenv("TARGET_PROJECT_NAME", "First Project").strip() or "First Project"
SAMPLE_PASSWORD = "abc1234"
LOCAL_SAMPLE_BUCKET = "alpled-local"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

RESET_GENERATED_DOCS = os.getenv("RESET_FIRST_GENERATED_DOCS", "Y").strip().upper() != "N"
RESET_PROJECT_NETS = os.getenv("RESET_FIRST_PROJECT_NETS", "Y").strip().upper() != "N"

STEP_ORDER = {
    "srs_wait": 0,
    "srs_done": 1,
    "itf_done": 2,
    "arch_ready": 2,
    "arch_done": 3,
    "erd_done": 4,
    "db_done": 5,
    "all_done": 6,
}

STEP_ALIAS = {
    "srs": "srs_wait",
    "itf": "srs_done",
    "arch_input": "itf_done",
}

raw_step = os.getenv("FIRST_GEN_STEP", os.getenv("GEN_SAMPLE_STEP", "srs_done")).strip().lower()
SAMPLE_STEP = STEP_ALIAS.get(raw_step, raw_step)
if SAMPLE_STEP not in STEP_ORDER:
    raise ValueError(
        "FIRST_GEN_STEP은 srs_wait, srs_done, itf_done, arch_ready, "
        "arch_done, erd_done, db_done, all_done 중 하나여야 합니다."
    )

SAMPLE_INPUT_FILES = {
    "FIRST_요구사항_RFP_샘플.docx": {
        "file_type_id": "FILE_RFP",
        "title": "FIRST 프로젝트 RFP 샘플",
        "lines": [
            "1. 사업 개요",
            "본 사업은 프로젝트 산출물 생성 및 승인 관리를 지원하는 AI 기반 SDLC 산출물 작성 서비스를 구축하는 것을 목적으로 한다.",
            "사용자는 프로젝트를 생성하고 RFP 및 회의록 파일을 등록한 뒤 사용자 요구사항 정의서, 화면 설계서, 아키텍처 설계서, ERD, 데이터베이스 설계서, 통합 테스트 시나리오를 순차적으로 생성할 수 있어야 한다.",
            "2. 사용자 및 권한",
            "프로젝트 관리자는 산출물 승인 요청을 검토하고, 정합성 검증 결과를 확인한 뒤 승인 또는 반려할 수 있어야 한다.",
            "프로젝트 멤버는 산출물을 생성하고 수정 요청을 등록할 수 있어야 한다.",
            "3. 산출물 버전 관리",
            "승인 완료된 산출물은 산출물 버전이력에 등록하여야 하며, 사용자는 확정본을 미리보기하거나 다운로드할 수 있어야 한다.",
        ],
    },
    "FIRST_요구사항_회의록_샘플.docx": {
        "file_type_id": "FILE_MEETING",
        "title": "FIRST 프로젝트 회의록 샘플",
        "lines": [
            "회의명: FIRST 프로젝트 요구사항 검토 회의",
            "1. 산출물 생성 흐름은 사용자 요구사항 정의서 → 화면 설계서 → 아키텍처 설계서 → ERD → 데이터베이스 설계서 → 통합 테스트 시나리오 순서로 진행한다.",
            "2. 사용자 요구사항 정의서 생성 단계에서는 RFP와 회의록을 입력으로 사용한다.",
            "3. 화면 설계서 생성 단계에서는 UI 이미지 또는 와이어프레임 이미지를 입력받는다.",
            "4. 아키텍처 설계서 생성 단계에서는 웹, 애플리케이션, AI Agent, DB, 스토리지 구성요소 정보를 입력받는다.",
            "5. ERD 이후 산출물은 이전 생성 완료 산출물을 기준으로 이어서 생성한다.",
        ],
    },
}


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


def _get_or_create_project(manager):
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


def _create_or_keep_input_file(project, actor, filename, spec):
    existing = ProjectFile.objects.filter(project=project, name=filename).first()
    if existing:
        return existing, False
    content_bytes = build_docx_bytes(spec["title"], spec["lines"])
    storage_path = save_project_file_bytes(project, filename, content_bytes)
    return (
        ProjectFile.objects.create(
            project=project,
            file_type_id=spec["file_type_id"],
            name=filename,
            path=storage_path,
            size=len(content_bytes),
            extension="docx",
            created_by=actor,
            updated_by=actor,
        ),
        True,
    )


def _ensure_input_files(project, actor):
    result = []
    for filename, spec in SAMPLE_INPUT_FILES.items():
        project_file, created = _create_or_keep_input_file(project, actor, filename, spec)
        result.append((project_file, created))
    return result


def _clear_generated_documents(project):
    if not RESET_GENERATED_DOCS:
        return {"documents": 0, "details": 0, "approvals": 0}
    approvals = DocumentApproval.objects.filter(detail__document__project=project).count()
    details = DocumentDetail.objects.filter(document__project=project).count()
    documents = Document.objects.filter(project=project).count()
    DocumentApproval.objects.filter(detail__document__project=project).delete()
    DocumentDetail.objects.filter(document__project=project).delete()
    Document.objects.filter(project=project).delete()
    return {"documents": documents, "details": details, "approvals": approvals}


def _clear_project_nets(project):
    if not RESET_PROJECT_NETS:
        return 0
    count = ProjectNet.objects.filter(project=project).count()
    ProjectNet.objects.filter(project=project).delete()
    return count


def _create_document(project, actor, document_code, version, title, lines, modification_content):
    document = Document.objects.create(
        project=project,
        possession_user=None,
        document_type_id=document_code,
        progress_status_id="PRGRS_COMPLETED",
        version=version,
        modification_content=modification_content,
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
        "1.0",
        "사용자 요구사항 정의서",
        [
            "FIRST 프로젝트의 사용자 요구사항 정의서 생성 완료본입니다.",
            "REQ-001 사용자는 프로젝트별 RFP 및 회의록을 등록할 수 있어야 한다.",
            "REQ-002 시스템은 등록된 입력 파일을 기반으로 사용자 요구사항 정의서를 생성하여야 한다.",
            "REQ-003 프로젝트 관리자는 생성된 산출물을 승인 또는 반려할 수 있어야 한다.",
        ],
        "요구사항 생성 완료 샘플",
    )


def _create_confirmed_itf(project, actor):
    return _create_document(
        project,
        actor,
        "DOC_ITF",
        "1.0",
        "화면 설계서",
        [
            "FIRST 프로젝트의 화면 설계서 생성 완료본입니다.",
            "화면: 산출물 생성 화면",
            "구성: 생성 진행 현황, 입력 자료 등록 영역, 산출물 생성 버튼, 산출물 미리보기/다운로드 버튼",
            "화면 설계서 단계에서는 UI 이미지 또는 와이어프레임 이미지를 업로드하여 입력으로 사용한다.",
        ],
        "화면 설계서 생성 완료 샘플",
    )


def _create_architecture_components(project, actor):
    rows = [
        {
            "name": "웹 UI",
            "purpose": "프로젝트 생성, 파일 업로드, 산출물 생성 요청, 산출물 버전이력 조회",
            "middleware_stack": "HTML, Tailwind CSS, JavaScript",
            "firewall_settings": "HTTPS 443 허용",
            "auth_method": "Django Session",
            "expected_concurrent_users": 50,
            "cloud_yn": YesNoChoices.YES,
            "hardware_spec": "정적 리소스 및 템플릿 렌더링",
            "remarks": "사용자 접점 계층",
        },
        {
            "name": "Django 웹 애플리케이션",
            "purpose": "사용자 요청 처리, 프로젝트/파일/산출물/승인 상태 관리",
            "middleware_stack": "Django, ORM, MySQL Client",
            "firewall_settings": "MySQL 3306, FastAPI 8000 내부 접근 허용",
            "auth_method": "세션 로그인, 프로젝트 역할 기반 권한",
            "expected_concurrent_users": 50,
            "cloud_yn": YesNoChoices.YES,
            "hardware_spec": "2vCPU / 4GB RAM",
            "remarks": "업무 처리 계층",
        },
        {
            "name": "AI Agent 서버",
            "purpose": "SDLC 산출물 생성 오케스트레이션 및 LLM 호출",
            "middleware_stack": "FastAPI, LangGraph, Python",
            "firewall_settings": "Django 서버에서만 API 호출 허용",
            "auth_method": "API Key 또는 서비스 계정",
            "expected_concurrent_users": 20,
            "cloud_yn": YesNoChoices.YES,
            "hardware_spec": "4vCPU / 16GB RAM, GPU 연계 가능",
            "remarks": "산출물 생성 계층",
        },
        {
            "name": "데이터 저장소",
            "purpose": "메타데이터, 문서 파일, 벡터 검색 데이터 저장",
            "middleware_stack": "MySQL, S3 Compatible Storage, Qdrant",
            "firewall_settings": "애플리케이션 내부망 접근만 허용",
            "auth_method": "DB 계정, S3 Access Key, Qdrant API Key",
            "expected_concurrent_users": 50,
            "cloud_yn": YesNoChoices.YES,
            "hardware_spec": "RDS MySQL, Object Storage, Vector DB",
            "remarks": "영속성 계층",
        },
    ]
    for row in rows:
        ProjectNet.objects.create(project=project, created_by=actor, updated_by=actor, **row)


def _ensure_architecture_components(project, actor):
    if not ProjectNet.objects.filter(project=project).exists():
        _create_architecture_components(project, actor)


def _create_confirmed_arch(project, actor):
    _ensure_architecture_components(project, actor)
    return _create_document(
        project,
        actor,
        "DOC_ARCH",
        "1.0",
        "아키텍처 설계서",
        [
            "FIRST 프로젝트의 아키텍처 설계서 생성 완료본입니다.",
            "웹 UI, Django 웹 애플리케이션, AI Agent 서버, 데이터 저장소로 구성한다.",
            "Django는 프로젝트/산출물 상태를 관리하고 FastAPI Agent는 산출물 생성을 담당한다.",
        ],
        "아키텍처 설계서 생성 완료 샘플",
    )


def _create_confirmed_erd(project, actor):
    return _create_document(
        project,
        actor,
        "DOC_ERD",
        "1.0",
        "엔티티 관계 모델 설계서",
        [
            "FIRST 프로젝트의 엔티티 관계 모델 설계서 생성 완료본입니다.",
            "주요 엔티티: Project, User, ProjectFile, Document, DocumentDetail, DocumentApproval, ProjectNet",
            "Project는 여러 Document, ProjectFile, ProjectNet을 포함하며 Document는 여러 DocumentDetail 이력을 가진다.",
        ],
        "ERD 생성 완료 샘플",
    )


def _create_confirmed_db(project, actor):
    return _create_document(
        project,
        actor,
        "DOC_DB",
        "1.0",
        "데이터베이스 설계서",
        [
            "FIRST 프로젝트의 데이터베이스 설계서 생성 완료본입니다.",
            "tbl_project: 프로젝트 기본 정보",
            "tbl_file: 프로젝트 입력 파일 정보",
            "tbl_docs: 산출물 버전 및 진행 상태 정보",
            "tbl_docs_detail: 산출물 파일 상세 이력",
            "tbl_project_net: 아키텍처 구성요소 입력 정보",
        ],
        "DB 설계서 생성 완료 샘플",
    )


def _create_confirmed_ts(project, actor):
    return _create_document(
        project,
        actor,
        "DOC_TS",
        "1.0",
        "통합 테스트 시나리오",
        [
            "FIRST 프로젝트의 통합 테스트 시나리오 생성 완료본입니다.",
            "TS-001 RFP/회의록 선택 후 사용자 요구사항 정의서 생성 버튼이 활성화되는지 확인한다.",
            "TS-002 화면 설계서 단계에서 UI 이미지 업로드 후 생성이 가능한지 확인한다.",
            "TS-003 아키텍처 설계서 단계에서 구성요소 등록 후 생성이 가능한지 확인한다.",
            "TS-004 완료된 산출물은 버전이력에서 미리보기와 다운로드가 가능한지 확인한다.",
        ],
        "테스트 시나리오 생성 완료 샘플",
    )


@transaction.atomic
def run():
    _ensure_bucket_for_local_storage()
    admin = _ensure_reference_data()
    manager = _upsert_user("USER001", "프로젝트 관리자", "PMO", "팀장", admin=admin, is_manager=True)
    member = _upsert_user("USER002", "프로젝트 멤버", "개발팀", "담당자", admin=admin, is_manager=False)

    project = _get_or_create_project(manager)
    _ensure_project_role(project, manager, "ROLE_MANAGER", manager)
    _ensure_project_role(project, member, "ROLE_MEMBER", manager)

    input_results = _ensure_input_files(project, manager)
    removed_docs = _clear_generated_documents(project)
    removed_nets = _clear_project_nets(project)

    order = STEP_ORDER[SAMPLE_STEP]
    if order >= 1:
        _create_confirmed_srs(project, manager)
    if order >= 2:
        _create_confirmed_itf(project, manager)
    if SAMPLE_STEP == "arch_ready":
        _ensure_architecture_components(project, manager)
    if order >= 3:
        _create_confirmed_arch(project, manager)
    if order >= 4:
        _create_confirmed_erd(project, manager)
    if order >= 5:
        _create_confirmed_db(project, manager)
    if order >= 6:
        _create_confirmed_ts(project, manager)

    next_urls = {
        "srs_wait": "/docs/generate/?docs_cd=DOC_SRS&resume=1",
        "srs_done": "/docs/generate/?docs_cd=DOC_ITF&resume=1",
        "itf_done": "/docs/generate/?docs_cd=DOC_ARCH&resume=1&arch_form=1",
        "arch_ready": "/docs/generate/?docs_cd=DOC_ARCH&resume=1",
        "arch_done": "/docs/generate/?docs_cd=DOC_ERD&resume=1",
        "erd_done": "/docs/generate/?docs_cd=DOC_DB&resume=1",
        "db_done": "/docs/generate/?docs_cd=DOC_TS&resume=1",
        "all_done": "/docs/history/?docs_cd=all",
    }

    print("FIRST 프로젝트 단계별 산출물 생성 완료 가정 샘플 적용 완료")
    print(f"단계: {SAMPLE_STEP}")
    print(f"프로젝트: {project.name} / project_sn={project.sn}")
    print("입력 파일:")
    for project_file, created in input_results:
        print(f"  - {project_file.name} / file_sn={project_file.sn} / {'신규 생성' if created else '기존 유지'}")
    print(f"기존 산출물 삭제: documents={removed_docs['documents']}, details={removed_docs['details']}, approvals={removed_docs['approvals']}")
    print(f"기존 아키텍처 구성요소 삭제: {removed_nets}")
    print("로그인: USER001 / abc1234")
    print(f"확인 URL: {next_urls[SAMPLE_STEP]}")
    print("브라우저에서 현재 프로젝트가 'First Project'인지 확인한 뒤 새로고침하세요.")


run()
