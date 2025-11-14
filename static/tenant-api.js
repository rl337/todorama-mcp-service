// Tenant Management API Client Functions
// Shared API functions for organizations, teams, and roles

const API_BASE_URL = window.location.origin;
let apiKey = localStorage.getItem('apiKey') || '';

// Get API key from URL params if present
const urlParams = new URLSearchParams(window.location.search);
const keyParam = urlParams.get('api_key');
if (keyParam) {
    apiKey = keyParam;
    localStorage.setItem('apiKey', apiKey);
}

// API request helper
async function apiRequest(endpoint, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    if (apiKey) {
        headers['X-API-Key'] = apiKey;
    }

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            ...options,
            headers
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('API request failed:', error);
        throw error;
    }
}

// ============================================================================
// Organization API Functions
// ============================================================================

async function listOrganizations() {
    return await apiRequest('/organizations');
}

async function getOrganization(organizationId) {
    return await apiRequest(`/organizations/${organizationId}`);
}

async function createOrganization(data) {
    return await apiRequest('/organizations', {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

async function updateOrganization(organizationId, data) {
    return await apiRequest(`/organizations/${organizationId}`, {
        method: 'PATCH',
        body: JSON.stringify(data)
    });
}

async function deleteOrganization(organizationId) {
    return await apiRequest(`/organizations/${organizationId}`, {
        method: 'DELETE'
    });
}

async function listOrganizationMembers(organizationId) {
    return await apiRequest(`/organizations/${organizationId}/members`);
}

async function addOrganizationMember(organizationId, userId, roleId = null) {
    return await apiRequest(`/organizations/${organizationId}/members`, {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, role_id: roleId })
    });
}

async function removeOrganizationMember(organizationId, userId) {
    return await apiRequest(`/organizations/${organizationId}/members/${userId}`, {
        method: 'DELETE'
    });
}

// ============================================================================
// Team API Functions
// ============================================================================

async function listTeams(organizationId) {
    return await apiRequest(`/organizations/${organizationId}/teams`);
}

async function getTeam(teamId) {
    return await apiRequest(`/teams/${teamId}`);
}

async function createTeam(organizationId, data) {
    return await apiRequest(`/organizations/${organizationId}/teams`, {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

async function updateTeam(teamId, data) {
    return await apiRequest(`/teams/${teamId}`, {
        method: 'PATCH',
        body: JSON.stringify(data)
    });
}

async function deleteTeam(teamId) {
    return await apiRequest(`/teams/${teamId}`, {
        method: 'DELETE'
    });
}

async function listTeamMembers(teamId) {
    return await apiRequest(`/teams/${teamId}/members`);
}

async function addTeamMember(teamId, userId, roleId = null) {
    return await apiRequest(`/teams/${teamId}/members`, {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, role_id: roleId })
    });
}

async function removeTeamMember(teamId, userId) {
    return await apiRequest(`/teams/${teamId}/members/${userId}`, {
        method: 'DELETE'
    });
}

// ============================================================================
// Role API Functions
// ============================================================================

async function listRoles(organizationId) {
    return await apiRequest(`/organizations/${organizationId}/roles`);
}

async function getRole(roleId) {
    return await apiRequest(`/roles/${roleId}`);
}

async function createRole(organizationId, data) {
    return await apiRequest(`/organizations/${organizationId}/roles`, {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

async function updateRole(roleId, data) {
    return await apiRequest(`/roles/${roleId}`, {
        method: 'PATCH',
        body: JSON.stringify(data)
    });
}

async function deleteRole(roleId) {
    return await apiRequest(`/roles/${roleId}`, {
        method: 'DELETE'
    });
}

// ============================================================================
// Organization Context Management
// ============================================================================

function getCurrentOrganizationId() {
    return parseInt(localStorage.getItem('currentOrganizationId') || '0');
}

function setCurrentOrganizationId(organizationId) {
    localStorage.setItem('currentOrganizationId', organizationId);
}

// Switch organization (if session-based auth is available)
async function switchOrganization(organizationId) {
    try {
        const response = await apiRequest('/auth/switch-organization', {
            method: 'POST',
            body: JSON.stringify({ organization_id: organizationId })
        });
        setCurrentOrganizationId(organizationId);
        return response;
    } catch (error) {
        // If session auth is not available, just set in localStorage
        console.warn('Session-based organization switch failed, using localStorage:', error);
        setCurrentOrganizationId(organizationId);
        return { success: true, organization_id: organizationId };
    }
}

// ============================================================================
// Utility Functions
// ============================================================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateString) {
    if (!dateString) return '?';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function showError(message) {
    const errorEl = document.getElementById('errorMessage');
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.style.display = 'block';
        setTimeout(() => {
            hideError();
        }, 5000);
    } else {
        alert('Error: ' + message);
    }
}

function hideError() {
    const errorEl = document.getElementById('errorMessage');
    if (errorEl) {
        errorEl.style.display = 'none';
    }
}

function showSuccess(message) {
    // Simple success notification
    alert(message);
}
