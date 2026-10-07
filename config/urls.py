from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views_cuenta
from core.autenticacion import FormularioIngreso
from movil.views import encuesta
from tablero.exportar import exportar_csv
from tablero.views import raiz

urlpatterns = [
    path("", raiz, name="raiz"),
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True,
                                                authentication_form=FormularioIngreso), name="login"),
    path("cuenta/clave/", views_cuenta.cambiar_clave, name="cambiar_clave"),
    path("cuenta/privacidad/", views_cuenta.privacidad, name="privacidad"),
    path("cuenta/recuperar/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("cuenta/recuperar/enviado/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("cuenta/recuperar/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(),
         name="password_reset_confirm"),
    path("cuenta/recuperar/listo/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("tablero/", include("tablero.urls")),
    path("personal/", include("personal.urls")),
    path("app/", include("movil.urls")),
    path("encuesta/<uuid:token>/", encuesta, name="encuesta"),
    path("api/powerbi/<slug:dataset>.csv", exportar_csv, name="exportar_csv"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
