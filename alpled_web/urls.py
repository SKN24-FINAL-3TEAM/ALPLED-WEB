"""
URL configuration for alpled_web project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path

from common.views import set_current_project_view
from docs.views import document_history_list
from files.views import file_list
from projects.views import project_list
from users.views import user_list

urlpatterns = [
    path("", user_list, name="home"),
    path("users/", user_list, name="user_list"),
    path("projects/", project_list, name="project_list"),
    path("files/", file_list, name="file_list"),
    path("docs/history/", document_history_list, name="doc_history_list"),
    path("projects/current/", set_current_project_view, name="set_current_project"),
    path('admin/', admin.site.urls),
]
