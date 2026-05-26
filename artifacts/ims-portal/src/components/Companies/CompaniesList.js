// src/components/Companies/CompaniesList.js - Companies list and management
import React, { useState } from 'react';
import { companiesAPI } from '../../services/api';
import useFetch from '../../hooks/useFetch';
import './Companies.scss';

const CompaniesList = () => {
  const [skip, setSkip] = useState(0);
  const [limit] = useState(10);
  const [statusFilter, setStatusFilter] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    contact_person: '',
    contact_email: '',
    sla_type: 'silver'
  });

  const { data: companiesData, loading, error, refetch } = useFetch(
    () => companiesAPI.getAll(skip, limit, statusFilter),
    [skip, limit, statusFilter]
  );

  const companies = companiesData?.data || [];
  const total = companiesData?.total || 0;

  const handleOpenModal = (company = null) => {
    if (company) {
      setFormData(company);
      setEditingId(company.id);
    } else {
      setFormData({
        name: '',
        contact_person: '',
        contact_email: '',
        sla_type: 'silver'
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
        await companiesAPI.update(editingId, formData);
      } else {
        await companiesAPI.create(formData);
      }
      handleCloseModal();
      refetch();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleToggleStatus = async (companyId, currentStatus) => {
    try {
      const newStatus = currentStatus === 'active' ? 'inactive' : 'active';
      await companiesAPI.updateStatus(companyId, newStatus);
      refetch();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const filteredCompanies = companies.filter(c =>
    c.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    c.contact_email.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(skip / limit) + 1;

  return (
    <div className="companies-container">
      <h1>Companies Management</h1>

      {error && <div className="alert alert-danger">{error}</div>}

      {/* Toolbar */}
      <div className="companies-toolbar">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search companies..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="form-control"
          />
        </div>

        <div className="filter-controls">
          <select
            className="form-control"
            value={statusFilter || ''}
            onChange={(e) => setStatusFilter(e.target.value || null)}
          >
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>

        <button 
          className="btn btn-primary"
          onClick={() => handleOpenModal()}
        >
          <i className="fas fa-plus"></i> Add Company
        </button>
      </div>

      {/* Companies Table */}
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
                  <th>Company Name</th>
                  <th>Contact Person</th>
                  <th>Email</th>
                  <th>SLA Type</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredCompanies.map(company => (
                  <tr key={company.id}>
                    <td>
                      <strong>{company.name}</strong>
                    </td>
                    <td>{company.contact_person}</td>
                    <td>{company.contact_email}</td>
                    <td>
                      <span className="badge badge-info">
                        {company.sla_type?.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      <span className={`badge badge-${company.status === 'active' ? 'success' : 'danger'}`}>
                        {company.status?.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button 
                          className="btn btn-sm btn-info"
                          onClick={() => handleOpenModal(company)}
                        >
                          <i className="fas fa-edit"></i>
                        </button>
                        <button 
                          className={`btn btn-sm btn-${company.status === 'active' ? 'warning' : 'success'}`}
                          onClick={() => handleToggleStatus(company.id, company.status)}
                        >
                          <i className={`fas fa-${company.status === 'active' ? 'ban' : 'check'}`}></i>
                        </button>
                        <a 
                          href={`/companies/${company.id}/users`}
                          className="btn btn-sm btn-secondary"
                        >
                          <i className="fas fa-users"></i>
                        </a>
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
              <h2>{editingId ? 'Edit Company' : 'Add New Company'}</h2>
              <button className="close-btn" onClick={handleCloseModal}>
                <i className="fas fa-times"></i>
              </button>
            </div>

            <form onSubmit={handleSubmit} className="modal-body">
              <div className="form-group">
                <label>Company Name *</label>
                <input
                  type="text"
                  className="form-control"
                  value={formData.name}
                  onChange={(e) => setFormData({...formData, name: e.target.value})}
                  required
                />
              </div>

              <div className="form-group">
                <label>Contact Person</label>
                <input
                  type="text"
                  className="form-control"
                  value={formData.contact_person}
                  onChange={(e) => setFormData({...formData, contact_person: e.target.value})}
                />
              </div>

              <div className="form-group">
                <label>Contact Email *</label>
                <input
                  type="email"
                  className="form-control"
                  value={formData.contact_email}
                  onChange={(e) => setFormData({...formData, contact_email: e.target.value})}
                  required
                />
              </div>

              <div className="form-group">
                <label>SLA Type *</label>
                <select
                  className="form-control"
                  value={formData.sla_type}
                  onChange={(e) => setFormData({...formData, sla_type: e.target.value})}
                  required
                >
                  <option value="bronze">Bronze</option>
                  <option value="silver">Silver</option>
                  <option value="gold">Gold</option>
                </select>
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={handleCloseModal}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  {editingId ? 'Update Company' : 'Create Company'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default CompaniesList;
