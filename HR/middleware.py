from django.shortcuts import redirect

from .models import SecurityProfile

EXEMPT = ('/hr/security/', '/hr/file/')


class SecurityMiddleware:
    """Inside /hr/: a first-login password change is compulsory."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        user = getattr(request, 'user', None)
        if path.startswith('/hr/') and not path.startswith(EXEMPT) and user is not None and user.is_authenticated:
            if SecurityProfile.objects.filter(user=user, must_change_password=True).exists():
                return redirect('hr:password_change')
        return self.get_response(request)
