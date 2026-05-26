// src/utils/auth.js - Authentication utilities
import jwt_decode from 'jwt-decode';

const TOKEN_KEY = 'ims_auth_token';
const USER_KEY = 'ims_user';

export const AuthUtils = {
  // Store token and user in localStorage
  setAuthData: (token, user) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },

  // Get token from localStorage
  getToken: () => localStorage.getItem(TOKEN_KEY),

  // Get user from localStorage
  getUser: () => {
    const user = localStorage.getItem(USER_KEY);
    return user ? JSON.parse(user) : null;
  },

  // Check if token is valid and not expired
  isTokenValid: () => {
    const token = AuthUtils.getToken();
    if (!token) return false;

    try {
      const decoded = jwt_decode(token);
      const currentTime = Date.now() / 1000;
      return decoded.exp > currentTime;
    } catch (error) {
      return false;
    }
  },

  // Get user role
  getUserRole: () => {
    const user = AuthUtils.getUser();
    return user?.role;
  },

  // Get user company ID
  getUserCompanyId: () => {
    const user = AuthUtils.getUser();
    return user?.company_id;
  },

  // Clear auth data (logout)
  clearAuthData: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },

  // Check if user has specific role
  hasRole: (requiredRole) => {
    const userRole = AuthUtils.getUserRole();
    return userRole === requiredRole;
  },

  // Check if user is HQ admin
  isHQAdmin: () => {
    return AuthUtils.getUserRole() === 'admin';
  },

  // Check if user is finance role
  isFinance: () => {
    return AuthUtils.getUserRole() === 'finance';
  },

  // Check if user is agent
  isAgent: () => {
    return AuthUtils.getUserRole() === 'agent';
  },

  // Check if user is client
  isClient: () => {
    return AuthUtils.getUserRole() === 'client';
  },

  // Decode token and get payload
  getTokenPayload: () => {
    const token = AuthUtils.getToken();
    if (!token) return null;
    try {
      return jwt_decode(token);
    } catch (error) {
      return null;
    }
  }
};

export default AuthUtils;
