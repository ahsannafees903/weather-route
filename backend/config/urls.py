"""Root URLconf. The planning API is POST /api/plan."""

from django.urls import path

from planner.views import health_view, plan_view

urlpatterns = [
    path("", health_view),
    path("api/plan", plan_view),
]
