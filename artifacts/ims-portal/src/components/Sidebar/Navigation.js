// src/components/Sidebar/Navigation.js - Main navigation sidebar
import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import useAuth from '../../hooks/useAuth';
import './Sidebar.scss';

const Navigation = () => {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  const isActive = (path) => location.pathname.startsWith(path);

  const handleLogout = async () => {
    await logout();
    window.location.href = '/login';
  };

  const menuItems = [
    {
      label: 'Dashboard',
      icon: 'fas fa-chart-line',
      path: '/dashboard',
      roles: ['admin', 'agent', 'finance']
    },
    {
      label: 'Companies',
      icon: 'fas fa-building',
      path: '/companies',
      roles: ['admin']
    },
    {
      label: 'Users',
      icon: 'fas fa-users',
      path: '/users',
      roles: ['admin']
    },
    {
      label: 'Incidents',
      icon: 'fas fa-tickets',
      path: '/incidents',
      roles: ['admin', 'agent']
    },
    {
      label: 'Billing',
      icon: 'fas fa-receipt',
      path: '/billing',
      roles: ['admin', 'finance']
    },
    {
      label: 'Reports',
      icon: 'fas fa-chart-bar',
      path: '/reports',
      roles: ['admin', 'finance']
    },
    {
      label: 'SLA Status',
      icon: 'fas fa-tachometer-alt',
      path: '/sla',
      roles: ['admin', 'agent']
    }
  ];

  const visibleItems = menuItems.filter(item => 
    item.roles.includes(user?.role)
  );

  return (
    <div className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      {/* Logo */}
      <div className="sidebar-header">
        <div className="logo">
          <i className="fas fa-shield-alt"></i>
          {!collapsed && <span>IMS HQ</span>}
        </div>
        <button 
          className="collapse-btn"
          onClick={() => setCollapsed(!collapsed)}
        >
          <i className="fas fa-chevron-left"></i>
        </button>
      </div>

      {/* Navigation Menu */}
      <nav className="sidebar-nav">
        {visibleItems.map((item, index) => (
          <Link
            key={index}
            to={item.path}
            className={`nav-item ${isActive(item.path) ? 'active' : ''}`}
            title={collapsed ? item.label : ''}
          >
            <i className={item.icon}></i>
            {!collapsed && <span>{item.label}</span>}
          </Link>
        ))}
      </nav>

      {/* User Profile */}
      <div className="sidebar-footer">
        <div className="user-profile">
          <div className="user-avatar">
            {user?.first_name?.charAt(0)}{user?.last_name?.charAt(0)}
          </div>
          {!collapsed && (
            <div className="user-info">
              <div className="user-name">
                {user?.first_name} {user?.last_name}
              </div>
              <div className="user-role badge badge-primary">
                {user?.role?.toUpperCase()}
              </div>
            </div>
          )}
        </div>

        <button 
          className="logout-btn"
          onClick={handleLogout}
          title="Logout"
        >
          <i className="fas fa-sign-out-alt"></i>
          {!collapsed && <span>Logout</span>}
        </button>
      </div>
    </div>
  );
};

export default Navigation;
