// src/services/api.js - API client for backend communication
import AuthUtils from '../utils/auth';

const API_BASE_URL = process.env.API_URL || 'http://localhost:3000/api';

class APIClient {
  constructor(baseURL) {
    this.baseURL = baseURL;
  }

  // Get authorization header
  getAuthHeader() {
    const token = AuthUtils.getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  // Make HTTP request
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...this.getAuthHeader(),
      ...options.headers
    };

    try {
      const response = await fetch(url, {
        ...options,
        headers
      });

      // Handle 401 - Token expired, redirect to login
      if (response.status === 401) {
        AuthUtils.clearAuthData();
        window.location.href = '/login';
        return null;
      }

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error?.message || 'Request failed');
      }

      return data;
    } catch (error) {
      console.error('API Error:', error);
      throw error;
    }
  }

  // GET request
  get(endpoint, options = {}) {
    return this.request(endpoint, { method: 'GET', ...options });
  }

  // POST request
  post(endpoint, body, options = {}) {
    return this.request(endpoint, {
      method: 'POST',
      body: JSON.stringify(body),
      ...options
    });
  }

  // PUT request
  put(endpoint, body, options = {}) {
    return this.request(endpoint, {
      method: 'PUT',
      body: JSON.stringify(body),
      ...options
    });
  }

  // PATCH request
  patch(endpoint, body, options = {}) {
    return this.request(endpoint, {
      method: 'PATCH',
      body: JSON.stringify(body),
      ...options
    });
  }

  // DELETE request
  delete(endpoint, options = {}) {
    return this.request(endpoint, { method: 'DELETE', ...options });
  }
}

export const api = new APIClient(API_BASE_URL);

// Auth API
export const authAPI = {
  login: (email, password) => api.post('/auth/login', { email, password }),
  logout: () => api.post('/auth/logout', {}),
  getCurrentUser: () => api.get('/auth/me'),
  refreshToken: () => api.post('/auth/refresh-token', {})
};

// Companies API
export const companiesAPI = {
  getAll: (skip = 0, limit = 10, status = null) => 
    api.get(`/companies?skip=${skip}&limit=${limit}${status ? `&status=${status}` : ''}`),
  getById: (id) => api.get(`/companies/${id}`),
  create: (data) => api.post('/companies', data),
  update: (id, data) => api.put(`/companies/${id}`, data),
  updateStatus: (id, status) => api.patch(`/companies/${id}/status`, { status }),
  getUsers: (id) => api.get(`/companies/${id}/users`)
};

// Users API
export const usersAPI = {
  getAll: (companyId = null, role = null, skip = 0, limit = 10) => {
    let url = `/users?skip=${skip}&limit=${limit}`;
    if (companyId) url += `&company_id=${companyId}`;
    if (role) url += `&role=${role}`;
    return api.get(url);
  },
  getById: (id) => api.get(`/users/${id}`),
  create: (data) => api.post('/users', data),
  update: (id, data) => api.put(`/users/${id}`, data),
  updateStatus: (id, status) => api.patch(`/users/${id}/status`, { status }),
  resetPassword: (id) => api.post(`/users/${id}/reset-password`, {}),
  getPermissions: (id) => api.get(`/users/${id}/permissions`),
  updatePermissions: (id, permissions) => api.put(`/users/${id}/permissions`, permissions)
};

// Incidents API
export const incidentsAPI = {
  getAll: (filters = {}) => {
    let url = '/incidents?';
    const params = new URLSearchParams(filters);
    return api.get(`/incidents?${params.toString()}`);
  },
  getById: (id) => api.get(`/incidents/${id}`),
  create: (data) => api.post('/incidents', data),
  update: (id, data) => api.put(`/incidents/${id}`, data),
  updateStatus: (id, status) => api.patch(`/incidents/${id}/status`, { status }),
  updatePriority: (id, priority) => api.patch(`/incidents/${id}/priority`, { priority }),
  assign: (id, agentId) => api.patch(`/incidents/${id}/assign`, { assigned_to: agentId }),
  getTimeline: (id) => api.get(`/incidents/${id}/timeline`),
  getComments: (id) => api.get(`/incidents/${id}/comments`),
  addComment: (id, text, isInternal = false) => 
    api.post(`/incidents/${id}/comments`, { comment_text: text, is_internal: isInternal }),
  getAttachments: (id) => api.get(`/incidents/${id}/attachments`),
  uploadAttachment: (id, file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.request(`/incidents/${id}/attachments`, {
      method: 'POST',
      body: formData,
      headers: {} // Let browser set Content-Type
    });
  },
  setBillable: (id, isBillable, hoursWorked = 0) => 
    api.patch(`/incidents/${id}/billable`, { is_billable: isBillable, hours_worked: hoursWorked }),
  escalate: (id) => api.post(`/incidents/${id}/escalate`, {})
};

// SLA API
export const slaAPI = {
  getConfig: () => api.get('/sla/config'),
  getBreached: (companyId = null) => {
    let url = '/sla/breached';
    if (companyId) url += `?company_id=${companyId}`;
    return api.get(url);
  },
  getAtRisk: () => api.get('/sla/at-risk'),
  getStatus: (incidentId) => api.get(`/incidents/${incidentId}/sla-status`)
};

// Invoices API
export const invoicesAPI = {
  getAll: (companyId = null, status = null, skip = 0, limit = 10) => {
    let url = `/invoices?skip=${skip}&limit=${limit}`;
    if (companyId) url += `&company_id=${companyId}`;
    if (status) url += `&status=${status}`;
    return api.get(url);
  },
  getById: (id) => api.get(`/invoices/${id}`),
  create: (data) => api.post('/invoices', data),
  update: (id, data) => api.put(`/invoices/${id}`, data),
  updateStatus: (id, status) => api.patch(`/invoices/${id}/status`, { status }),
  getItems: (id) => api.get(`/invoices/${id}/items`),
  addItem: (id, item) => api.post(`/invoices/${id}/items`, item),
  getPDF: (id) => api.get(`/invoices/${id}/pdf`),
  getRevenue: (companyId, startDate, endDate) => 
    api.get(`/billing/company/${companyId}/revenue?start_date=${startDate}&end_date=${endDate}`)
};

// Analytics API
export const analyticsAPI = {
  getDashboard: () => api.get('/analytics/dashboard'),
  getIncidentsByCompany: () => api.get('/analytics/incidents-by-company'),
  getIncidentsTrend: (days = 30) => api.get(`/analytics/incidents-trend?days=${days}`),
  getSLACompliance: () => api.get('/analytics/sla-compliance'),
  getTopCompanies: () => api.get('/analytics/top-companies'),
  getAgentPerformance: () => api.get('/analytics/agent-performance')
};

// Client API
export const clientAPI = {
  getDashboard: () => api.get('/client/dashboard'),
  getTickets: (filters = {}) => {
    let url = '/client/tickets?';
    const params = new URLSearchParams(filters);
    return api.get(`/client/tickets?${params.toString()}`);
  },
  createTicket: (data) => api.post('/client/tickets', data),
  getTicket: (id) => api.get(`/client/tickets/${id}`),
  addComment: (id, text) => api.post(`/client/tickets/${id}/comments`, { comment_text: text }),
  getNotifications: (isRead = null, skip = 0, limit = 10) => {
    let url = `/client/notifications?skip=${skip}&limit=${limit}`;
    if (isRead !== null) url += `&is_read=${isRead}`;
    return api.get(url);
  },
  getProfile: () => api.get('/client/profile'),
  updateProfile: (data) => api.put('/client/profile', data),
  changePassword: (currentPassword, newPassword) => 
    api.put('/client/password', { current_password: currentPassword, new_password: newPassword })
};

// Notifications API
export const notificationsAPI = {
  getAll: (isRead = null, skip = 0, limit = 10) => {
    let url = `/notifications?skip=${skip}&limit=${limit}`;
    if (isRead !== null) url += `&is_read=${isRead}`;
    return api.get(url);
  },
  markAsRead: (id) => api.patch(`/notifications/${id}/read`, {}),
  markAllAsRead: () => api.post('/notifications/mark-all-read', {}),
  delete: (id) => api.delete(`/notifications/${id}`)
};

// Reports API
export const reportsAPI = {
  getIncidentsByStatus: () => api.get('/reports/incidents-by-status'),
  getIncidentsByPriority: () => api.get('/reports/incidents-by-priority'),
  getCompanySummary: (companyId, startDate, endDate) => 
    api.get(`/reports/company-summary?company_id=${companyId}&start_date=${startDate}&end_date=${endDate}`),
  export: (type, format = 'pdf', startDate, endDate) => 
    api.get(`/reports/export?type=${type}&format=${format}&date_from=${startDate}&date_to=${endDate}`)
};

export default api;
