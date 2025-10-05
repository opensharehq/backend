from django.urls import path

from .views import index

app_name = "homepage"

urlpatterns = [path("", index, name="index")]
