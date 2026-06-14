from django.test import TestCase
from django.urls import reverse

from common.models import YesNoChoices

from .models import User
from .views import TEMP_PASSWORD


class UserListViewTests(TestCase):
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
            self.admin.save(update_fields=["password"])
        self.client.force_login(self.admin)

    def test_login_view_renders_for_anonymous_user(self):
        self.client.logout()

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/login.html")

    def test_login_view_authenticates_and_redirects_to_user_list(self):
        self.client.logout()

        response = self.client.post(
            reverse("login"),
            {"user_id": "admin", "password": "abc1234"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("user_list"))

    def test_logout_redirects_to_login_page(self):
        response = self.client.post(reverse("logout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("home"))

    def test_logout_rejects_get_requests(self):
        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 405)

    def test_create_user_inserts_requested_values(self):
        response = self.client.post(
            reverse("user_list"),
            {
                "action": "create_user",
                "user_id": "EMP001",
                "name": "홍길동",
                "department": "개발팀",
                "position": "대리",
                "use_yn": YesNoChoices.NO,
            },
        )

        self.assertEqual(response.status_code, 302)

        created_user = User.objects.get(user_id="EMP001")
        self.assertEqual(created_user.sn, 2)
        self.assertEqual(created_user.name, "홍길동")
        self.assertEqual(created_user.department, "개발팀")
        self.assertEqual(created_user.position, "대리")
        self.assertEqual(created_user.sys_mngr_yn, YesNoChoices.NO)
        self.assertEqual(created_user.tmpr_pswd_yn, YesNoChoices.YES)
        self.assertEqual(created_user.use_yn, YesNoChoices.NO)
        self.assertTrue(created_user.check_password(TEMP_PASSWORD))

    def test_create_user_with_duplicate_user_id_shows_error(self):
        User.objects.create(
            sn=2,
            user_id="EMP001",
            password="abc1234",
            name="기존 사용자",
            sys_mngr_yn=YesNoChoices.NO,
            tmpr_pswd_yn=YesNoChoices.NO,
            use_yn=YesNoChoices.YES,
            created_by=self.admin,
            updated_by=self.admin,
        )

        response = self.client.post(
            reverse("user_list"),
            {
                "action": "create_user",
                "user_id": "EMP001",
                "name": "홍길동",
                "department": "개발팀",
                "position": "대리",
                "use_yn": YesNoChoices.YES,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(user_id="EMP001").count(), 1)
        self.assertTrue(response.context["open_user_create_modal"])
