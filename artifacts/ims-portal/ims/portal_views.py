from django.shortcuts import render
from django.http import HttpResponse
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / 'static'


def portal_login_view(request):
    """Serve the branded login page."""
    login_html = (STATIC_DIR / 'pages-sign-in.html').read_text()
    return HttpResponse(login_html, content_type='text/html')


def portal_index_view(request):
    """Serve the main dashboard page (requires JS auth check)."""
    index_html = (STATIC_DIR / 'index.html').read_text()
    return HttpResponse(index_html, content_type='text/html')
