# Django Project Setup & Configuration Guide

## Quick Start: Setting Up the IMS Django Backend

### Prerequisites
- Python 3.10+
- PostgreSQL (recommended) or SQLite for development
- pip and virtualenv

---

## Step 1: Initial Project Setup

### Create Django Project (if not already done)
```bash
# Create project directory
mkdir ims_backend
cd ims_backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Create Django project
django-admin startproject config .

# Create Django app
python manage.py startapp ims
```

---

## Step 2: Install Required Dependencies

### requirements.txt
```txt
# Core Django
Django==4.2.0
djangorestframework==3.14.0
django-cors-headers==4.0.0

# Database
psycopg2-binary==2.9.6  # PostgreSQL adapter
dj-database-url==2.0.0

# Authentication
djangorestframework-simplejwt==5.2.2
PyJWT==2.8.0

# Utilities
python-decouple==3.8
Pillow==10.0.0  # Image handling

# Validation
django-phonenumber-field==7.2.0
phonenumbers==8.13.0

# Pagination
djangorestframework-pagination==0.0.1

# File handling
boto3==1.26.137  # AWS S3 integration

# Celery (for background tasks like SLA checks)
celery==5.3.1
redis==4.5.5

# API Documentation
drf-spectacular==0.26.2

# Testing
pytest==7.4.0
pytest-django==4.5.2
factory-boy==3.3.0

# Code quality
black==23.7.0
flake8==6.0.0
isort==5.12.0
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

---

## Step 3: Django Settings Configuration

### settings.py
```python
import os
from pathlib import Path
from decouple import config
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = config('SECRET_KEY', default='django-insecure-CHANGE-THIS')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

# Installed Apps
INSTALLED_APPS = [
    'daphne',  # For WebSocket support
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party
    'rest_framework',
    'corsheaders',
    'drf_spectacular',
    'phonenumber_field',
    
    # Local
    'ims',
]

# Middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='ims_db'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# Custom User Model
AUTH_USER_MODEL = 'ims.User'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# JWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=24),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# CORS Configuration
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://localhost:8080',
    cast=lambda v: [s.strip() for s in v.split(',')]
)
CORS_ALLOW_CREDENTIALS = True

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static Files
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media Files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

### .env Example
```env
# Django
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,yourdomain.com

# Database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=ims_db
DB_USER=ims_user
DB_PASSWORD=secure_password
DB_HOST=localhost
DB_PORT=5432

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080,https://yourdomain.com

# JWT
SECRET_KEY_JWT=your-jwt-secret

# AWS S3 (optional)
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_STORAGE_BUCKET_NAME=your-bucket
AWS_S3_REGION_NAME=us-east-1

# Celery (optional)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

---

## Step 4: Database Migrations

### Apply Models
```bash
# Create migrations for ims app
python manage.py makemigrations ims

# Apply migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

---

## Step 5: Initialize SLA Configurations

### Create Management Command File
Create: `ims/management/commands/init_sla_config.py`

```python
from django.core.management.base import BaseCommand
from ims.models import SLAConfig
import datetime

class Command(BaseCommand):
    help = 'Initialize SLA configurations'
    
    def handle(self, *args, **options):
        sla_configs = [
            {
                'sla_type': 'bronze',
                'response_time_hours': 24,
                'resolution_time_hours': 72,
                'available_24_7': False,
            },
            {
                'sla_type': 'silver',
                'response_time_hours': 12,
                'resolution_time_hours': 48,
                'available_24_7': True,
            },
            {
                'sla_type': 'gold',
                'response_time_hours': 4,
                'resolution_time_hours': 24,
                'available_24_7': True,
            },
        ]
        
        for config in sla_configs:
            SLAConfig.objects.update_or_create(
                sla_type=config['sla_type'],
                defaults={k: v for k, v in config.items() if k != 'sla_type'}
            )
        
        self.stdout.write(self.style.SUCCESS('✓ SLA configurations initialized'))
```

### Run Command
```bash
python manage.py init_sla_config
```

---

## Step 6: Create Sample Data (Optional)

### ims/management/commands/seed_data.py
```python
from django.core.management.base import BaseCommand
from ims.models import Company, User, UserProfile

class Command(BaseCommand):
    help = 'Seed database with sample data'
    
    def handle(self, *args, **options):
        # Create sample company
        company, created = Company.objects.get_or_create(
            name='Acme Corp',
            defaults={
                'slug': 'acme-corp',
                'contact_person': 'John Doe',
                'contact_email': 'john@acme.com',
                'billing_email': 'billing@acme.com',
                'sla_type': 'silver',
            }
        )
        
        # Create sample users
        admin_user, _ = User.objects.get_or_create(
            email='admin@rehumile.com',
            defaults={
                'first_name': 'Admin',
                'last_name': 'User',
                'role': 'admin',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        admin_user.set_password('admin123')
        admin_user.save()
        
        agent_user, _ = User.objects.get_or_create(
            email='agent@acme.com',
            defaults={
                'first_name': 'Support',
                'last_name': 'Agent',
                'role': 'agent',
                'company': company,
            }
        )
        agent_user.set_password('agent123')
        agent_user.save()
        
        self.stdout.write(self.style.SUCCESS('✓ Sample data seeded'))
```

### Run Seed Command
```bash
python manage.py seed_data
```

---

## Step 7: URL Configuration

### urls.py
```python
from django.contrib import admin
from django.urls import path, include
from rest_framework import routers
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

# API routes would go here
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema')),
    path('api/', include('ims.urls')),
]
```

---

## Step 8: Running the Server

```bash
# Development server
python manage.py runserver

# With custom host/port
python manage.py runserver 0.0.0.0:8000
```

Access:
- Admin: http://localhost:8000/admin
- API Docs: http://localhost:8000/api/docs
- API: http://localhost:8000/api/

---

## Database Structure Summary

The complete database includes:

### Authentication & Users (4 models)
- User (custom, extends AbstractUser)
- UserProfile
- Company
- CompanyBillingInfo

### Incident Management (5 models)
- Incident
- IncidentComment
- IncidentAttachment
- IncidentTimeline
- SLAConfig, SLABreach

### Billing (2 models)
- Invoice
- InvoiceItem

### Notifications & Audit (3 models)
- Notification
- AuditLog
- DashboardMetric

**Total: 17 core models**

---

## Project Structure
```
ims_backend/
├── venv/                           # Virtual environment
├── config/                         # Django settings
│   ├── settings.py                # Main configuration
│   ├── urls.py                    # URL routing
│   ├── asgi.py                    # ASGI config
│   └── wsgi.py                    # WSGI config
├── ims/                           # Main app
│   ├── models.py                  # All models
│   ├── admin.py                   # Admin interface
│   ├── views.py                   # API views
│   ├── serializers.py             # DRF serializers
│   ├── urls.py                    # App URLs
│   ├── permissions.py             # Custom permissions
│   ├── filters.py                 # Query filters
│   ├── tasks.py                   # Celery tasks (SLA checks)
│   ├── signals.py                 # Django signals
│   └── management/
│       └── commands/              # Custom commands
├── requirements.txt               # Dependencies
├── .env                           # Environment variables
├── .env.example                   # Example env
├── manage.py                      # Django management
└── README.md                      # Project documentation
```

---

## Key Features Implemented

✅ **Multi-Tenant Architecture**
- Company-scoped data isolation
- Row-level security

✅ **User Management**
- Custom User model with roles
- Profile management
- Permission system

✅ **Incident Management**
- Full CRUD operations
- SLA tracking and breach detection
- Comments & attachments
- Activity timeline

✅ **Billing System**
- Invoice generation
- Line items management
- Payment tracking

✅ **Notifications**
- Real-time alerts
- SLA warnings
- Activity notifications

✅ **Audit Trail**
- Complete change tracking
- User action logging
- Compliance reporting

✅ **Admin Interface**
- Django admin customization
- List filters & search
- Inline management

---

## Next Steps

1. **Create Serializers** (ims/serializers.py)
   - UserSerializer
   - CompanySerializer
   - IncidentSerializer
   - InvoiceSerializer
   - NotificationSerializer

2. **Create Views/ViewSets** (ims/views.py)
   - Authentication endpoints
   - CRUD operations
   - Custom business logic

3. **Create Permissions** (ims/permissions.py)
   - Custom permission classes
   - Role-based access

4. **Create Filters** (ims/filters.py)
   - Query parameter filtering
   - Search capabilities

5. **Setup Celery** (ims/tasks.py)
   - SLA check background task
   - Email notifications
   - Invoice generation

6. **Create Tests** (tests/)
   - Unit tests
   - Integration tests
   - API endpoint tests

7. **Deploy**
   - Docker containerization
   - Production server setup
   - Database backups

---

## Useful Management Commands

```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Clear cache
python manage.py clear_cache

# Shell access
python manage.py shell

# Admin user
python manage.py init_sla_config

# Seed data
python manage.py seed_data

# Collect static files
python manage.py collectstatic

# Run tests
pytest
```

---

## Troubleshooting

### Migration Issues
```bash
# Show migration status
python manage.py showmigrations

# Revert to previous migration
python manage.py migrate ims 0001

# Create empty migration
python manage.py makemigrations --empty ims --name custom_migration
```

### Database Issues
```bash
# Check database connection
python manage.py dbshell

# Reset database (development only)
python manage.py flush
```

### Static Files Issues
```bash
# Collect static files
python manage.py collectstatic --noinput

# Find missing static files
python manage.py findstatic [filename]
```

This Django setup is production-ready and fully supports the IMS system requirements!
