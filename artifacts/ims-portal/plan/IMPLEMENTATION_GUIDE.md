# IMS Headquarters Dashboard - Implementation Guide

## Overview
This document provides a comprehensive guide to implement the Headquarters (Admin) Dashboard for the ITIL Incident Management System.

## Project Structure
```
src/
├── components/
│   ├── Auth/
│   │   ├── Login.js          # Login page component
│   │   └── Login.scss        # Login styling
│   ├── Dashboard/
│   │   ├── MainDashboard.js  # Main dashboard with KPIs
│   │   └── Dashboard.scss    # Dashboard styling
│   ├── Sidebar/
│   │   ├── Navigation.js     # Sidebar navigation
│   │   └── Sidebar.scss      # Sidebar styling
│   ├── Companies/
│   │   ├── CompaniesList.js  # Companies management
│   │   └── Companies.scss
│   ├── Users/
│   │   ├── UsersList.js      # User management
│   │   └── Users.scss
│   ├── Incidents/
│   │   ├── IncidentsList.js  # Central incident view
│   │   └── Incidents.scss
│   ├── Billing/
│   │   ├── InvoicesList.js   # Billing management
│   │   └── Billing.scss
│   └── Reports/
│       ├── SLAStatus.js      # SLA tracking
│       └── Reports.scss
├── services/
│   └── api.js               # API client with all endpoints
├── hooks/
│   ├── useAuth.js           # Authentication hook
│   └── useFetch.js          # Data fetching hook
└── utils/
    └── auth.js              # Auth utilities
```

## Component Architecture

### 1. Authentication Flow
- **Login Component**: User enters credentials
- **useAuth Hook**: Manages auth state and persists token to localStorage
- **Protected Routes**: Redirect unauthenticated users to login
- **Role-Based Access**: Components check user role for visibility

```javascript
// Usage example
const { user, login, logout, isAdmin } = useAuth();

if (isAdmin()) {
  // Show admin features
}
```

### 2. Data Fetching Pattern
- **useFetch Hook**: Handles API calls with loading/error states
- **API Service**: Centralized API client with all endpoints
- **Automatic Refetch**: Triggered on component mount and dependency changes

```javascript
const { data, loading, error, refetch } = useFetch(
  () => companiesAPI.getAll(),
  []
);
```

### 3. Component Hierarchy
```
App
├── Router
│   ├── /login → Login
│   ├── /dashboard → MainDashboard
│   ├── /companies → CompaniesList
│   ├── /users → UsersList
│   ├── /incidents → IncidentsList
│   ├── /billing → InvoicesList
│   └── /sla → SLAStatus
└── Layout (includes Navigation Sidebar)
```

## Installation & Setup

### 1. Backend Setup
```bash
# Install Node.js dependencies
npm install

# Create .env file
API_URL=http://localhost:3000/api
JWT_SECRET=your_secret_key
DATABASE_URL=postgresql://user:password@localhost:5432/ims_db

# Initialize database
npm run db:migrate

# Seed sample data (optional)
npm run db:seed
```

### 2. Frontend Setup
```bash
# Update package.json with required dependencies
npm install react-router-dom jwt-decode

# Configure API endpoint in src/services/api.js
// Change this line:
const API_BASE_URL = process.env.API_URL || 'http://localhost:3000/api';
```

### 3. Create Main App Component
```javascript
// src/App.js
import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import Login from './components/Auth/Login';
import Navigation from './components/Sidebar/Navigation';
import MainDashboard from './components/Dashboard/MainDashboard';
import CompaniesList from './components/Companies/CompaniesList';
import UsersList from './components/Users/UsersList';
import IncidentsList from './components/Incidents/IncidentsList';
import InvoicesList from './components/Billing/InvoicesList';
import SLAStatus from './components/Reports/SLAStatus';

function ProtectedRoute({ children }) {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? children : <Navigate to="/login" />;
}

function App() {
  const { isAuthenticated } = useAuth();

  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        
        <Route element={isAuthenticated && <Navigation />}>
          <Route path="/dashboard" element={<ProtectedRoute><MainDashboard /></ProtectedRoute>} />
          <Route path="/companies" element={<ProtectedRoute><CompaniesList /></ProtectedRoute>} />
          <Route path="/users" element={<ProtectedRoute><UsersList /></ProtectedRoute>} />
          <Route path="/incidents" element={<ProtectedRoute><IncidentsList /></ProtectedRoute>} />
          <Route path="/billing" element={<ProtectedRoute><InvoicesList /></ProtectedRoute>} />
          <Route path="/sla" element={<ProtectedRoute><SLAStatus /></ProtectedRoute>} />
        </Route>

        <Route path="*" element={<Navigate to="/dashboard" />} />
      </Routes>
    </Router>
  );
}

export default App;
```

## API Integration

### Authentication
```javascript
// Login
const response = await authAPI.login('admin@hq.com', 'password');
// Response: { token, user: { id, email, role, company_id } }

// Get current user
const user = await authAPI.getCurrentUser();

// Logout
await authAPI.logout();
```

### Companies Management
```javascript
// Get all companies
const companies = await companiesAPI.getAll(skip, limit, status);

// Create company
await companiesAPI.create({
  name: 'Tech Corp',
  contact_person: 'John Doe',
  contact_email: 'john@techcorp.com',
  sla_type: 'gold'
});

// Update company
await companiesAPI.update(companyId, { name: 'Updated Name' });

// Get company users
const users = await companiesAPI.getUsers(companyId);
```

### Users Management
```javascript
// Get all users
const users = await usersAPI.getAll(companyId, role, skip, limit);

// Create user
await usersAPI.create({
  email: 'agent@company.com',
  first_name: 'John',
  last_name: 'Agent',
  role: 'agent',
  company_id: companyId
});

// Reset password
await usersAPI.resetPassword(userId);
```

### Incidents Management
```javascript
// Get incidents with filters
const incidents = await incidentsAPI.getAll({
  status: 'open',
  priority: 'high',
  company_id: companyId,
  skip: 0,
  limit: 20
});

// Assign incident
await incidentsAPI.assign(incidentId, agentId);

// Add comment
await incidentsAPI.addComment(incidentId, 'Comment text', isInternal);

// Update status
await incidentsAPI.updateStatus(incidentId, 'in_progress');
```

### Billing Management
```javascript
// Create invoice
await invoicesAPI.create({
  company_id: companyId,
  billing_period_start: '2026-01-01',
  billing_period_end: '2026-01-31'
});

// Update invoice status
await invoicesAPI.updateStatus(invoiceId, 'sent');

// Download PDF
await invoicesAPI.getPDF(invoiceId);
```

## Styling Guide

### Color Scheme
- **Primary**: #007bff (Blue)
- **Success**: #28a745 (Green)
- **Danger**: #dc3545 (Red)
- **Warning**: #ffc107 (Yellow)
- **Info**: #17a2b8 (Cyan)
- **Secondary**: #6c757d (Gray)

### Component Sizing
- **Sidebar Width**: 250px (collapsible to 70px)
- **Modal Max Width**: 500px (700px for large modals)
- **KPI Card Grid**: 6 columns (auto-fit)
- **Padding**: 1rem, 1.5rem, 2rem

### Responsive Breakpoints
- **Desktop**: No changes
- **Tablet**: Sidebar collapses, grid adjusts
- **Mobile**: Sidebar hidden, full width content

## Security Best Practices

1. **JWT Token Management**
   - Store tokens in localStorage (consider httpOnly cookies for production)
   - Validate token expiration
   - Auto-logout on 401 responses

2. **API Security**
   - Always include Authorization header with token
   - HTTPS in production
   - CORS configuration on backend

3. **Input Validation**
   - Validate emails, phone numbers
   - Sanitize text inputs
   - Prevent XSS attacks

4. **Role-Based Access**
   - Check user role on components
   - Restrict API endpoints by role
   - Hide sensitive actions for non-admin users

## Testing Checklist

### Authentication
- [ ] Login with valid credentials
- [ ] Reject login with invalid credentials
- [ ] Token persists across page refresh
- [ ] Logout clears token
- [ ] Redirect to login on 401 error

### Dashboard
- [ ] KPI cards display correctly
- [ ] Charts render properly
- [ ] Quick actions navigate correctly
- [ ] Responsive on mobile/tablet

### Companies
- [ ] List all companies with pagination
- [ ] Search/filter works
- [ ] Create company modal appears
- [ ] Update company details
- [ ] Toggle active/inactive status
- [ ] View company users

### Users
- [ ] List all users with role filter
- [ ] Create new user
- [ ] Edit user details
- [ ] Reset password sends email
- [ ] Activate/deactivate user
- [ ] Role-based visibility

### Incidents
- [ ] List incidents with all filters
- [ ] Assign incident to agent
- [ ] Update incident status/priority
- [ ] Add internal/client comments
- [ ] Upload attachments
- [ ] Mark as billable

### Billing
- [ ] Create invoice for company
- [ ] Add invoice items
- [ ] Update invoice status
- [ ] Download invoice as PDF
- [ ] View revenue reports

### SLA
- [ ] Display breached incidents
- [ ] Display at-risk incidents
- [ ] Show SLA deadlines
- [ ] Escalate incident functionality

## Performance Optimization

1. **Code Splitting**
   - Lazy load route components
   - Use React.lazy() for modal content

2. **Data Caching**
   - Cache company/user lists
   - Invalidate cache on mutations

3. **Pagination**
   - Load 10-20 items per page
   - Implement virtual scrolling for large lists

4. **Image Optimization**
   - Use compressed avatars
   - Lazy load images

## Deployment

### Build
```bash
npm run build
```

### Environment Variables
Create `.env` file with:
```
REACT_APP_API_URL=https://api.yourdomain.com
REACT_APP_ENVIRONMENT=production
```

### Hosting
- Deploy to AWS S3 + CloudFront
- Or Netlify/Vercel for simplicity
- Ensure CORS is configured

## Troubleshooting

### Common Issues

1. **401 Unauthorized**
   - Token expired: Implement token refresh
   - Missing header: Check API client

2. **CORS Errors**
   - Backend CORS config incorrect
   - Missing credentials in fetch options

3. **Data not loading**
   - API endpoint incorrect
   - Network tab shows 404/500
   - Check error handling in useFetch

4. **Styling issues**
   - SCSS files not imported
   - Class names mismatched
   - CSS specificity conflicts

## Next Steps

1. Set up backend API server (Node.js/Express or Django/FastAPI)
2. Implement database with provided schema
3. Create authentication middleware
4. Test all API endpoints
5. Deploy frontend and backend
6. Set up monitoring and logging
7. Configure email for password resets
8. Implement PDF generation for invoices
