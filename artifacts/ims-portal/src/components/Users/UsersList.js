// src/components/Users/UsersList.js - User management
import React, { useState } from 'react';
import { usersAPI } from '../../services/api';
import useFetch from '../../hooks/useFetch';
import './Users.scss';

const UsersList = () => {
  const [skip, setSkip] = useState(0);
  const [limit] = useState(10);
  const [roleFilter, setRoleFilter] = useState('');
  const [companyFilter, setCompanyFilter] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formData, setFormData] = useState({
    email: '',
    first_name: '',
    last_name: '',
    role: 'viewer',
    company_id: ''
  });

  const { data: usersData, loading, error, refetch } = useFetch(
    () => usersAPI.getAll(companyFilter, roleFilter, skip, limit),
    [skip, limit, roleFilter, companyFilter]
  );

  const users = usersData?.data || [];
  const total = usersData?.total || 0;

  const handleOpenModal = (user = null) => {
    if (user) {
      setFormData(user);
      setEditingId(user.id);
    } else {
      setFormData({
        email: '',
        first_name: '',
        last_name: '',
        role: 'viewer',
        company_id: ''
      });
      setEditingId(null);
    }
    setShowModal(true);
  };

  const handleCloseModal = () => {
    setShowModal(false);
    setEditingId(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      if (editingId) {
        await usersAPI.update(editingId, formData);
      } else {
        await usersAPI.create(formData);
      }
      handleCloseModal();
      refetch();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleToggleStatus = async (userId, currentStatus) => {
    try {
      const newStatus = currentStatus === 'active' ? 'inactive' : 'active';
      await usersAPI.updateStatus(userId, newStatus);
      refetch();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleResetPassword = async (userId) => {
    if (window.confirm('Send password reset email to this user?')) {
      try {
        await usersAPI.resetPassword(userId);
        alert('Password reset link sent!');
      } catch (err) {
        alert('Error: ' + err.message);
      }
    }
  };

  const getRoleColor = (role) => {
    const colors = {
      admin: 'danger',
      agent: 'info',
      finance: 'warning',
      viewer: 'secondary'
    };
    return colors[role] || 'secondary';
  };

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(skip / limit) + 1;

  return (
    <div className="users-container">
      <h1>User Management</h1>

      {error && <div className="alert alert-danger">{error}</div>}

      {/* Filters */}
      <div className="users-toolbar">
        <div className="filter-group">
          <select
            className="form-control"
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setSkip(0);
            }}
          >
            <option value="">All Roles</option>
            <option value="admin">Admin</option>
            <option value="agent">Agent</option>
            <option value="finance">Finance</option>
            <option value="viewer">Viewer</option>
          </select>
        </div>

        <button 
          className="btn btn-primary"
          onClick={() => handleOpenModal()}
        >
          <i className="fas fa-plus"></i> Add User
        </button>
      </div>

      {/* Users Table */}
      {loading ? (
        <div className="spinner-container">
          <div className="spinner"></div>
        </div>
      ) : (
        <>
          <div className="table-responsive">
            <table className="table table-hover">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Company</th>
                  <th>Status</th>
                  <th>Last Login</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map(user => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.first_name} {user.last_name}</strong>
                    </td>
                    <td>{user.email}</td>
                    <td>
                      <span className={`badge badge-${getRoleColor(user.role)}`}>
                        {user.role?.toUpperCase()}
                      </span>
                    </td>
                    <td>{user.company_name}</td>
                    <td>
                      <span className={`badge badge-${user.status === 'active' ? 'success' : 'danger'}`}>
                        {user.status?.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      {user.last_login ? new Date(user.last_login).toLocaleDateString() : 'Never'}
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button 
                          className="btn btn-sm btn-info"
                          onClick={() => handleOpenModal(user)}
                          title="Edit"
                        >
                          <i className="fas fa-edit"></i>
                        </button>
                        <button 
                          className={`btn btn-sm btn-${user.status === 'active' ? 'warning' : 'success'}`}
                          onClick={() => handleToggleStatus(user.id, user.status)}
                          title={user.status === 'active' ? 'Deactivate' : 'Activate'}
                        >
                          <i className={`fas fa-${user.status === 'active' ? 'ban' : 'check'}`}></i>
                        </button>
                        <button 
                          className="btn btn-sm btn-secondary"
                          onClick={() => handleResetPassword(user.id)}
                          title="Reset Password"
                        >
                          <i className="fas fa-key"></i>
                        </button>
                      </div>
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
              Page {currentPage} of {totalPages || 1}
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

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={handleCloseModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{editingId ? 'Edit User' : 'Add New User'}</h2>
              <button className="close-btn" onClick={handleCloseModal}>
                <i className="fas fa-times"></i>
              </button>
            </div>

            <form onSubmit={handleSubmit} className="modal-body">
              <div className="form-group">
                <label>Email *</label>
                <input
                  type="email"
                  className="form-control"
                  value={formData.email}
                  onChange={(e) => setFormData({...formData, email: e.target.value})}
                  required
                  disabled={!!editingId}
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>First Name *</label>
                  <input
                    type="text"
                    className="form-control"
                    value={formData.first_name}
                    onChange={(e) => setFormData({...formData, first_name: e.target.value})}
                    required
                  />
                </div>

                <div className="form-group">
                  <label>Last Name *</label>
                  <input
                    type="text"
                    className="form-control"
                    value={formData.last_name}
                    onChange={(e) => setFormData({...formData, last_name: e.target.value})}
                    required
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Role *</label>
                  <select
                    className="form-control"
                    value={formData.role}
                    onChange={(e) => setFormData({...formData, role: e.target.value})}
                    required
                  >
                    <option value="viewer">Viewer</option>
                    <option value="agent">Agent</option>
                    <option value="finance">Finance</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Company *</label>
                  <select
                    className="form-control"
                    value={formData.company_id}
                    onChange={(e) => setFormData({...formData, company_id: e.target.value})}
                    required
                  >
                    <option value="">Select Company</option>
                    {/* Companies will be populated from API */}
                  </select>
                </div>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={handleCloseModal}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  {editingId ? 'Update User' : 'Create User'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default UsersList;
