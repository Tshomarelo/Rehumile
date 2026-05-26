// src/components/Billing/InvoicesList.js - Billing and invoicing management
import React, { useState } from 'react';
import { invoicesAPI } from '../../services/api';
import useFetch from '../../hooks/useFetch';
import './Billing.scss';

const InvoicesList = () => {
  const [skip, setSkip] = useState(0);
  const [limit] = useState(10);
  const [statusFilter, setStatusFilter] = useState('');
  const [companyFilter, setCompanyFilter] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [formData, setFormData] = useState({
    company_id: '',
    billing_period_start: '',
    billing_period_end: ''
  });

  const { data: invoicesData, loading, error, refetch } = useFetch(
    () => invoicesAPI.getAll(companyFilter, statusFilter, skip, limit),
    [skip, limit, statusFilter, companyFilter]
  );

  const invoices = invoicesData?.data || [];
  const total = invoicesData?.total || 0;

  const handleCreateInvoice = async (e) => {
    e.preventDefault();
    try {
      await invoicesAPI.create(formData);
      setShowModal(false);
      refetch();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleStatusChange = async (invoiceId, newStatus) => {
    try {
      await invoicesAPI.updateStatus(invoiceId, newStatus);
      refetch();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleDownloadPDF = async (invoiceId) => {
    try {
      const response = await invoicesAPI.getPDF(invoiceId);
      // Trigger download
      const url = window.URL.createObjectURL(response);
      const a = document.createElement('a');
      a.href = url;
      a.download = `invoice-${invoiceId}.pdf`;
      a.click();
    } catch (err) {
      alert('Error downloading PDF: ' + err.message);
    }
  };

  const getStatusColor = (status) => {
    const colors = {
      draft: 'secondary',
      sent: 'info',
      paid: 'success',
      overdue: 'danger'
    };
    return colors[status] || 'secondary';
  };

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(skip / limit) + 1;

  return (
    <div className="billing-container">
      <h1>Billing & Invoices</h1>

      {error && <div className="alert alert-danger">{error}</div>}

      {/* Filters */}
      <div className="billing-toolbar">
        <div className="filter-group">
          <select
            className="form-control"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setSkip(0);
            }}
          >
            <option value="">All Status</option>
            <option value="draft">Draft</option>
            <option value="sent">Sent</option>
            <option value="paid">Paid</option>
            <option value="overdue">Overdue</option>
          </select>
        </div>

        <button 
          className="btn btn-primary"
          onClick={() => setShowModal(true)}
        >
          <i className="fas fa-plus"></i> Create Invoice
        </button>
      </div>

      {/* Invoices Table */}
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
                  <th>Invoice #</th>
                  <th>Company</th>
                  <th>Period</th>
                  <th>Items</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map(invoice => (
                  <tr key={invoice.id}>
                    <td>
                      <strong>{invoice.invoice_number}</strong>
                    </td>
                    <td>{invoice.company_name}</td>
                    <td>
                      {new Date(invoice.billing_period_start).toLocaleDateString()} - {new Date(invoice.billing_period_end).toLocaleDateString()}
                    </td>
                    <td>
                      <span className="badge badge-secondary">{invoice.ticket_count} tickets</span>
                    </td>
                    <td>
                      <strong>${invoice.total_amount?.toFixed(2)}</strong>
                    </td>
                    <td>
                      <select
                        className={`badge badge-${getStatusColor(invoice.status)}`}
                        value={invoice.status}
                        onChange={(e) => handleStatusChange(invoice.id, e.target.value)}
                      >
                        <option value="draft">Draft</option>
                        <option value="sent">Sent</option>
                        <option value="paid">Paid</option>
                        <option value="overdue">Overdue</option>
                      </select>
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button 
                          className="btn btn-sm btn-info"
                          onClick={() => {/* View details */}}
                        >
                          <i className="fas fa-eye"></i>
                        </button>
                        <button 
                          className="btn btn-sm btn-success"
                          onClick={() => handleDownloadPDF(invoice.id)}
                        >
                          <i className="fas fa-download"></i>
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

      {/* Create Invoice Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Create New Invoice</h2>
              <button className="close-btn" onClick={() => setShowModal(false)}>
                <i className="fas fa-times"></i>
              </button>
            </div>

            <form onSubmit={handleCreateInvoice} className="modal-body">
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

              <div className="form-group">
                <label>Billing Period Start *</label>
                <input
                  type="date"
                  className="form-control"
                  value={formData.billing_period_start}
                  onChange={(e) => setFormData({...formData, billing_period_start: e.target.value})}
                  required
                />
              </div>

              <div className="form-group">
                <label>Billing Period End *</label>
                <input
                  type="date"
                  className="form-control"
                  value={formData.billing_period_end}
                  onChange={(e) => setFormData({...formData, billing_period_end: e.target.value})}
                  required
                />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Create Invoice
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default InvoicesList;
