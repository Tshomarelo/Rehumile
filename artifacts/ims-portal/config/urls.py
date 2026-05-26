from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from ims.portal_views import portal_login_view, portal_index_view

urlpatterns = [
    # Django admin
    path('admin/', admin.site.urls),

    # API Schema & Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # JWT Token endpoints (standard simplejwt paths)
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # IMS REST API
    path('api/', include('ims.urls')),

    # Portal frontend: root redirects to login
    path('login/', portal_login_view, name='portal-login'),
    path('dashboard/', portal_index_view, name='portal-dashboard'),
    # Root redirects to login page
    path('', RedirectView.as_view(url='/portal/login/', permanent=False), name='portal-root'),
]
