// src/components/Incidents/IncidentsList.js - Central incident management view
import React, { useState } from 'react';
import { incidentsAPI } from '../../services/api';
import useFetch from '../../hooks/useFetch';
import './Incidents.scss';

const IncidentsList = () => {
  const [skip, setSkip] = useState(0);
  const [limit] = useState(15);
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [companyFilter, setCompanyFilter] = useState('');
  const [slaBreachedFilter, setSlaBreachedFilter] = useState('');
  const [selectedIncident, setSelectedIncident] = useState(null);

  const filters = {
    skip,
    limit,
    ...(statusFilter && { status: statusFilter }),
    ...(priorityFilter && { priority: priorityFilter }),
    ...(companyFilter && { company_id: companyFilter }),
    ...(slaBreachedFilter && { sla_breached: slaBreachedFilter === 'true' })
  };

  const { data: incidentsData, loading, error, refetch } = useFetch(
    () => incidentsAPI.getAll(filters),
    [skip, limit, statusFilter, priorityFilter, companyFilter, slaBreachedFilter]
  );

  const { data: detailedIncident } = useFetch(
    () => selectedIncident ? incidentsAPI.getById(selectedIncident) : null,
    [selectedIncident]
  );

  const incidents = incidentsData?.data || [];
  const total = incidentsData?.total || 0;

  const getPriorityClass = (priority) => {
    const priorities = {
      critical: 'danger',
      high: 'warning',
      medium: 'info',
      low: 'secondary'
    };
    return priorities[priority] || 'secondary';
  };

  const getStatusClass = (status) => {
    const statuses = {
      open: 'primary',
      in_progress: 'info',
      resolved: 'success',
      closed: 'secondary'
    };
    return statuses[status] || 'secondary';
  };

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(skip / limit) + 1;

  return (
    <div className="incidents-container">
      <h1>Incident Management</h1>

      {error && <div className="alert alert-danger">{error}</div>}

      {/* Filters */}
      <div className="incidents-filters">
        <div className="filter-group">
          <label>Status</label>
          <select
            className="form-control"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setSkip(0);
            }}
          >
            <option value="">All Status</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Priority</label>
          <select
            className="form-control"
            value={priorityFilter}
            onChange={(e) => {
              setPriorityFilter(e.target.value);
              setSkip(0);
            }}
          >
            <option value="">All Priority</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>

        <div className="filter-group">
          <label>SLA Status</label>
          <select
            className="form-control"
            value={slaBreachedFilter}
            onChange={(e) => {
              setSlaBreachedFilter(e.target.value);
              setSkip(0);
            }}
          >
            <option value="">All</option>
            <option value="true">Breached</option>
            <option value="false">On Track</option>
          </select>
        </div>

        <button className="btn btn-primary" onClick={refetch}>
          <i className="fas fa-sync"></i> Refresh
        </button>
      </div>

      {/* Incidents List */}
      {loading ? (
        <div className="spinner-container">
          <div className="spinner"></div>
        </div>
      ) : (
        <>
          <div className="table-responsive">
            <table className="table table-hover incidents-table">
              <thead>
                <tr>
                  <th>Ticket ID</th>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Assigned To</th>
                  <th>SLA Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map(incident => (
                  <tr 
                    key={incident.id}
                    className={incident.sla_breached ? 'sla-breached' : ''}
                  >
                    <td>
                      <strong className="ticket-id">{incident.ticket_id}</strong>
                    </td>
                    <td>
                      <div className="incident-title">{incident.title}</div>
                      <small className="text-muted">{incident.description?.substring(0, 50)}...</small>
                    </td>
                    <td>{incident.company_name}</td>
                    <td>
                      <span className={`badge badge-${getPriorityClass(incident.priority)}`}>
                        {incident.priority?.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      <span className={`badge badge-${getStatusClass(incident.status)}`}>
                        {incident.status?.toUpperCase()}
                      </span>
                    </td>
                    <td>{incident.assigned_to_name || 'Unassigned'}</td>
                    <td>
                      {incident.sla_breached ? (
                        <span className="badge badge-danger">
                          <i className="fas fa-exclamation-triangle"></i> BREACHED
                        </span>
                      ) : (
                        <span className="badge badge-success">ON TRACK</span>
                      )}
                    </td>
                    <td>
                      <button 
                        className="btn btn-sm btn-info"
                        onClick={() => setSelectedIncident(incident.id)}
                      >
                        <i className="fas fa-eye"></i>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="pagination-container">
            <button 
              disabled={currentPage === 1}
              onClick={() => setSkip(skip - limit)}
              className="btn btn-sm btn-outline-primary"
            >
              Previous
            </button>
            <span className="page-info">
              Page {currentPage} of {totalPages || 1} ({total} total)
            </span>
            <button 
              disabled={currentPage >= totalPages}
              onClick={() => setSkip(skip + limit)}
              className="btn btn-sm btn-outline-primary"
            >
              Next
            </button>
          </div>
        </>
      )}

      {/* Incident Detail Modal */}
      {selectedIncident && detailedIncident && (
        <IncidentDetailModal 
          incident={detailedIncident}
          onClose={() => setSelectedIncident(null)}
          onUpdate={refetch}
        />
      )}
    </div>
  );
};

// Incident Detail Modal Component
const IncidentDetailModal = ({ incident, onClose, onUpdate }) => {
  const [comments, setComments] = useState('');
  const [isInternal, setIsInternal] = useState(false);

  const handleAddComment = async () => {
    if (!comments.trim()) return;

    try {
      await incidentsAPI.addComment(incident.id, comments, isInternal);
      setComments('');
      onUpdate();
    } catch (err) {
      alert('Error adding comment: ' + err.message);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content large-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{incident.title}</h2>
          <button className="close-btn" onClick={onClose}>
            <i className="fas fa-times"></i>
          </button>
        </div>

        <div className="modal-body">
          {/* Incident Info */}
          <div className="incident-info">
            <div className="info-row">
              <div className="info-item">
                <label>Ticket ID</label>
                <span>{incident.ticket_id}</span>
              </div>
              <div className="info-item">
                <label>Company</label>
                <span>{incident.company_name}</span>
              </div>
              <div className="info-item">
                <label>Priority</label>
                <span className="badge badge-danger">{incident.priority?.toUpperCase()}</span>
              </div>
              <div className="info-item">
                <label>Status</label>
                <span className="badge badge-info">{incident.status?.toUpperCase()}</span>
              </div>
            </div>

            <div className="info-row">
              <div className="info-item">
                <label>Submitted By</label>
                <span>{incident.submitted_by_name}</span>
              </div>
              <div className="info-item">
                <label>Assigned To</label>
                <span>{incident.assigned_to_name || 'Unassigned'}</span>
              </div>
              <div className="info-item">
                <label>SLA Deadline</label>
                <span>{new Date(incident.sla_deadline).toLocaleString()}</span>
              </div>
              <div className="info-item">
                <label>Billable</label>
                <span>{incident.is_billable ? 'Yes' : 'No'}</span>
              </div>
            </div>
          </div>

          {/* Description */}
          <div className="section">
            <h4>Description</h4>
            <p>{incident.description}</p>
          </div>

          {/* Comments Section */}
          <div className="section">
            <h4>Comments & Timeline</h4>
            <div className="comments-list">
              {incident.comments?.map(comment => (
                <div key={comment.id} className={`comment-item ${comment.is_internal ? 'internal' : ''}`}>
                  <div className="comment-header">
                    <strong>{comment.author_name}</strong>
                    {comment.is_internal && <span className="badge badge-warning">Internal</span>}
                    <small>{new Date(comment.created_at).toLocaleString()}</small>
                  </div>
                  <div className="comment-body">{comment.comment_text}</div>
                </div>
              ))}
            </div>

            {/* Add Comment */}
            <div className="add-comment-form">
              <textarea
                className="form-control"
                rows="3"
                placeholder="Add a comment..."
                value={comments}
                onChange={(e) => setComments(e.target.value)}
              />
              <div className="form-check">
                <input
                  type="checkbox"
                  id="internalCheck"
                  checked={isInternal}
                  onChange={(e) => setIsInternal(e.target.checked)}
                />
                <label htmlFor="internalCheck">Internal comment (not visible to client)</label>
              </div>
              <button 
                className="btn btn-primary"
                onClick={handleAddComment}
              >
                <i className="fas fa-comment"></i> Add Comment
              </button>
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
          <button className="btn btn-primary">
            Update Incident
          </button>
        </div>
      </div>
    </div>
  );
};

export default IncidentsList;
