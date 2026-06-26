# IMS Database Schema

## Tables

### 1. Users
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  first_name VARCHAR(100),
  last_name VARCHAR(100),
  role ENUM('admin', 'agent', 'finance', 'viewer', 'client') NOT NULL,
  company_id UUID NOT NULL REFERENCES companies(id),
  status ENUM('active', 'inactive', 'suspended') DEFAULT 'active',
  permissions JSON,
  last_login TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2. Companies
```sql
CREATE TABLE companies (
  id UUID PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  contact_person VARCHAR(255),
  contact_email VARCHAR(255) NOT NULL,
  contact_phone VARCHAR(20),
  sla_type ENUM('bronze', 'silver', 'gold') DEFAULT 'silver',
  billing_email VARCHAR(255),
  billing_address TEXT,
  status ENUM('active', 'inactive') DEFAULT 'active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3. Incidents
```sql
CREATE TABLE incidents (
  id UUID PRIMARY KEY,
  ticket_id VARCHAR(20) UNIQUE NOT NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  category ENUM('hardware', 'software', 'network', 'other') DEFAULT 'other',
  company_id UUID NOT NULL REFERENCES companies(id),
  submitted_by UUID NOT NULL REFERENCES users(id),
  assigned_to UUID REFERENCES users(id),
  status ENUM('open', 'in_progress', 'resolved', 'closed') DEFAULT 'open',
  priority ENUM('low', 'medium', 'high', 'critical') DEFAULT 'medium',
  sla_deadline TIMESTAMP,
  sla_breached BOOLEAN DEFAULT FALSE,
  is_billable BOOLEAN DEFAULT TRUE,
  hours_worked DECIMAL(10, 2),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4. Incident_Comments
```sql
CREATE TABLE incident_comments (
  id UUID PRIMARY KEY,
  incident_id UUID NOT NULL REFERENCES incidents(id),
  author_id UUID NOT NULL REFERENCES users(id),
  comment_text TEXT NOT NULL,
  is_internal BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5. Incident_Attachments
```sql
CREATE TABLE incident_attachments (
  id UUID PRIMARY KEY,
  incident_id UUID NOT NULL REFERENCES incidents(id),
  file_name VARCHAR(255),
  file_path VARCHAR(500),
  file_size INT,
  uploaded_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 6. Invoices
```sql
CREATE TABLE invoices (
  id UUID PRIMARY KEY,
  invoice_number VARCHAR(50) UNIQUE NOT NULL,
  company_id UUID NOT NULL REFERENCES companies(id),
  billing_period_start DATE NOT NULL,
  billing_period_end DATE NOT NULL,
  total_amount DECIMAL(15, 2),
  ticket_count INT,
  hours_worked DECIMAL(10, 2),
  status ENUM('draft', 'sent', 'paid', 'overdue') DEFAULT 'draft',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_invoices_company ON invoices(company_id);
CREATE INDEX idx_invoices_status ON invoices(status);
```

### 7. Invoice_Items
```sql
CREATE TABLE invoice_items (
  id UUID PRIMARY KEY,
  invoice_id UUID NOT NULL REFERENCES invoices(id),
  incident_id UUID REFERENCES incidents(id),
  description VARCHAR(255),
  quantity DECIMAL(10, 2),
  unit_price DECIMAL(10, 2),
  amount DECIMAL(15, 2),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 8. Notifications
```sql
CREATE TABLE notifications (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  type ENUM('sla_warning', 'new_incident', 'assignment', 'invoice', 'general') NOT NULL,
  title VARCHAR(255),
  message TEXT,
  related_incident_id UUID REFERENCES incidents(id),
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9. SLA_Config
```sql
CREATE TABLE sla_config (
  id UUID PRIMARY KEY,
  sla_type ENUM('bronze', 'silver', 'gold') NOT NULL,
  response_time_hours INT,
  resolution_time_hours INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Indexes
- incidents(company_id, status, priority)
- incidents(sla_breached, sla_deadline)
- users(company_id, role)
- invoices(company_id, status)
- notifications(user_id, is_read)
