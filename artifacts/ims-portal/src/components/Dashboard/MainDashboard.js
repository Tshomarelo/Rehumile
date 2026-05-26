// src/components/Dashboard/MainDashboard.js - Main dashboard with KPIs and real-time enhancements
import React, { useState, useEffect } from 'react';
import { analyticsAPI, incidentsAPI, slaAPI, notificationsAPI } from '../../services/api';
import useFetch from '../../hooks/useFetch';
import './Dashboard.scss';

const MainDashboard = () => {
  const { data: analytics, loading: analyticsLoading, error: analyticsError, refetch: refetchAnalytics } = useFetch(
    () => analyticsAPI.getDashboard(),
    []
  );

  const { data: incidentsTrend, loading: trendLoading, refetch: refetchTrend } = useFetch(
    () => analyticsAPI.getIncidentsTrend(30),
    []
  );

  const { data: topCompanies, loading: companiesLoading, refetch: refetchCompanies } = useFetch(
    () => analyticsAPI.getTopCompanies(),
    []
  );

  const { data: atRiskIncidents, loading: atRiskLoading, error: atRiskError, refetch: refetchAtRisk } = useFetch(
    () => slaAPI.getAtRisk(),
    []
  );

  const { data: recentNotifications, loading: notificationsLoading, error: notificationsError } = useFetch(
    () => notificationsAPI.getAll(false, 0, 5), // Get 5 unread notifications
    []
  );

  const [lastUpdated, setLastUpdated] = useState(null);
  const [timeLeft, setTimeLeft] = useState('');

  // Format time left for SLA breach
  const formatTimeLeft = (deadline) => {
    if (!deadline) return '';
    const now = new Date();
    const deadlineDate = new Date(deadline);
    const diffMs = deadlineDate - now;
    
    if (diffMs <= 0) return 'BREACHED';
    
    const diffHrs = Math.floor(diffMs / (1000 * 60 * 60));
    const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
    const diffSecs = Math.floor((diffMs % (1000 * 60)) / 1000);
    
    if (diffHrs > 0) {
      return `${diffHrs}h ${diffMins}m ${diffSecs}s`;
    } else if (diffMins > 0) {
      return `${diffMins}m ${diffSecs}s`;
    } else {
      return `${diffSecs}s`;
    }
  };

  // Update time left every second
  useEffect(() => {
    if (atRiskIncidents && atRiskIncidents.length > 0) {
      const interval = setInterval(() => {
        // Find the incident with the earliest deadline
        const earliest = atRiskIncidents.reduce((prev, current) => {
          const prevDate = new Date(prev.sla_deadline);
          const currentDate = new Date(current.sla_deadline);
          return prevDate < currentDate ? prev : current;
        });
        setTimeLeft(formatTimeLeft(earliest.sla_deadline));
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [atRiskIncidents]);

  // Set up auto-refresh interval (every 5 minutes)
  useEffect(() => {
    const interval = setInterval(() => {
      refetchAll();
    }, 5 * 60 * 1000); // 5 minutes
    return () => clearInterval(interval);
  }, []);

  // Function to refetch all data
  const refetchAll = async () => {
    await refetchAnalytics();
    await refetchTrend();
    await refetchCompanies();
    await refetchAtRisk();
    setLastUpdated(new Date().toLocaleTimeString());
  };

  const getComplianceColor = (rate) => {
    if (rate >= 95) return 'success';
    if (rate >= 80) return 'warning';
    return 'danger';
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1>Dashboard</h1>
        <div className="dashboard-actions">
          <button 
            className="btn btn-outline-primary btn-sm"
            onClick={refetchAll}
          >
            <i className="fas fa-sync-alt"></i> Refresh
          </button>
          <span className="text-muted small ms-2">
            Last updated: {lastUpdated || 'Never'}
          </span>
        </div>
      </div>

      {analyticsError && <div className="alert alert-danger">{analyticsError}</div>}
      {atRiskError && <div className="alert alert-warning">{atRiskError}</div>}
      {notificationsError && <div className="alert alert-warning">{notificationsError}</div>}

      {!analyticsLoading && (
        <>
          {/* KPI Cards */}
          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-icon total-incidents">
                <i className="fas fa-ticket-alt"></i>
              </div>
              <div className="kpi-content">
                <div className="kpi-value">{analytics?.total_incidents || 0}</div>
                <div className="kpi-label">Total Incidents</div>
              </div>
            </div>

            <div className="kpi-card">
              <div className="kpi-icon open-tickets">
                <i className="fas fa-hourglass-start"></i>
              </div>
              <div className="kpi-content">
                <div className="kpi-value">{analytics?.open_tickets || 0}</div>
                <div className="kpi-label">Open Tickets</div>
              </div>
            </div>

            <div className="kpi-card">
              <div className="kpi-icon resolved-tickets">
                <i className="fas fa-check-circle"></i>
              </div>
              <div className="kpi-content">
                <div className="kpi-value">{analytics?.resolved_tickets || 0}</div>
                <div className="kpi-label">Resolved Tickets</div>
              </div>
            </div>

            <div className="kpi-card">
              <div className={`kpi-icon sla-compliance ${getComplianceColor(analytics?.sla_compliance_rate || 0)}`}>
                <i className="fas fa-tachometer-alt"></i>
              </div>
              <div className="kpi-content">
                <div className="kpi-value">{analytics?.sla_compliance_rate || 0}%</div>
                <div className="kpi-label">SLA Compliance</div>
              </div>
            </div>

            <div className="kpi-card">
              <div className="kpi-icon revenue">
                <i className="fas fa-dollar-sign"></i>
              </div>
              <div className="kpi-content">
                <div className="kpi-value">${analytics?.revenue?.toLocaleString() || 0}</div>
                <div className="kpi-label">Total Revenue</div>
              </div>
            </div>

            <div className="kpi-card">
              <div className="kpi-icon sla-breached">
                <i className="fas fa-exclamation-triangle"></i>
              </div>
              <div className="kpi-content">
                <div className="kpi-value">{analytics?.sla_breached_count || 0}</div>
                <div className="kpi-label">SLA Breached</div>
              </div>
            </div>

            {/* New KPI: At Risk Incidents */}
            <div className="kpi-card">
              <div className="kpi-icon sla-at-risk">
                <i className="fas fa-exclamation-circle"></i>
              </div>
              <div className="kpi-content">
                <div className="kpi-value">
                  {atRiskIncidents?.length || 0}
                  {timeLeft && (
                    <span className="ms-2 badge bg-danger-pulse">
                      {timeLeft}
                    </span>
                  )}
                </div>
                <div className="kpi-label">At Risk of Breach</div>
              </div>
            </div>
          </div>

          {/* Charts Row */}
          <div className="charts-row">
            <div className="chart-container">
              <h3>Incidents Trend (Last 30 Days)</h3>
              <canvas id="incidentsChart"></canvas>
            </div>

            <div className="chart-container">
              <h3>Top Companies by Volume</h3>
              <div className="top-companies-list">
                {topCompanies?.map((company, index) => (
                  <div key={index} className="company-item">
                    <span className="company-name">{company.name}</span>
                    <span className="company-count badge badge-primary">
                      {company.incident_count} incidents
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Notifications Panel */}
          <div className="notifications-panel">
            <h3>
              <i className="fas fa-bell me-2"></i>
              Internal Notifications
              {recentNotifications?.length > 0 && (
                <span className="badge bg-danger">{recentNotifications.length}</span>
              )}
            </h3>
            {notificationsLoading ? (
              <div className="spinner-container">
                <div className="spinner"></div>
              </div>
            ) : (
              <div className="notifications-list">
                {recentNotifications && recentNotifications.length > 0 ? (
                  recentNotifications.map(notification => (
                    <div key={notification.id} className="notification-item">
                      <div className="notification-header">
                        <span className={`notification-type ${notification.type}`}>
                          {notification.type.charAt(0).toUpperCase() + notification.type.slice(1)}
                        </span>
                        <small className="text-muted">
                          {new Date(notification.created_at).toLocaleString()}
                        </small>
                      </div>
                      <div className="notification-body">
                        {notification.message}
                      </div>
                    </div>
                  )) : (
                    <div className="text-center text-muted py-3">
                      No new notifications
                    </div>
                  )}
              </div>
            )}
          </div>

          {/* Quick Actions */}
          <div className="quick-actions">
            <h3>Quick Actions</h3>
            <div className="actions-grid">
              <a href="/companies/new" className="action-btn">
                <i className="fas fa-building"></i>
                <span>Add New Company</span>
              </a>
              <a href="/users/new" className="action-btn">
                <i className="fas fa-user-plus"></i>
                <span>Add New User</span>
              </a>
              <a href="/incidents" className="action-btn">
                <i className="fas fa-list"></i>
                <span>View All Incidents</span>
              </a>
              <a href="/billing" className="action-btn">
                <i className="fas fa-receipt"></i>
                <span>Create Invoice</span>
              </a>
              <a href="/reports" className="action-btn">
                <i className="fas fa-chart-bar"></i>
                <span>View Reports</span>
              </a>
              <a href="/settings" className="action-btn">
                <i className="fas fa-cog"></i>
                <span>System Settings</span>
              </a>
            </div>
          </div>
        </>
      )}
      
      {analyticsLoading || trendLoading || companiesLoading || atRiskLoading ? (
        <div className="spinner-container">
          <div className="spinner"></div>
        </div>
      ) : null}
    </div>
  );
};

export default MainDashboard;