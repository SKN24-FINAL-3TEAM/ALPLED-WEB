from django.test import TestCase
from django.urls import reverse

from common.models import YesNoChoices
from users.models import User


class ProjectListAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.filter(user_id="admin").first()
        if self.admin is None:
            self.admin = User.objects.create_user(
                sn=1,
                user_id="admin",
                password="abc1234",
                name="Admin",
                sys_mngr_yn=YesNoChoices.YES,
                use_yn=YesNoChoices.YES,
            )
        else:
            self.admin.set_password("abc1234")
            self.admin.sys_mngr_yn = YesNoChoices.YES
            self.admin.use_yn = YesNoChoices.YES
            self.admin.save(update_fields=["password", "sys_mngr_yn", "use_yn"])

        self.member = User.objects.filter(user_id="project-member").first()
        if self.member is None:
            self.member = User.objects.create_user(
                sn=2,
                user_id="project-member",
                password="abc1234",
                name="Project Member",
                sys_mngr_yn=YesNoChoices.NO,
                use_yn=YesNoChoices.YES,
                created_by=self.admin,
                updated_by=self.admin,
            )
        else:
            self.member.set_password("abc1234")
            self.member.sys_mngr_yn = YesNoChoices.NO
            self.member.use_yn = YesNoChoices.YES
            self.member.created_by = self.admin
            self.member.updated_by = self.admin
            self.member.save(
                update_fields=["password", "sys_mngr_yn", "use_yn", "created_by", "updated_by"]
            )

    def _doc_history_url(self):
        return f"{reverse('doc_history_list')}?docs_cd=DOC_SRS"

    def test_non_admin_access_to_project_list_redirects_to_document_history(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("project_list"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self._doc_history_url())

    def test_admin_access_to_project_list_succeeds(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("project_list"))

        self.assertEqual(response.status_code, 200)
