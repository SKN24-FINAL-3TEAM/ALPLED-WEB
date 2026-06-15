import os
import shutil
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from common.models import Code, ProjectFile, YesNoChoices
from projects.models import Project, ProjectNet, ProjectUserRole
from users.models import User

from .models import Document, DocumentApproval, DocumentDetail
from .services import extract_text_from_docx


class DocumentWorkflowViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.filter(user_id="admin").first()
        if self.user is None:
            self.user = User.objects.create_user(
                sn=1,
                user_id="admin",
                password="abc1234",
                name="Admin",
                sys_mngr_yn=YesNoChoices.YES,
                use_yn=YesNoChoices.YES,
            )
        else:
            self.user.set_password("abc1234")
            self.user.use_yn = YesNoChoices.YES
            self.user.save(update_fields=["password", "use_yn"])
        self.client.force_login(self.user)
        self.temp_dir = Path.cwd() / ".tmp-test-itf" / self._testMethodName
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.role_manager, _ = Code.objects.get_or_create(
            code="ROLE_MANAGER",
            defaults={"name": "관리자", "created_by": self.user, "updated_by": self.user},
        )
        self.role_member, _ = Code.objects.get_or_create(
            code="ROLE_MEMBER",
            defaults={"name": "멤버", "created_by": self.user, "updated_by": self.user},
        )

        self.srs_code, _ = Code.objects.get_or_create(
            code="DOC_SRS",
            defaults={"name": "사용자 요구사항 정의서", "created_by": self.user, "updated_by": self.user},
        )
        self.itf_code, _ = Code.objects.get_or_create(
            code="DOC_ITF",
            defaults={"name": "사용자 인터페이스 설계서", "created_by": self.user, "updated_by": self.user},
        )
        self.arch_code, _ = Code.objects.get_or_create(
            code="DOC_ARCH",
            defaults={"name": "아키텍처 설계서", "created_by": self.user, "updated_by": self.user},
        )
        self.erd_code, _ = Code.objects.get_or_create(
            code="DOC_ERD",
            defaults={"name": "엔티티 관계 모델 설계서", "created_by": self.user, "updated_by": self.user},
        )
        self.db_code, _ = Code.objects.get_or_create(
            code="DOC_DB",
            defaults={"name": "데이터베이스 설계서", "created_by": self.user, "updated_by": self.user},
        )
        self.ts_code, _ = Code.objects.get_or_create(
            code="DOC_TS",
            defaults={"name": "통합 테스트 시나리오", "created_by": self.user, "updated_by": self.user},
        )

        self.file_rfp_code, _ = Code.objects.get_or_create(
            code="FILE_RFP",
            defaults={"name": "제안요청서(RFP)", "created_by": self.user, "updated_by": self.user},
        )
        self.file_meeting_code, _ = Code.objects.get_or_create(
            code="FILE_MEETING",
            defaults={"name": "회의록", "created_by": self.user, "updated_by": self.user},
        )

        self.approval_requested, _ = Code.objects.get_or_create(
            code="APRV_REQ",
            defaults={"name": "승인 대기", "created_by": self.user, "updated_by": self.user},
        )
        self.approval_approved, _ = Code.objects.get_or_create(
            code="APRV_COM",
            defaults={"name": "승인 완료", "created_by": self.user, "updated_by": self.user},
        )

        self.project = Project.objects.create(
            sn=1,
            name="First Project",
            is_deleted=YesNoChoices.NO,
            created_by=self.user,
            updated_by=self.user,
        )
        ProjectUserRole.objects.create(
            sn=1,
            project=self.project,
            user=self.user,
            role=self.role_manager,
            created_by=self.user,
            updated_by=self.user,
        )
        session = self.client.session
        session["current_project_sn"] = self.project.sn
        session.save()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_project_file(self, sn=1, *, code=None, name="proposal.pdf"):
        return ProjectFile.objects.create(
            sn=sn,
            project=self.project,
            file_type=code or self.file_rfp_code,
            name=name,
            path=name,
            content=b"file-content",
            size=12,
            extension=name.split(".")[-1][:4],
            created_by=self.user,
            updated_by=self.user,
        )

    def _create_document(self, sn=1, *, document_type=None, version="1.0", user=None):
        return Document.objects.create(
            sn=sn,
            project=self.project,
            user=user,
            document_type=document_type or self.srs_code,
            version=version,
            modification_content="최초 생성",
            created_by=self.user,
            updated_by=self.user,
        )

    def _create_detail(self, sn=1, *, document=None, content=b"docx-binary"):
        return DocumentDetail.objects.create(
            sn=sn,
            document=document,
            content=content,
            is_deleted="N",
            created_by=self.user,
        )

    def _create_project_net(
        self,
        sn=1,
        *,
        project=None,
        name="업무망",
        purpose="내부 업무 처리",
        middleware_stack="Nginx",
        firewall_settings="Allow 443",
        auth_method="SSO",
        expected_concurrent_users=50,
        cloud_yn=YesNoChoices.YES,
        hardware_spec="8core/32GB",
        remarks="기본 비고",
    ):
        return ProjectNet.objects.create(
            sn=sn,
            project=project or self.project,
            name=name,
            purpose=purpose,
            middleware_stack=middleware_stack,
            firewall_settings=firewall_settings,
            auth_method=auth_method,
            expected_concurrent_users=expected_concurrent_users,
            cloud_yn=cloud_yn,
            hardware_spec=hardware_spec,
            remarks=remarks,
            created_by=self.user,
            updated_by=self.user,
        )

    def _set_generation_state(
        self,
        *,
        selected_file_ids=None,
        draft_documents=None,
        confirmed_documents=None,
        itf_reference_files=None,
    ):
        session = self.client.session
        session["docs_initial_generation"] = {
            "project_sn": self.project.sn,
            "selected_file_ids": [str(file_id) for file_id in (selected_file_ids or [])],
            "draft_documents": draft_documents or {},
            "confirmed_documents": confirmed_documents or {},
            "itf_reference_files": itf_reference_files or [],
        }
        session.save()

    def test_history_list_shows_generation_button_before_any_confirmed_document_exists(self):
        response = self.client.get(reverse("doc_history_list"), {"docs_cd": "DOC_ITF"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_document_code"], "DOC_ITF")
        self.assertTrue(response.context["can_generate"])

    def test_history_list_excludes_version_zero_and_keeps_latest_duplicate_version(self):
        self._create_document(sn=1, version="1.0", document_type=self.srs_code)
        newer = self._create_document(sn=2, version="1.0", document_type=self.srs_code)
        self._create_document(sn=3, version="0", document_type=self.srs_code)

        response = self.client.get(reverse("doc_history_list"), {"docs_cd": "DOC_SRS"})

        self.assertEqual(response.status_code, 200)
        documents = response.context["documents"]
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["sn"], newer.sn)

    def test_generate_view_initially_shows_only_file_load_ui(self):
        response = self.client.get(reverse("doc_generate"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["selected_files"])
        self.assertIsNone(response.context["current_draft"])
        self.assertTrue(response.context["show_file_selector"])

    def test_selecting_files_updates_generation_session_and_redirects_to_clean_url(self):
        project_file = self._create_project_file()

        response = self.client.get(
            reverse("doc_generate"),
            {"selected_files": [project_file.sn], "apply_selection": "1"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('doc_generate')}?docs_cd=DOC_SRS&resume=1")
        self.assertEqual(
            self.client.session["docs_initial_generation"]["selected_file_ids"],
            [str(project_file.sn)],
        )

    def test_generate_view_restores_active_generation_session_on_plain_entry(self):
        project_file = self._create_project_file()
        self._set_generation_state(selected_file_ids=[project_file.sn])

        response = self.client.get(reverse("doc_generate"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["selected_files"]), 1)
        self.assertTrue(response.context["has_selected_files"])
        self.assertIn("docs_initial_generation", self.client.session)

    def test_generate_view_restores_active_generation_session_for_resume_entry(self):
        project_file = self._create_project_file()
        self._set_generation_state(selected_file_ids=[project_file.sn])

        response = self.client.get(reverse("doc_generate"), {"resume": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["selected_files"]), 1)

    def test_reset_generation_clears_session_state_and_temp_references(self):
        with self.settings(ALPLED_ITF_REFERENCE_ROOT=self.temp_dir):
            self._set_generation_state(confirmed_documents={"DOC_SRS": 1})
            upload = SimpleUploadedFile("screen.png", b"png-bytes", content_type="image/png")
            self.client.post(
                reverse("doc_generate"),
                {"action": "upload_itf_reference", "docs_cd": "DOC_ITF", "itf_references": [upload]},
            )
            reference_path = self.client.session["docs_initial_generation"]["itf_reference_files"][0]["path"]

            response = self.client.post(
                reverse("doc_generate"),
                {"action": "reset_generation", "docs_cd": "DOC_ITF"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("docs_initial_generation", self.client.session)
        self.assertTrue(reference_path.endswith(".png"))

    def test_start_current_generation_creates_first_draft_document(self):
        project_file = self._create_project_file()
        self._set_generation_state(selected_file_ids=[project_file.sn])

        response = self.client.post(
            reverse("doc_generate"),
            {"action": "start_current", "selected_files": [project_file.sn]},
        )

        self.assertEqual(response.status_code, 302)
        draft = Document.objects.get(version="0")
        self.assertEqual(draft.document_type_id, "DOC_SRS")
        self.assertEqual(DocumentDetail.objects.filter(document=draft).count(), 1)

    def test_confirming_initial_draft_advances_to_next_document_step(self):
        project_file = self._create_project_file()
        draft = self._create_document(sn=1, version="0", document_type=self.srs_code)
        self._create_detail(sn=1, document=draft)
        self._set_generation_state(
            selected_file_ids=[project_file.sn],
            draft_documents={"DOC_SRS": draft.sn},
        )

        response = self.client.post(reverse("doc_confirm", args=[draft.sn]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("doc_generate")))
        self.assertTrue(Document.objects.filter(document_type=self.srs_code, version="1").exists())
        updated_session = self.client.session["docs_initial_generation"]
        self.assertIn("DOC_SRS", updated_session["confirmed_documents"])
        self.assertNotIn("DOC_SRS", updated_session["draft_documents"])

    def test_itf_start_requires_uploaded_references(self):
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1})

        response = self.client.post(
            reverse("doc_generate"),
            {"action": "start_current", "docs_cd": "DOC_ITF"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Document.objects.filter(version="0").count(), 0)
        self.assertTrue(response["Location"].startswith(f"{reverse('doc_generate')}?docs_cd=DOC_ITF&resume=1"))

    def test_itf_upload_accepts_valid_images_and_rejects_invalid_files(self):
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1})
        valid = SimpleUploadedFile("screen.png", b"png-bytes", content_type="image/png")
        invalid = SimpleUploadedFile("notes.txt", b"text", content_type="text/plain")
        oversized = SimpleUploadedFile(
            "large.jpg",
            b"x" * (3 * 1024 * 1024 + 1),
            content_type="image/jpeg",
        )

        with self.settings(ALPLED_ITF_REFERENCE_ROOT=self.temp_dir):
            response = self.client.post(
                reverse("doc_generate"),
                {
                    "action": "upload_itf_reference",
                    "docs_cd": "DOC_ITF",
                    "itf_references": [valid, invalid, oversized],
                },
            )

        self.assertEqual(response.status_code, 302)
        references = self.client.session["docs_initial_generation"]["itf_reference_files"]
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["name"], "screen.png")
        self.assertTrue(os.path.exists(references[0]["path"]))

    def test_itf_upload_appends_references_across_multiple_requests(self):
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1})
        first = SimpleUploadedFile("screen-1.png", b"png-bytes-1", content_type="image/png")
        second = SimpleUploadedFile("screen-2.jpg", b"jpg-bytes-2", content_type="image/jpeg")

        with self.settings(ALPLED_ITF_REFERENCE_ROOT=self.temp_dir):
            first_response = self.client.post(
                reverse("doc_generate"),
                {
                    "action": "upload_itf_reference",
                    "docs_cd": "DOC_ITF",
                    "itf_references": [first],
                },
            )
            second_response = self.client.post(
                reverse("doc_generate"),
                {
                    "action": "upload_itf_reference",
                    "docs_cd": "DOC_ITF",
                    "itf_references": [second],
                },
            )

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        references = self.client.session["docs_initial_generation"]["itf_reference_files"]
        self.assertEqual(len(references), 2)
        self.assertEqual([reference["name"] for reference in references], ["screen-1.png", "screen-2.jpg"])

    def test_itf_remove_deletes_temp_file_and_session_entry(self):
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1})
        upload = SimpleUploadedFile("screen.png", b"png-bytes", content_type="image/png")

        with self.settings(ALPLED_ITF_REFERENCE_ROOT=self.temp_dir):
            self.client.post(
                reverse("doc_generate"),
                {"action": "upload_itf_reference", "docs_cd": "DOC_ITF", "itf_references": [upload]},
            )
            reference = self.client.session["docs_initial_generation"]["itf_reference_files"][0]

            response = self.client.post(
                reverse("doc_generate"),
                {
                    "action": "remove_itf_reference",
                    "docs_cd": "DOC_ITF",
                    "reference_token": reference["token"],
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["docs_initial_generation"]["itf_reference_files"], [])
        self.assertTrue(reference["path"].endswith(".png"))

    def test_itf_draft_generation_uses_uploaded_reference_names(self):
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1})
        upload = SimpleUploadedFile("screen.png", b"png-bytes", content_type="image/png")

        with self.settings(ALPLED_ITF_REFERENCE_ROOT=self.temp_dir):
            self.client.post(
                reverse("doc_generate"),
                {"action": "upload_itf_reference", "docs_cd": "DOC_ITF", "itf_references": [upload]},
            )
            response = self.client.post(
                reverse("doc_generate"),
                {"action": "start_current", "docs_cd": "DOC_ITF"},
            )

        self.assertEqual(response.status_code, 302)
        draft = Document.objects.get(document_type=self.itf_code, version="0")
        content_text = extract_text_from_docx(DocumentDetail.objects.get(document=draft).content)
        self.assertIn("screen.png", content_text)

    def test_architecture_form_add_creates_project_net_with_requested_mapping(self):
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1, "DOC_ITF": 2})

        response = self.client.post(
            reverse("doc_generate"),
            {
                "action": "add_project_net",
                "docs_cd": "DOC_ARCH",
                "name": "업무망",
                "purpose": "업무 처리",
                "middleware_stack": "Nginx, Tomcat",
                "firewall_settings": "443 허용",
                "auth_method": "SSO",
                "expected_concurrent_users": "120",
                "cloud_yn": YesNoChoices.YES,
                "hardware_spec": "8core / 32GB",
                "remarks": "이중화 구성",
            },
        )

        self.assertEqual(response.status_code, 302)
        project_net = ProjectNet.objects.get(project=self.project)
        self.assertEqual(project_net.name, "업무망")
        self.assertEqual(project_net.purpose, "업무 처리")
        self.assertEqual(project_net.middleware_stack, "Nginx, Tomcat")
        self.assertEqual(project_net.firewall_settings, "443 허용")
        self.assertEqual(project_net.auth_method, "SSO")
        self.assertEqual(project_net.expected_concurrent_users, 120)
        self.assertEqual(project_net.cloud_yn, YesNoChoices.YES)
        self.assertEqual(project_net.hardware_spec, "8core / 32GB")
        self.assertEqual(project_net.remarks, "이중화 구성")

    def test_architecture_delete_removes_only_target_row_in_current_project(self):
        other_project = Project.objects.create(
            sn=2,
            name="Other Project",
            is_deleted=YesNoChoices.NO,
            created_by=self.user,
            updated_by=self.user,
        )
        target = self._create_project_net(sn=1, name="업무망")
        survivor = self._create_project_net(sn=2, name="외부망", project=other_project)
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1, "DOC_ITF": 2})

        response = self.client.post(
            reverse("doc_generate"),
            {
                "action": "delete_project_net",
                "docs_cd": "DOC_ARCH",
                "project_net_sn": target.sn,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectNet.objects.filter(sn=target.sn, project=self.project).exists())
        self.assertTrue(ProjectNet.objects.filter(sn=survivor.sn, project=other_project).exists())

    def test_architecture_start_requires_project_net_then_creates_draft(self):
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1, "DOC_ITF": 2})

        missing_response = self.client.post(
            reverse("doc_generate"),
            {"action": "start_current", "docs_cd": "DOC_ARCH"},
        )

        self.assertEqual(missing_response.status_code, 302)
        self.assertEqual(Document.objects.filter(document_type=self.arch_code, version="0").count(), 0)

        self._create_project_net()
        success_response = self.client.post(
            reverse("doc_generate"),
            {"action": "start_current", "docs_cd": "DOC_ARCH"},
        )

        self.assertEqual(success_response.status_code, 302)
        draft = Document.objects.get(document_type=self.arch_code, version="0")
        self.assertEqual(draft.document_type_id, "DOC_ARCH")
        self.assertEqual(DocumentDetail.objects.filter(document=draft).count(), 1)

    def test_architecture_draft_generation_uses_project_net_names(self):
        self._set_generation_state(confirmed_documents={"DOC_SRS": 1, "DOC_ITF": 2})
        self._create_project_net(name="업무망", purpose="내부 시스템")

        response = self.client.post(
            reverse("doc_generate"),
            {"action": "start_current", "docs_cd": "DOC_ARCH"},
        )

        self.assertEqual(response.status_code, 302)
        draft = Document.objects.get(document_type=self.arch_code, version="0")
        content_text = extract_text_from_docx(DocumentDetail.objects.get(document=draft).content)
        self.assertIn("업무망", content_text)
        self.assertIn("내부 시스템", content_text)

    def test_document_save_releases_lock_and_adds_revision(self):
        document = self._create_document(sn=1, version="0", user=self.user)
        self._create_detail(sn=1, document=document)

        response = self.client.post(
            reverse("doc_save", args=[document.sn]),
            {"content_text": "수정한 문서 본문"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(DocumentDetail.objects.filter(document=document).count(), 2)
        document.refresh_from_db()
        self.assertIsNone(document.user)

    def test_document_save_waits_for_onlyoffice_revision_when_form_has_no_text(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        detail = self._create_detail(sn=1, document=document)

        with patch("docs.views.request_force_save", return_value={"error": 0}) as force_save_mock, patch(
            "docs.views.wait_for_new_revision", return_value=detail
        ) as wait_mock, patch(
            "docs.views.settings.ONLYOFFICE_DOCUMENT_SERVER_URL",
            "http://document-server",
        ):
            response = self.client.post(reverse("doc_save", args=[document.sn]), {})

        self.assertEqual(response.status_code, 302)
        force_save_mock.assert_called_once()
        wait_mock.assert_called_once_with(document, baseline_detail_sn=detail.sn)

    def test_document_save_ajax_returns_redirect_after_onlyoffice_revision_is_ready(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        detail = self._create_detail(sn=1, document=document)
        new_detail = self._create_detail(sn=2, document=document)

        with patch("docs.views.request_force_save", return_value={"error": 0}) as force_save_mock, patch(
            "docs.views.wait_for_new_revision", return_value=new_detail
        ) as wait_mock, patch(
            "docs.views.settings.ONLYOFFICE_DOCUMENT_SERVER_URL",
            "http://document-server",
        ):
            response = self.client.post(
                reverse("doc_save", args=[document.sn]),
                {"baseline_detail_sn": str(detail.sn)},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect_url"], reverse("doc_detail", args=[document.sn]))
        force_save_mock.assert_called_once()
        wait_mock.assert_called_once_with(document, baseline_detail_sn=detail.sn)

    def test_document_save_ajax_keeps_edit_mode_when_onlyoffice_revision_is_missing(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        detail = self._create_detail(sn=1, document=document)

        with patch("docs.views.request_force_save", return_value={"error": 0}), patch(
            "docs.views.wait_for_new_revision", return_value=detail
        ), patch(
            "docs.views.settings.ONLYOFFICE_DOCUMENT_SERVER_URL",
            "http://document-server",
        ):
            response = self.client.post(
                reverse("doc_save", args=[document.sn]),
                {"baseline_detail_sn": str(detail.sn)},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 409)
        document.refresh_from_db()
        self.assertEqual(document.user_id, self.user.sn)

    def test_document_save_ajax_redirects_when_onlyoffice_reports_no_changes(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        detail = self._create_detail(sn=1, document=document)

        with patch("docs.views.request_force_save", return_value={"error": 4}) as force_save_mock, patch(
            "docs.views.settings.ONLYOFFICE_DOCUMENT_SERVER_URL",
            "http://document-server",
        ):
            response = self.client.post(
                reverse("doc_save", args=[document.sn]),
                {"baseline_detail_sn": str(detail.sn)},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["latest_detail_sn"], detail.sn)
        force_save_mock.assert_called_once()

    def test_document_download_uses_shared_document_title_helper(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        self._create_detail(sn=1, document=document, content=b"docx-binary")

        response = self.client.get(f"{reverse('doc_content', args=[document.sn])}?download=1")

        self.assertEqual(response.status_code, 200)
        self.assertIn('filename="DOC_SRS_v1.0.docx"', response["Content-Disposition"])

    def test_history_preview_link_uses_modal_preview_endpoint(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        self._create_detail(sn=1, document=document, content=b"seed")

        response = self.client.get(reverse("doc_detail", args=[document.sn]), {"mode": "edit"})

        self.assertEqual(response.status_code, 200)
        preview_url = response.context["revision_rows"][0]["preview_url"]
        self.assertEqual(preview_url, reverse("doc_history_preview", args=[document.sn, 1]))

    def test_history_preview_endpoint_returns_revision_text_without_page_reload(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        detail = self._create_detail(sn=1, document=document, content=b"seed")

        with patch("docs.views.extract_text_from_docx", return_value="미리보기 본문"):
            response = self.client.get(reverse("doc_history_preview", args=[document.sn, detail.sn]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["preview_text"], "미리보기 본문")

    def test_history_preview_endpoint_returns_404_for_missing_revision(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        self._create_detail(sn=1, document=document, content=b"seed")

        response = self.client.get(reverse("doc_history_preview", args=[document.sn, 999]))

        self.assertEqual(response.status_code, 404)

    def test_document_callback_saves_onlyoffice_revision(self):
        document = self._create_document(sn=1, version="0", user=None)
        self._create_detail(sn=1, document=document, content=b"seed")

        response = self.client.post(
            reverse("doc_callback", args=[document.sn]),
            data='{"status": 2, "content_text": "OnlyOffice save"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(DocumentDetail.objects.filter(document=document).count(), 2)

    def test_editor_config_uses_desktop_type_for_edit_mode(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        self._create_detail(sn=1, document=document, content=b"seed")

        response = self.client.get(reverse("doc_editor_config", args=[document.sn]), {"mode": "edit"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["type"], "desktop")
        self.assertEqual(payload["editorConfig"]["mode"], "edit")
        self.assertTrue(payload["document"]["permissions"]["edit"])

    def test_editor_config_uses_embedded_type_for_view_mode(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        self._create_detail(sn=1, document=document, content=b"seed")

        response = self.client.get(reverse("doc_editor_config", args=[document.sn]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["type"], "embedded")
        self.assertEqual(payload["editorConfig"]["mode"], "view")
        self.assertFalse(payload["document"]["permissions"]["edit"])

    def test_approval_list_view_renders_with_db_driven_choices(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        detail = self._create_detail(sn=1, document=document)
        DocumentApproval.objects.create(
            sn=1,
            detail=detail,
            approval_status=self.approval_requested,
            request_content="승인 요청입니다.",
            rejection_reason=None,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(reverse("doc_approval_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["document_type_choices"][1][0], "DOC_SRS")

    def test_document_detail_shows_approval_request_button_in_view_mode_for_last_editor(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        self._create_detail(sn=1, document=document)

        response = self.client.get(reverse("doc_detail", args=[document.sn]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-modal-target="approval-request-modal"', html=False)

    def test_document_detail_hides_approval_request_button_in_edit_mode(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        self._create_detail(sn=1, document=document)

        response = self.client.get(reverse("doc_detail", args=[document.sn]), {"mode": "edit"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-modal-target="approval-request-modal"', html=False)

    def test_document_request_approval_allows_last_editor_from_detail_view(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        detail = self._create_detail(sn=1, document=document)

        response = self.client.post(
            reverse("doc_request_approval", args=[document.sn]),
            {"request_content": "승인 요청입니다."},
        )

        self.assertEqual(response.status_code, 302)
        approval = DocumentApproval.objects.get(detail=detail)
        self.assertEqual(approval.request_content, "승인 요청입니다.")

    def test_approval_detail_uses_modal_buttons_instead_of_inline_forms(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        detail = self._create_detail(sn=1, document=document)
        approval = DocumentApproval.objects.create(
            sn=1,
            detail=detail,
            approval_status=self.approval_requested,
            request_content="승인 요청입니다.",
            rejection_reason=None,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(reverse("doc_approval_detail", args=[approval.sn]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-modal-target="approval-approve-modal"', html=False)
        self.assertContains(response, 'data-modal-target="approval-reject-modal"', html=False)

    def test_manager_cannot_approve_duplicate_version_for_same_document_type(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        detail = self._create_detail(sn=1, document=document)
        approval = DocumentApproval.objects.create(
            sn=1,
            detail=detail,
            approval_status=self.approval_requested,
            request_content="승인 요청입니다.",
            rejection_reason=None,
            created_by=self.user,
            updated_by=self.user,
        )
        self._create_document(sn=2, version="1.1", user=None, document_type=self.srs_code)

        response = self.client.post(
            reverse("doc_approval_approve", args=[approval.sn]),
            {"new_version": "1.1"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("?modal=approve"))
        approval.refresh_from_db()
        self.assertEqual(approval.approval_status_id, "APRV_REQ")

    def test_manager_can_approve_request_and_create_new_version(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        detail = self._create_detail(sn=1, document=document)
        approval = DocumentApproval.objects.create(
            sn=1,
            detail=detail,
            approval_status=self.approval_requested,
            request_content="승인 요청입니다.",
            rejection_reason=None,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            reverse("doc_approval_approve", args=[approval.sn]),
            {"new_version": "1.1"},
        )

        self.assertEqual(response.status_code, 302)
        approval.refresh_from_db()
        self.assertEqual(approval.approval_status_id, "APRV_COM")
        self.assertTrue(Document.objects.filter(version="1.1").exists())
