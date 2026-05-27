# Deploying Rehumile TMW to PythonAnywhere

This guide deploys the **entire project** (main website + IMS portal + quote form API) as a single Django web app on PythonAnywhere. No Node.js needed — the React frontend is pre-built to static files and served through Django.

---

## Architecture on PythonAnywhere

```
PythonAnywhere Web App (Django / WSGI)
├── /                 → React frontend (built static SPA)
├── /api/quote/       → Django quote request view (sends email)
├── /portal/login/    → IMS Portal login
├── /portal/...       → All IMS portal pages
├── /api/...          → REST API (JWT auth, incidents, invoices)
└── /static/          → All static files (WhiteNoise)
```

---

## Prerequisites

- A PythonAnywhere account (free tier works for the portal; paid plan needed for outbound SMTP)
- Git installed on PythonAnywhere (it is by default)
- Python 3.11 (select this when creating your web app)

---

## Step 1 — Upload the Project

Open a **Bash console** on PythonAnywhere and clone your repo:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git ~/rehumile
cd ~/rehumile
```

If you don't have the project on GitHub, use the **Files** tab to upload a zip, then unzip:

```bash
unzip rehumile.zip -d ~/rehumile
cd ~/rehumile
```

---

## Step 2 — Build the React Frontend

You need Node.js to build the frontend. PythonAnywhere provides it:

```bash
# Check node is available
node --version   # should print v18+ (free tier has it)

# Install pnpm if not present
npm install -g pnpm

# Install all workspace dependencies
cd ~/rehumile
pnpm install

# Build the React frontend
pnpm --filter @workspace/rehumile-tmw run build
```

The built files land in `artifacts/rehumile-tmw/dist/`.

---

## Step 3 — Copy the React Build into Django

Django will serve the React app as a single-page app. Copy the built files:

```bash
cd ~/rehumile

# Copy the built React dist into Django's template + static area
mkdir -p artifacts/ims-portal/frontend_dist
cp -r artifacts/rehumile-tmw/dist/. artifacts/ims-portal/frontend_dist/
```

Now add a catch-all URL and view to Django so it serves `index.html` for all unmatched routes.

Open `artifacts/ims-portal/config/urls.py` and add at the **bottom** of `urlpatterns`:

```python
# Add this import at the top of urls.py:
from django.views.generic import TemplateResponse
import os
from django.http import FileResponse, Http404
from django.conf import settings as conf_settings

# Add this view (paste above urlpatterns):
def serve_react(request, path=''):
    """Serve the React SPA index.html for all non-API, non-portal routes."""
    index = os.path.join(conf_settings.BASE_DIR, 'frontend_dist', 'index.html')
    if os.path.exists(index):
        return FileResponse(open(index, 'rb'), content_type='text/html')
    raise Http404

# Add at the BOTTOM of urlpatterns (must be last):
path('site/', serve_react, name='react-site'),
path('site/<path:path>', serve_react, name='react-site-path'),
# Or to serve from root, replace the RedirectView root entry with:
# re_path(r'^(?!portal/|api/|admin/|static/).*$', serve_react),
```

For a cleaner root-level setup, replace the existing root redirect in `urls.py`:

```python
# Replace this line:
path('', RedirectView.as_view(url='/portal/login/', permanent=False), name='portal-root'),

# With this (add re_path import at top):
from django.urls import path, include, re_path
re_path(r'^(?!portal/|api/|admin/|static/).*$', serve_react, name='react-root'),
```

---

## Step 4 — Update Django Settings for Production

```bash
cd ~/rehumile/artifacts/ims-portal
```

Edit `config/settings.py` and make these changes:

```python
# Change DEBUG to False in production
DEBUG = config('DEBUG', default='False', cast=bool)

# Add your PythonAnywhere domain
ALLOWED_HOSTS = ['yourusername.pythonanywhere.com', 'www.rehumile.co.za']

# Add frontend_dist to Django's template dirs so index.html is found
TEMPLATES[0]['DIRS'] = [BASE_DIR / 'frontend_dist']

# Static files — WhiteNoise serves everything from staticfiles/
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATIC_URL = '/static/'

# Tell WhiteNoise to also serve the React build's assets
WHITENOISE_ROOT = BASE_DIR / 'frontend_dist'
```

---

## Step 5 — Install Python Dependencies

```bash
cd ~/rehumile/artifacts/ims-portal

# Install all Python requirements into your home virtualenv
pip3 install --user -r requirements.txt
```

If there is no `requirements.txt`, generate one:

```bash
pip3 freeze > requirements.txt
# Or install manually:
pip3 install --user django gunicorn whitenoise djangorestframework \
    djangorestframework-simplejwt django-cors-headers django-filter \
    drf-spectacular python-decouple dj-database-url
```

---

## Step 6 — Set Environment Variables

On PythonAnywhere, go to **Web** tab → your web app → **Environment variables** section (or use a `.env` file):

Create `~/rehumile/artifacts/ims-portal/.env`:

```env
IMS_SECRET_KEY=your-long-random-secret-key-here
DEBUG=False
EMAIL_HOST=mail.rehumile.co.za
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreply@rehumile.co.za
EMAIL_HOST_PASSWORD=your-email-password-here
DEFAULT_FROM_EMAIL=noreply@rehumile.co.za
DATABASE_URL=sqlite:///db.sqlite3
```

Generate a secure secret key:

```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## Step 7 — Run Migrations and Collect Static Files

```bash
cd ~/rehumile/artifacts/ims-portal
export DJANGO_SETTINGS_MODULE=config.settings

python3 manage.py migrate --noinput
python3 manage.py seed_admin
python3 manage.py collectstatic --noinput --clear
```

---

## Step 8 — Configure the PythonAnywhere Web App

1. Go to **Web** tab on PythonAnywhere → **Add a new web app**
2. Choose **Manual configuration** → **Python 3.11**
3. Set the **Source code** directory: `/home/yourusername/rehumile/artifacts/ims-portal`
4. Set the **Working directory**: `/home/yourusername/rehumile/artifacts/ims-portal`

### WSGI File

Click **WSGI configuration file** link and replace its entire contents with:

```python
import os
import sys

# Add the project to sys.path
project_home = '/home/yourusername/rehumile/artifacts/ims-portal'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Load .env before Django starts
from decouple import config as decouple_config  # noqa

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### Static Files Mapping

In the **Static files** section of the Web tab, add:

| URL       | Directory                                                         |
|-----------|-------------------------------------------------------------------|
| `/static/`| `/home/yourusername/rehumile/artifacts/ims-portal/staticfiles/`   |

---

## Step 9 — Add the Quote URL to Django

The quote endpoint is already wired in `config/urls.py`. Confirm it's there:

```python
# In config/urls.py — this line should already exist:
path('api/quote/', quote_request_view, name='quote-request'),
```

If it's missing, add it inside `urlpatterns`.

---

## Step 10 — Reload and Test

1. Click **Reload** on the Web tab
2. Visit `https://yourusername.pythonanywhere.com/portal/login/` — IMS portal should load
3. Visit `https://yourusername.pythonanywhere.com/` — React website should load
4. Test the quote form — submission should email `infor@rehumile.co.za`

---

## Custom Domain (optional)

1. Go to **Web** tab → **Add a custom domain**: `www.rehumile.co.za`
2. PythonAnywhere will show you a **CNAME value** to add in your DNS (at your domain registrar)
3. Add the CNAME record, wait for DNS propagation (up to 48 hrs)
4. Enable **HTTPS** (free Let's Encrypt certificate) with one click

---

## Updating the Site

Every time you make changes:

```bash
cd ~/rehumile
git pull                                          # get latest code
pnpm --filter @workspace/rehumile-tmw run build   # rebuild React if frontend changed
cp -r artifacts/rehumile-tmw/dist/. artifacts/ims-portal/frontend_dist/
cd artifacts/ims-portal
python3 manage.py migrate --noinput               # run any new migrations
python3 manage.py collectstatic --noinput --clear # re-collect static files
```

Then click **Reload** on the PythonAnywhere Web tab.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| 502 Bad Gateway | Check the **Error log** in the Web tab — usually a missing package or bad WSGI path |
| Static files 404 | Re-run `collectstatic` and verify the static files mapping in the Web tab |
| Email not sending | PythonAnywhere free tier **blocks outbound SMTP**. Upgrade to a paid plan or use a relay like SendGrid/Mailgun on port 587 |
| `IMS_SECRET_KEY` error | Make sure your `.env` file is in `artifacts/ims-portal/` and `python-decouple` is installed |
| React app shows blank | Check browser console — usually a base path issue. Verify `WHITENOISE_ROOT` points to `frontend_dist/` |
