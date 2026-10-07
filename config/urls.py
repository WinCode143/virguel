from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from movil.views import encuesta
from tablero.exportar import exportar_csv
from tablero.views import raiz

urlpatterns = [
    path("", raiz, name="raiz"),
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("tablero/", include("tablero.urls")),
    path("app/", include("movil.urls")),
    path("encuesta/<uuid:token>/", encuesta, name="encuesta"),
    path("api/powerbi/<slug:dataset>.csv", exportar_csv, name="exportar_csv"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
