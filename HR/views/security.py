from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render

from ..models import SecurityProfile
from ..services import audit


@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    for f in form.fields.values():
        f.widget.attrs['class'] = 'form-control'
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        SecurityProfile.objects.update_or_create(user=user, defaults={'must_change_password': False})
        audit.log('password.change', 'security', request=request, user=user)
        messages.success(request, "Password changed.")
        return redirect('/hr/')
    forced = SecurityProfile.objects.filter(user=request.user, must_change_password=True).exists()
    return render(request, 'hr/security.html', {'form': form, 'forced': forced})


@require_POST
def logout_view(request):
    """Ends the session AND clears the portal's JWT so the user is fully signed out."""
    from django.contrib.auth import logout
    from django.http import HttpResponse
    logout(request)
    return HttpResponse(
        "<!doctype html><meta charset='utf-8'><title>Signing out…</title><script>"
        "['ims_access','ims_refresh','ims_user'].forEach(k=>localStorage.removeItem(k));"
        "location.replace('/portal/login/');</script>")
