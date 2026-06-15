from django.test import TestCase
from django.urls import reverse

from common.models import YesNoChoices

from .models import User
from .views import (
    DEFAULT_DOCUMENT_CODE,
    TEMP_PASSWORD,
    TEMP_PASSWORD_REDIRECT_SESSION_KEY,
)


class UserViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.filter(user_id="admin").first()
        if self.admin is None:
            self.admin = User.objects.create_user(
                sn=1,
                user_id="admin",
                password="abc1234",
                name="Admin",
                sys_mngr_yn=YesNoChoices.YES,
                tmpr_pswd_yn=YesNoChoices.NO,
                use_yn=YesNoChoices.YES,
            )
        else:
            self.admin.set_password("abc1234")
            self.admin.name = "Admin"
            self.admin.sys_mngr_yn = YesNoChoices.YES
            self.admin.tmpr_pswd_yn = YesNoChoices.NO
            self.admin.use_yn = YesNoChoices.YES
            self.admin.save(update_fields=["password", "name", "sys_mngr_yn", "tmpr_pswd_yn", "use_yn"])

        self.member = User.objects.filter(user_id="member").first()
        if self.member is None:
            self.member = User.objects.create_user(
                sn=2,
                user_id="member",
                password="abc1234",
                name="Member",
                sys_mngr_yn=YesNoChoices.NO,
                tmpr_pswd_yn=YesNoChoices.NO,
                use_yn=YesNoChoices.YES,
                created_by=self.admin,
                updated_by=self.admin,
            )
        else:
            self.member.set_password("abc1234")
            self.member.name = "Member"
            self.member.sys_mngr_yn = YesNoChoices.NO
            self.member.tmpr_pswd_yn = YesNoChoices.NO
            self.member.use_yn = YesNoChoices.YES
            self.member.created_by = self.admin
            self.member.updated_by = self.admin
            self.member.save(
                update_fields=[
                    "password",
                    "name",
                    "sys_mngr_yn",
                    "tmpr_pswd_yn",
                    "use_yn",
                    "created_by",
                    "updated_by",
                ]
            )

    def _doc_history_url(self):
        return f"{reverse('doc_history_list')}?docs_cd={DEFAULT_DOCUMENT_CODE}"

    def _create_temp_user(self):
        return User.objects.create_user(
            sn=3,
            user_id="tempuser",
            password=TEMP_PASSWORD,
            name="Temp User",
            department="Initial Dept",
            position="Initial Position",
            sys_mngr_yn=YesNoChoices.NO,
            tmpr_pswd_yn=YesNoChoices.YES,
            use_yn=YesNoChoices.YES,
            created_by=self.admin,
            updated_by=self.admin,
        )

    def test_login_view_renders_for_anonymous_user(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/login.html")

    def test_admin_login_redirects_to_user_list(self):
        response = self.client.post(
            reverse("login"),
            {"user_id": "admin", "password": "abc1234"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("user_list"))

    def test_non_admin_login_redirects_to_document_history(self):
        response = self.client.post(
            reverse("login"),
            {"user_id": "member", "password": "abc1234"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self._doc_history_url())

    def test_temp_password_login_redirects_to_notice_and_stores_next_url(self):
        temp_user = self._create_temp_user()

        response = self.client.post(
            reverse("login"),
            {
                "user_id": temp_user.user_id,
                "password": TEMP_PASSWORD,
                "next": reverse("project_list"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("temp_password_notice"))
        self.assertEqual(
            self.client.session[TEMP_PASSWORD_REDIRECT_SESSION_KEY],
            reverse("project_list"),
        )

    def test_temp_password_notice_uses_styled_notice_instead_of_browser_alert(self):
        temp_user = self._create_temp_user()
        self.client.force_login(temp_user)

        response = self.client.get(reverse("temp_password_notice"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/temp_password_notice.html")
        self.assertContains(response, "data-auto-notice", html=False)
        self.assertContains(response, "임시 비밀번호입니다. 비밀번호를 변경해 주세요.")
        self.assertNotContains(response, "alert(", html=False)

    def test_profile_update_changes_name_department_and_position(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("user_profile"),
            {
                "name": "Updated Admin",
                "department": "Platform",
                "position": "Lead",
                "new_password": "",
                "new_password_confirm": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("user_list"))

        self.admin.refresh_from_db()
        self.assertEqual(self.admin.name, "Updated Admin")
        self.assertEqual(self.admin.department, "Platform")
        self.assertEqual(self.admin.position, "Lead")
        self.assertEqual(self.admin.tmpr_pswd_yn, YesNoChoices.NO)

    def test_profile_password_change_clears_temp_password_flag_and_keeps_session(self):
        temp_user = self._create_temp_user()
        self.client.force_login(temp_user)
        session = self.client.session
        session[TEMP_PASSWORD_REDIRECT_SESSION_KEY] = reverse("project_list")
        session.save()

        response = self.client.post(
            reverse("user_profile"),
            {
                "name": "Temp User",
                "department": "Security",
                "position": "Engineer",
                "new_password": "newpass123!",
                "new_password_confirm": "newpass123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("project_list"))

        temp_user.refresh_from_db()
        self.assertEqual(temp_user.department, "Security")
        self.assertEqual(temp_user.position, "Engineer")
        self.assertEqual(temp_user.tmpr_pswd_yn, YesNoChoices.NO)
        self.assertTrue(temp_user.check_password("newpass123!"))

        follow_response = self.client.get(self._doc_history_url())
        self.assertEqual(follow_response.status_code, 200)

    def test_non_admin_access_to_user_list_redirects_to_document_history(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("user_list"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self._doc_history_url())

    def test_create_user_inserts_requested_values(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("user_list"),
            {
                "action": "create_user",
                "user_id": "EMP001",
                "name": "Hong",
                "department": "Development",
                "position": "Manager",
                "use_yn": YesNoChoices.NO,
            },
        )

        self.assertEqual(response.status_code, 302)

        created_user = User.objects.get(user_id="EMP001")
        self.assertEqual(created_user.name, "Hong")
        self.assertEqual(created_user.department, "Development")
        self.assertEqual(created_user.position, "Manager")
        self.assertEqual(created_user.sys_mngr_yn, YesNoChoices.NO)
        self.assertEqual(created_user.tmpr_pswd_yn, YesNoChoices.YES)
        self.assertEqual(created_user.use_yn, YesNoChoices.NO)
        self.assertTrue(created_user.check_password(TEMP_PASSWORD))

    def test_user_list_renders_reset_password_button_in_detail_modal(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("user_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="action" value="reset_user_password"', html=False)
        self.assertContains(response, "data-confirm-form", html=False)

    def test_reset_user_password_sets_temp_flag_and_default_password(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("user_list"),
            {
                "action": "reset_user_password",
                "user_sn": str(self.member.sn),
            },
        )

        self.assertEqual(response.status_code, 302)

        self.member.refresh_from_db()
        self.assertEqual(self.member.tmpr_pswd_yn, YesNoChoices.YES)
        self.assertTrue(self.member.check_password(TEMP_PASSWORD))

    def test_resetting_own_password_keeps_admin_session_valid(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("user_list"),
            {
                "action": "reset_user_password",
                "user_sn": str(self.admin.sn),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse("user_list")).status_code, 200)

        self.admin.refresh_from_db()
        self.assertEqual(self.admin.tmpr_pswd_yn, YesNoChoices.YES)
        self.assertTrue(self.admin.check_password(TEMP_PASSWORD))

    def test_sidebar_hides_admin_links_for_non_admin_user(self):
        self.client.force_login(self.member)

        response = self.client.get(self._doc_history_url())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'href="{reverse("user_list")}"', html=False)
        self.assertNotContains(response, f'href="{reverse("project_list")}"', html=False)

    def test_sidebar_profile_block_contains_click_affordance(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("user_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-profile-url=", html=False)
        self.assertContains(response, "cursor-pointer", html=False)
