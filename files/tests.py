from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from common.models import Code, ProjectFile, YesNoChoices
from projects.models import Project, ProjectUserRole
from users.models import User


class FileListViewTests(TestCase):
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

        self.role_member, _ = Code.objects.get_or_create(
            code="ROLE_MEMBER",
            defaults={
                "name": "멤버",
                "created_by": self.user,
                "updated_by": self.user,
            },
        )
        self.role_manager, _ = Code.objects.get_or_create(
            code="ROLE_MANAGER",
            defaults={
                "name": "관리자",
                "created_by": self.user,
                "updated_by": self.user,
            },
        )
        self.rfp_code, _ = Code.objects.get_or_create(
            code="FILE_RFP",
            defaults={
                "name": "RFP",
                "created_by": self.user,
                "updated_by": self.user,
            },
        )
        self.meeting_code, _ = Code.objects.get_or_create(
            code="FILE_MEETING",
            defaults={
                "name": "회의록",
                "created_by": self.user,
                "updated_by": self.user,
            },
        )

        self.project = self._create_project(1, "First Project")
        self._grant_project_role(1, self.project, self.role_manager)

    def _create_project(self, sn, name, is_deleted=YesNoChoices.NO):
        return Project.objects.create(
            sn=sn,
            name=name,
            is_deleted=is_deleted,
            created_by=self.user,
            updated_by=self.user,
        )

    def _grant_project_role(self, sn, project, role):
        return ProjectUserRole.objects.create(
            sn=sn,
            project=project,
            user=self.user,
            role=role,
            created_by=self.user,
            updated_by=self.user,
        )

    def test_upload_files_creates_project_files(self):
        response = self.client.post(
            reverse("file_list"),
            {
                "action": "upload",
                "project_sn": self.project.sn,
                "rfp_files": [
                    SimpleUploadedFile(
                        "proposal.pdf",
                        b"rfp-content",
                        content_type="application/pdf",
                    )
                ],
                "meeting_files": [
                    SimpleUploadedFile(
                        "meeting.docx",
                        b"meeting-content",
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                ],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProjectFile.objects.count(), 2)
        self.assertTrue(ProjectFile.objects.filter(file_type=self.rfp_code).exists())
        self.assertTrue(ProjectFile.objects.filter(file_type=self.meeting_code).exists())

    def test_search_filters_files_by_type_and_name(self):
        ProjectFile.objects.create(
            sn=1,
            project=self.project,
            file_type=self.rfp_code,
            name="RFP_20260520.pdf",
            path="RFP_20260520.pdf",
            content=b"rfp",
            size=3,
            extension="pdf",
            created_by=self.user,
            updated_by=self.user,
        )
        ProjectFile.objects.create(
            sn=2,
            project=self.project,
            file_type=self.meeting_code,
            name="meeting_20260520.docx",
            path="meeting_20260520.docx",
            content=b"meeting",
            size=7,
            extension="docx",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(
            reverse("file_list"),
            {
                "file_type": "RFP",
                "field": "name",
                "q": "RFP_20260520",
            },
        )

        self.assertEqual(response.status_code, 200)
        documents = response.context["documents"]
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["name"], "RFP_20260520.pdf")

    def test_delete_and_download_selected_files(self):
        project_file = ProjectFile.objects.create(
            sn=1,
            project=self.project,
            file_type=self.rfp_code,
            name="proposal.pdf",
            path="proposal.pdf",
            content=b"download-me",
            size=11,
            extension="pdf",
            created_by=self.user,
            updated_by=self.user,
        )

        download_response = self.client.post(
            reverse("file_list"),
            {
                "action": "download",
                "project_sn": self.project.sn,
                "selected_files": [project_file.sn],
            },
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("attachment;", download_response["Content-Disposition"])
        self.assertEqual(download_response.content, b"download-me")

        delete_response = self.client.post(
            reverse("file_list"),
            {
                "action": "delete",
                "project_sn": self.project.sn,
                "selected_files": [project_file.sn],
            },
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(ProjectFile.objects.filter(sn=project_file.sn).exists())

    def test_sidebar_lists_only_accessible_non_deleted_projects(self):
        member_project = self._create_project(2, "Member Project")
        deleted_project = self._create_project(3, "Deleted Project", is_deleted=YesNoChoices.YES)
        self._create_project(4, "Unassigned Project")

        self._grant_project_role(2, member_project, self.role_member)
        self._grant_project_role(3, deleted_project, self.role_manager)

        response = self.client.get(reverse("file_list"))

        self.assertEqual(response.status_code, 200)
        available_names = [project.name for project in response.context["available_projects"]]
        self.assertEqual(available_names, ["First Project", "Member Project"])
        self.assertEqual(response.context["current_project"].name, "First Project")

    def test_set_current_project_updates_session_selection(self):
        second_project = self._create_project(2, "Second Project")
        self._grant_project_role(2, second_project, self.role_member)

        response = self.client.post(
            reverse("set_current_project"),
            {
                "project_sn": second_project.sn,
                "next": reverse("file_list"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("file_list"))

        follow_up = self.client.get(reverse("file_list"))
        self.assertEqual(follow_up.context["current_project"].name, "Second Project")
