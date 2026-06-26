# Rehumile Portal IMS

A Django-based Inventory Management System portal for client management, ticketing, and billing.

## Project Structure

```
Rehumile_Portal_IMS/
├── config/                  # Django settings and WSGI configuration
├── ims/                     # Main Django application
│   ├── models.py           # Database models
│   ├── views.py            # View logic
│   ├── serializers.py      # DRF serializers
│   ├── urls.py             # URL routing
│   ├── admin.py            # Django admin config
│   └── migrations/         # Database migrations
├── src/                    # Frontend assets and source
│   ├── components/         # UI components
│   ├── scss/              # Stylesheets
│   ├── js/                # JavaScript
│   └── fonts/             # Font files
├── static/                # Compiled static files
├── staticfiles/           # Collected static files (production)
├── plan/                  # Project documentation
├── tests/                 # Test files
├── manage.py              # Django CLI
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
└── db.sqlite3            # SQLite database
```

## Prerequisites

- Python 3.11+
- pip or poetry

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd Rehumile_Portal_IMS
   ```

2. **Create and activate virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create environment file:**
   ```bash
   cp .env.example .env
   ```

5. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Create superuser:**
   ```bash
   python manage.py createsuperuser
   ```

7. **Run development server:**
   ```bash
   python manage.py runserver
   ```

Server will be available at `http://localhost:8000`

## Key Features

- **Client Management** - Manage client profiles and information
- **Ticketing System** - Create, track, and manage support tickets
- **Billing** - Client billing and invoice management
- **Authentication** - JWT-based authentication with DRF
- **API Documentation** - Auto-generated OpenAPI/Swagger docs

## Django Apps

- **ims** - Core inventory management system

## Configuration

- Django settings: `config/settings.py`
- URL routing: `config/urls.py` and `ims/urls.py`
- Database: SQLite (development) or PostgreSQL (production)

## API Endpoints

See `plan/API_ENDPOINTS.md` for complete API documentation.

## Database Schema

See `plan/DATABASE_SCHEMA.md` for database design documentation.

## Deployment

See `DEPLOY_PYTHONANYWHERE.md` for deployment instructions.

## Documentation

- `plan/README.md` - Project planning details
- `plan/TECHNICAL_ARCHITECTURE.md` - System architecture
- `plan/IMPLEMENTATION_GUIDE.md` - Implementation notes

## License

See LICENSE file for details.
