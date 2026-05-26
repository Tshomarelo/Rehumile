# IMS Technical Architecture

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Layer (React)                      │
│  ┌────────────┬──────────────┬──────────────┬───────────┐   │
│  │  Login    │  Dashboard   │ Companies    │ Incidents │   │
│  ├────────────┼──────────────┼──────────────┼───────────┤   │
│  │  Users    │  Billing     │  Reports     │   SLA     │   │
│  └────────────┴──────────────┴──────────────┴───────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            API Client Layer                          │   │
│  │  ├─ Authentication Service                           │   │
│  │  ├─ Companies API                                    │   │
│  │  ├─ Users API                                        │   │
│  │  ├─ Incidents API                                    │   │
│  │  ├─ Billing API                                      │   │
│  │  └─ Analytics API                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            State Management (Hooks)                  │   │
│  │  ├─ useAuth (Authentication state)                   │   │
│  │  ├─ useFetch (Data fetching with caching)            │   │
│  │  └─ localStorage (Persistent state)                  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                         │
                    HTTP / REST
                         │
┌─────────────────────────────────────────────────────────────┐
│                    Backend API Layer                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Express.js / Node.js Server               │   │
│  │  ├─ Authentication Routes (JWT)                      │   │
│  │  ├─ Companies Routes (CRUD)                          │   │
│  │  ├─ Users Routes (CRUD)                              │   │
│  │  ├─ Incidents Routes (CRUD + workflows)              │   │
│  │  ├─ Billing Routes (Invoicing)                       │   │
│  │  └─ Analytics Routes (KPIs)                          │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Middleware Layer                          │   │
│  │  ├─ Authentication (JWT verification)                │   │
│  │  ├─ Authorization (Role checking)                    │   │
│  │  ├─ Error Handling                                   │   │
│  │  ├─ Request Logging                                  │   │
│  │  └─ CORS Configuration                               │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Business Logic Layer                      │   │
│  │  ├─ Authentication Service                           │   │
│  │  ├─ Company Service                                  │   │
│  │  ├─ User Service                                     │   │
│  │  ├─ Incident Service (with SLA logic)                │   │
│  │  ├─ Billing Service (with invoice generation)        │   │
│  │  ├─ Notification Service                             │   │
│  │  └─ Analytics Service                                │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Database Layer                            │   │
│  │  ├─ ORM (Sequelize / TypeORM)                         │   │
│  │  ├─ Query Builder                                    │   │
│  │  └─ Database Connection Pool                         │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                         │
                    SQL / TCP
                         │
         ┌───────────────────────────────┐
         │   PostgreSQL Database         │
         │  (Multi-tenant architecture)  │
         └───────────────────────────────┘
```

## Component Architecture Diagram

```
App.js (Main Router)
│
├── Login Route
│   └── Login Component
│       ├── useAuth Hook
│       └── authAPI.login()
│
├── Protected Routes (with Navigation Sidebar)
│   │
│   ├── Dashboard Route
│   │   ├── MainDashboard Component
│   │   ├── useFetch (analyticsAPI)
│   │   └── KPI Cards, Charts, Quick Actions
│   │
│   ├── Companies Route
│   │   ├── CompaniesList Component
│   │   ├── useFetch (companiesAPI.getAll)
│   │   ├── Company Table with Pagination
│   │   ├── Create/Edit Modal
│   │   └── useFetch (companiesAPI.getUsers)
│   │
│   ├── Users Route
│   │   ├── UsersList Component
│   │   ├── useFetch (usersAPI.getAll)
│   │   ├── User Table with Filters
│   │   └── Create/Edit/Reset Password
│   │
│   ├── Incidents Route
│   │   ├── IncidentsList Component
│   │   ├── useFetch (incidentsAPI.getAll)
│   │   ├── Incident Table with Filters
│   │   ├── IncidentDetailModal
│   │   │   ├── Comments Section
│   │   │   ├── Attachments
│   │   │   └── Status/Priority Update
│   │   └── SLA Status Highlight
│   │
│   ├── Billing Route
│   │   ├── InvoicesList Component
│   │   ├── useFetch (invoicesAPI.getAll)
│   │   ├── Invoice Table
│   │   ├── Create Invoice Modal
│   │   └── Download PDF Button
│   │
│   ├── SLA Route
│   │   ├── SLAStatus Component
│   │   ├── Breached Incidents Tab
│   │   ├── At-Risk Incidents Tab
│   │   └── Alert Cards
│   │
│   └── Navigation Sidebar
│       ├── Logo
│       ├── Menu Items (role-based)
│       ├── User Profile Section
│       └── Logout Button
│
└── Global State
    ├── Authentication (useAuth)
    └── Local Storage (Token, User Data)
```

## Data Flow

### 1. Authentication Flow
```
User Login
    │
    ├─→ Login Component collects email/password
    │
    ├─→ authAPI.login() called
    │
    ├─→ Backend validates credentials
    │
    ├─→ JWT token generated
    │
    ├─→ AuthUtils.setAuthData(token, user)
    │
    ├─→ Stored in localStorage
    │
    └─→ Navigate to /dashboard
```

### 2. Data Fetching Flow
```
Component Mounts
    │
    ├─→ useFetch Hook initialized
    │
    ├─→ API call with auth header
    │
    ├─→ Loading state set to true
    │
    ├─→ Backend returns data
    │
    ├─→ Data stored in component state
    │
    ├─→ Loading state set to false
    │
    └─→ Component re-renders with data
```

### 3. Incident Management Flow
```
Support Agent creates incident
    │
    ├─→ POST /api/incidents with details
    │
    ├─→ Backend generates ticket ID
    │
    ├─→ SLA deadline calculated based on priority + SLA type
    │
    ├─→ Incident created in database
    │
    ├─→ HQ admin receives notification
    │
    ├─→ HQ admin can assign to agent
    │
    ├─→ Agent updates status/adds comments
    │
    └─→ Auto-check SLA breach every 5 minutes
```

### 4. Billing Flow
```
Month End
    │
    ├─→ Finance role creates invoice
    │
    ├─→ System aggregates incidents for company
    │
    ├─→ Calculate hours worked + ticket count
    │
    ├─→ Apply SLA-based pricing
    │
    ├─→ Generate invoice with line items
    │
    ├─→ Change status Draft → Sent
    │
    ├─→ Generate PDF
    │
    └─→ Mark as Paid when payment received
```

## User Roles & Permissions

### 1. Headquarters Admin
- **Access**: All features
- **Permissions**:
  - Manage all companies (create, edit, deactivate)
  - Manage all users (create, edit, reset password)
  - View all incidents across all companies
  - Assign incidents to agents
  - Create and manage invoices
  - View all analytics and reports
  - Access SLA monitoring
  - System administration

### 3. Support Agent
- **Access**: Incidents, Dashboard
- **Permissions**:
  - View incidents for assigned company
  - Update incident status/priority
  - Add comments (internal & client-visible)
  - Upload attachments
  - Update hours worked
  - View SLA status
  - Cannot: Create companies, manage users, access billing

### 4. Finance/Billing
- **Access**: Billing, Reports, Dashboard
- **Permissions**:
  - Create and edit invoices
  - Manage invoice status
  - Download invoices as PDF
  - View revenue analytics
  - Generate billing reports
  - Cannot: Manage companies, manage users, manage incidents

### 5. Client
- **Access**: Dashboard, Tickets, Billing, Profile
- **Permissions**:
  - View company dashboard with own statistics
  - Create new incidents
  - View and comment on own company's tickets
  - View invoices for their company
  - Download PDF invoices
  - Update own profile
  - Cannot: Access admin features, manage users, view other companies

### 6. Viewer (Future Role)
- **Access**: Dashboard, Reports (read-only)
- **Permissions**:
  - View analytics
  - View reports
  - Cannot: Create/edit anything

## SLA Logic

### SLA Types & Response Times
```
Bronze:
  - Response Time: 24 hours
  - Resolution Time: 72 hours
  - Available: 8:00 - 17:00 (Business hours)

Silver:
  - Response Time: 12 hours
  - Resolution Time: 48 hours
  - Available: 24/7

Gold:
  - Response Time: 4 hours
  - Resolution Time: 24 hours
  - Available: 24/7
```

### SLA Calculation
```
When incident created:
1. Get priority level
2. Get company's SLA type
3. Calculate deadline = current_time + response_time
4. Set sla_deadline in database

Every 5 minutes:
1. Check all open incidents
2. If current_time > sla_deadline AND status != closed
   - Set sla_breached = true
   - Create notification for HQ admin
   - Highlight in incident list
```

## API Response Format

### Success Response (200 OK)
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "name": "Company Name",
    ...
  },
  "message": "Operation successful"
}
```

### Error Response (400/500)
```json
{
  "success": false,
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Email already exists"
  }
}
```

### Paginated Response
```json
{
  "success": true,
  "data": [...],
  "total": 100,
  "skip": 0,
  "limit": 10
}
```

## Security Implementation

### Authentication Flow
```
1. User logs in with email/password
2. Backend validates against bcrypt hash
3. JWT token generated (exp: 24 hours)
4. Token stored in localStorage
5. Every API request includes: Authorization: Bearer {token}
6. Backend verifies token signature
7. On 401: Client redirects to login
```

### Authorization Levels
```
Public:
  - /login

Protected (Any authenticated user):
  - /dashboard
  - /incidents (users see their company only)

Admin Only:
  - /companies
  - /users
  - /sla
  - System settings

Finance Only:
  - /billing
  - Revenue reports
```

## Database Multi-Tenancy

### Data Isolation Strategy
```
1. Every user has company_id
2. Every incident, invoice belongs to company
3. Queries automatically filtered by company_id
4. Row-level security enforced in backend

User login:
- Retrieve company_id from user record
- Store in auth state
- Pass to all queries

Example query:
SELECT * FROM incidents WHERE company_id = ? AND status = 'open'
```

## Performance Considerations

### Frontend
- Lazy load modal components
- Use pagination for large lists
- Cache API responses for 5 minutes
- Implement virtual scrolling for 1000+ items

### Backend
- Index on frequently queried columns
- Use database connection pooling
- Implement caching layer (Redis)
- Optimize SLA check query

### Network
- Gzip compression
- Minify JS/CSS
- CDN for static assets
- HTTP/2 push

## Error Handling Strategy

### Frontend Error Handling
```javascript
try {
  const data = await api.post('/companies', formData);
  // Success
} catch (error) {
  if (error.response?.status === 401) {
    // Redirect to login
  } else if (error.response?.status === 403) {
    // Permission denied
  } else {
    // Show error message to user
  }
}
```

### Backend Error Handling
```javascript
app.use((err, req, res, next) => {
  // Log error
  console.error(err);
  
  // Return appropriate status code
  const status = err.status || 500;
  const message = err.message || 'Internal server error';
  
  res.status(status).json({
    success: false,
    error: { code: err.code, message }
  });
});
```

## Monitoring & Logging

### Frontend Logging
- Track API errors
- Monitor component render times
- Log user actions (optional)

### Backend Logging
- API request/response logging
- Database query logging
- Error stack traces
- Performance metrics

### Monitoring Tools (Recommended)
- Sentry for error tracking
- DataDog for performance monitoring
- CloudWatch for logs
- New Relic for application metrics
