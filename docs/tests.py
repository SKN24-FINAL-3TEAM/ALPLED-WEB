from django.test import TestCase
from django.urls import reverse

from common.models import Code, YesNoChoices
from projects.models import Project, ProjectUserRole
from users.models import User

from .models import Document


class DocumentHistoryListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.filter(user_id="admin").first()
        if self.user is None:
            self.user = User.objects.create(
                sn=1,
                user_id="admin",
                password="abc1234",
                name="Admin",
                sys_mngr_yn="Y",
                use_yn="Y",
            )

        self.role_manager, _ = Code.objects.get_or_create(
            code="ROLE_MANAGER",
            defaults={
                "name": "관리자",
                "created_by": self.user,
                "updated_by": self.user,
            },
        )
        self.srs_code, _ = Code.objects.get_or_create(
            code="DOC_SRS",
            defaults={
                "name": "사용자 요구사항 정의서",
                "created_by": self.user,
                "updated_by": self.user,
            },
        )
        self.db_code, _ = Code.objects.get_or_create(
            code="DOC_DB",
            defaults={
                "name": "데이터베이스 설계서",
                "created_by": self.user,
                "updated_by": self.user,
            },
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

    def test_history_list_filters_by_selected_document_type(self):
        Document.objects.create(
            sn=1,
            project=self.project,
            user=self.user,
            document_type=self.srs_code,
            version="1.0",
            modification_content="최초 생성",
            created_by=self.user,
            updated_by=self.user,
        )
        Document.objects.create(
            sn=2,
            project=self.project,
            user=self.user,
            document_type=self.db_code,
            version="1.0",
            modification_content="DB 초안",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(reverse("doc_history_list"), {"docs_cd": "DOC_SRS"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_document_code"], "DOC_SRS")
        self.assertEqual(len(response.context["documents"]), 1)
        self.assertEqual(response.context["documents"][0]["version"], "1.0")
        self.assertEqual(response.context["documents"][0]["modification_content"], "최초 생성")

    def test_history_list_uses_default_document_code_for_invalid_value(self):
        response = self.client.get(reverse("doc_history_list"), {"docs_cd": "INVALID"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_document_code"], "DOC_SRS")
