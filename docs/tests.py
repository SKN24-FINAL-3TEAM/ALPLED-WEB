from django.test import TestCase
from django.urls import reverse

from common.models import Code, ProjectFile, YesNoChoices
from projects.models import Project, ProjectUserRole
from users.models import User

from .models import Document, DocumentApproval, DocumentDetail


class DocumentWorkflowViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.filter(user_id="admin").first()
        if self.user is None:
            self.user = User.objects.create_user(
                sn=1,
                user_id="admin",
                password="abc1234",
                name="Admin",
                sys_mngr_yn="Y",
                use_yn="Y",
            )
        else:
            self.user.set_password("abc1234")
            self.user.save(update_fields=["password"])
        self.client.force_login(self.user)

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
        self.file_rfp_code, _ = Code.objects.get_or_create(
            code="FILE_RFP",
            defaults={"name": "사업제안서(RFP)", "created_by": self.user, "updated_by": self.user},
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

    def test_generate_view_clears_active_generation_session_on_plain_entry(self):
        project_file = self._create_project_file()
        session = self.client.session
        session["docs_initial_generation"] = {
            "project_sn": self.project.sn,
            "selected_file_ids": [str(project_file.sn)],
            "draft_documents": {},
            "confirmed_documents": {},
        }
        session.save()

        response = self.client.get(reverse("doc_generate"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["selected_files"])
        self.assertFalse(response.context["has_selected_files"])
        self.assertNotIn("docs_initial_generation", self.client.session)

    def test_generate_view_restores_active_generation_session_for_resume_entry(self):
        project_file = self._create_project_file()
        session = self.client.session
        session["docs_initial_generation"] = {
            "project_sn": self.project.sn,
            "selected_file_ids": [str(project_file.sn)],
            "draft_documents": {},
            "confirmed_documents": {},
        }
        session.save()

        response = self.client.get(reverse("doc_generate"), {"resume": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["selected_files"]), 1)

    def test_start_current_generation_creates_first_draft_document(self):
        project_file = self._create_project_file()
        session = self.client.session
        session["docs_initial_generation"] = {
            "project_sn": self.project.sn,
            "selected_file_ids": [str(project_file.sn)],
            "draft_documents": {},
            "confirmed_documents": {},
        }
        session.save()

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
        session = self.client.session
        session["docs_initial_generation"] = {
            "project_sn": self.project.sn,
            "selected_file_ids": [str(project_file.sn)],
            "draft_documents": {"DOC_SRS": draft.sn},
            "confirmed_documents": {},
        }
        session.save()

        response = self.client.post(reverse("doc_confirm", args=[draft.sn]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("doc_generate")))
        self.assertTrue(Document.objects.filter(document_type=self.srs_code, version="1").exists())
        updated_session = self.client.session["docs_initial_generation"]
        self.assertIn("DOC_SRS", updated_session["confirmed_documents"])
        self.assertNotIn("DOC_SRS", updated_session["draft_documents"])

    def test_document_save_releases_lock_and_adds_revision(self):
        document = self._create_document(sn=1, version="0", user=self.user)
        self._create_detail(sn=1, document=document)

        response = self.client.post(
            reverse("doc_save", args=[document.sn]),
            {"content_text": "수정된 문서 본문"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(DocumentDetail.objects.filter(document=document).count(), 2)
        document.refresh_from_db()
        self.assertIsNone(document.user)

    def test_document_download_uses_shared_document_title_helper(self):
        document = self._create_document(sn=1, version="1.0", user=None)
        self._create_detail(sn=1, document=document, content=b"docx-binary")

        response = self.client.get(f"{reverse('doc_content', args=[document.sn])}?download=1")

        self.assertEqual(response.status_code, 200)
        self.assertIn('filename="DOC_SRS_v1.0.docx"', response["Content-Disposition"])

    def test_history_preview_link_preserves_edit_mode_and_restore_button(self):
        document = self._create_document(sn=1, version="1.0", user=self.user)
        self._create_detail(sn=1, document=document, content=b"seed")

        response = self.client.get(reverse("doc_detail", args=[document.sn]), {"mode": "edit"})

        self.assertEqual(response.status_code, 200)
        preview_url = response.context["revision_rows"][0]["preview_url"]
        self.assertIn("preview_detail=1", preview_url)
        self.assertIn("mode=edit", preview_url)
        self.assertIn("modal=history", preview_url)

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
        self.assertContains(response, "산출물 승인요청")
        self.assertEqual(response.context["document_type_choices"][1][0], "DOC_SRS")

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
