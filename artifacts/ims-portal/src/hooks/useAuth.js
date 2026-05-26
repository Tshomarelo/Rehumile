// src/hooks/useAuth.js - Authentication hook
import { useState, useEffect, useCallback } from 'react';
import AuthUtils from '../utils/auth';
import { authAPI } from '../services/api';

export const useAuth = () => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Initialize auth state from localStorage
  useEffect(() => {
    const storedUser = AuthUtils.getUser();
    const token = AuthUtils.getToken();

    if (storedUser && token && AuthUtils.isTokenValid()) {
      setUser(storedUser);
    } else {
      AuthUtils.clearAuthData();
    }
    setLoading(false);
  }, []);

  // Login function
  const login = useCallback(async (email, password) => {
    setLoading(true);
    setError(null);
    try {
      const response = await authAPI.login(email, password);
      const { token, user: userData } = response.data;
      AuthUtils.setAuthData(token, userData);
      setUser(userData);
      return userData;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // Logout function
  const logout = useCallback(async () => {
    try {
      await authAPI.logout();
    } catch (err) {
      console.error('Logout error:', err);
    } finally {
      AuthUtils.clearAuthData();
      setUser(null);
    }
  }, []);

  // Check authorization
  const isAuthorized = useCallback((requiredRole) => {
    if (!user) return false;
    if (!requiredRole) return true;
    return user.role === requiredRole || user.role === 'admin';
  }, [user]);

  const isAdmin = useCallback(() => isAuthorized('admin'), [isAuthorized]);
  const isAgent = useCallback(() => isAuthorized('agent'), [isAuthorized]);
  const isFinance = useCallback(() => isAuthorized('finance'), [isAuthorized]);

  return {
    user,
    loading,
    error,
    login,
    logout,
    isAuthenticated: !!user,
    isAuthorized,
    isAdmin,
    isAgent,
    isFinance
  };
};

export default useAuth;
