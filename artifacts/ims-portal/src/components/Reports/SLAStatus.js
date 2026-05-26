// src/components/Reports/SLAStatus.js - SLA tracking and breach alerts
import React, { useState } from 'react';
import { slaAPI, incidentsAPI } from '../../services/api';
import useFetch from '../../hooks/useFetch';
import './Reports.scss';

const SLAStatus = () => {
  const [viewMode, setViewMode] = useState('breached'); // 'breached' or 'at-risk'

  const { data: breachedIncidents, loading: loadingBreached } = useFetch(
    () => slaAPI.getBreached(),
    [viewMode]
  );

  const { data: atRiskIncidents, loading: loadingAtRisk } = useFetch(
    () => slaAPI.getAtRisk(),
    [viewMode]
  );

  const incidents = viewMode === 'breached' ? breachedIncidents : atRiskIncidents;
  const loading = viewMode === 'breached' ? loadingBreached : loadingAtRisk;

  const getStatusColor = (severity) => {
    if (severity === 'critical') return 'danger';
    if (severity === 'high') return 'warning';
    return 'info';
  };

  return (
    <div className="sla-container">
      <h1>SLA Status Monitoring</h1>

      {/* View Toggle */}
      <div className="view-toggle">
        <button 
          className={`btn ${viewMode === 'breached' ? 'btn-danger' : 'btn-outline-danger'}`}
          onClick={() => setViewMode('breached')}
        >
          <i className="fas fa-exclamation-circle"></i> SLA Breached ({breachedIncidents?.length || 0})
        </button>
        <button 
          className={`btn ${viewMode === 'at-risk' ? 'btn-warning' : 'btn-outline-warning'}`}
          onClick={() => setViewMode('at-risk')}
        >
          <i className="fas fa-clock"></i> At Risk ({atRiskIncidents?.length || 0})
        </button>
      </div>

      {/* Incidents List */}
      {loading ? (
        <div className="spinner-container">
          <div className="spinner"></div>
        </div>
      ) : (
        <div className="sla-list">
          {incidents && incidents.length > 0 ? (
            incidents.map(incident => (
              <div key={incident.id} className={`sla-card alert alert-${getStatusColor(incident.priority)}`}>
                <div className="sla-card-header">
                  <h4>{incident.ticket_id}: {incident.title}</h4>
                  <span className="badge badge-danger">
                    <i className="fas fa-exclamation-triangle"></i> {viewMode === 'breached' ? 'BREACHED' : 'AT RISK'}
                  </span>
                </div>

                <div className="sla-card-body">
                  <div className="sla-item">
                    <label>Company:</label>
                    <span>{incident.company_name}</span>
                  </div>
                  <div className="sla-item">
                    <label>Priority:</label>
                    <span className="badge badge-danger">{incident.priority?.toUpperCase()}</span>
                  </div>
                  <div className="sla-item">
                    <label>Status:</label>
                    <span>{incident.status?.toUpperCase()}</span>
                  </div>
                  <div className="sla-item">
                    <label>SLA Deadline:</label>
                    <span>{new Date(incident.sla_deadline).toLocaleString()}</span>
                  </div>
                  {viewMode === 'breached' && (
                    <div className="sla-item">
                      <label>Breached Since:</label>
                      <span>{incident.hours_breached} hours ago</span>
                    </div>
                  )}
                </div>

                <div className="sla-card-footer">
                  <button className="btn btn-sm btn-primary">
                    <i className="fas fa-eye"></i> View Details
                  </button>
                  <button className="btn btn-sm btn-warning">
                    <i className="fas fa-exclamation"></i> Escalate
                  </button>
                </div>
              </div>
            ))
          ) : (
            <div className="alert alert-success">
              <i className="fas fa-check-circle"></i> No {viewMode} incidents!
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default SLAStatus;
