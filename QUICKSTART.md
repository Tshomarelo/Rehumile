# Development Commands

## Initial Setup
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

## Running the Server
```bash
# Development server
python manage.py runserver

# Run on specific port
python manage.py runserver 0.0.0.0:8000
```

## Database
```bash
# Make migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# See migration status
python manage.py showmigrations
```

## Static Files
```bash
# Collect static files
python manage.py collectstatic

# Collect without prompting
python manage.py collectstatic --noinput
```

## Admin
```bash
# Create superuser
python manage.py createsuperuser

# Access admin at: http://localhost:8000/admin/
```

## Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ims

# Run specific test file
pytest tests/test_models.py
```

## Shell
```bash
# Django interactive shell
python manage.py shell

# Example usage:
# >>> from ims.models import Client
# >>> Client.objects.all()
```
