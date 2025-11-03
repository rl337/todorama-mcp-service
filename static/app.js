// Configuration
const API_BASE_URL = window.location.origin;
const PAGE_SIZE = 50;

// State
let currentPage = 1;
let totalTasks = 0;
let allTasks = [];
let filteredTasks = [];
let currentSort = { field: null, direction: 'asc' };
let apiKey = localStorage.getItem('apiKey') || '';

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    
    // Set default date range to past week
    const today = new Date();
    const weekAgo = new Date(today);
    weekAgo.setDate(today.getDate() - 7);
    
    document.getElementById('createdDateFrom').valueAsDate = weekAgo;
    document.getElementById('createdDateTo').valueAsDate = today;
    
    loadTasks();
    
    // Check for API key in URL params
    const urlParams = new URLSearchParams(window.location.search);
    const keyParam = urlParams.get('api_key');
    if (keyParam) {
        apiKey = keyParam;
        localStorage.setItem('apiKey', apiKey);
        window.history.replaceState({}, document.title, window.location.pathname);
    }
});

// Setup event listeners
function setupEventListeners() {
    // Header buttons
    document.getElementById('refreshBtn').addEventListener('click', () => {
        loadTasks();
    });
    document.getElementById('createTaskBtn').addEventListener('click', () => {
        openCreateModal();
    });

    // Filter controls
    document.getElementById('applyFiltersBtn').addEventListener('click', applyFilters);
    document.getElementById('clearFiltersBtn').addEventListener('click', clearFilters);
    document.getElementById('exportBtn').addEventListener('click', exportJSON);
    document.getElementById('exportCsvBtn').addEventListener('click', exportCSV);
    
    // Search
    document.getElementById('searchInput').addEventListener('input', debounce(applyFilters, 300));

    // Pagination
    document.getElementById('prevPage').addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            renderTasks();
        }
    });
    document.getElementById('nextPage').addEventListener('click', () => {
        const maxPage = Math.ceil(filteredTasks.length / PAGE_SIZE);
        if (currentPage < maxPage) {
            currentPage++;
            renderTasks();
        }
    });

    // Table header sorting
    document.querySelectorAll('th[data-sort]').forEach(header => {
        header.addEventListener('click', () => {
            const field = header.getAttribute('data-sort');
            sortTasks(field);
        });
    });

    // Create task form
    document.getElementById('createTaskForm').addEventListener('submit', createTask);

    // Close modals on outside click
    document.getElementById('createTaskModal').addEventListener('click', (e) => {
        if (e.target.id === 'createTaskModal') {
            closeCreateModal();
        }
    });
    document.getElementById('taskDetailsModal').addEventListener('click', (e) => {
        if (e.target.id === 'taskDetailsModal') {
            closeTaskDetailsModal();
        }
    });
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
        showError(error.message);
        throw error;
    }
}

// Load tasks
async function loadTasks() {
    showLoading();
    hideError();
    
    try {
        const tasks = await apiRequest('/tasks?limit=10000');
        allTasks = Array.isArray(tasks) ? tasks : [];
        filteredTasks = [...allTasks];
        totalTasks = allTasks.length;
        currentPage = 1;
        applyFilters();
    } catch (error) {
        console.error('Failed to load tasks:', error);
    } finally {
        hideLoading();
    }
}

// Apply filters
function applyFilters() {
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    const statusFilter = Array.from(document.getElementById('statusFilter').selectedOptions).map(o => o.value);
    const typeFilter = Array.from(document.getElementById('typeFilter').selectedOptions).map(o => o.value);
    const priorityFilter = Array.from(document.getElementById('priorityFilter').selectedOptions).map(o => o.value);
    const agentFilter = document.getElementById('agentFilter').value.toLowerCase();
    const projectFilter = document.getElementById('projectFilter').value;
    const createdFrom = document.getElementById('createdDateFrom').value;
    const createdTo = document.getElementById('createdDateTo').value;

    filteredTasks = allTasks.filter(task => {
        // Search filter
        if (searchTerm) {
            const matchesTitle = task.title?.toLowerCase().includes(searchTerm);
            const matchesId = task.id.toString().includes(searchTerm);
            if (!matchesTitle && !matchesId) return false;
        }

        // Status filter
        if (statusFilter.length > 0 && !statusFilter.includes(task.task_status)) {
            return false;
        }

        // Type filter
        if (typeFilter.length > 0 && !typeFilter.includes(task.task_type)) {
            return false;
        }

        // Priority filter
        if (priorityFilter.length > 0 && !priorityFilter.includes(task.priority)) {
            return false;
        }

        // Agent filter
        if (agentFilter && (!task.assigned_agent || !task.assigned_agent.toLowerCase().includes(agentFilter))) {
            return false;
        }

        // Project filter
        if (projectFilter && task.project_id !== parseInt(projectFilter)) {
            return false;
        }

        // Date filters
        if (createdFrom) {
            const taskCreated = new Date(task.created_at);
            const filterFrom = new Date(createdFrom);
            if (taskCreated < filterFrom) return false;
        }

        if (createdTo) {
            const taskCreated = new Date(task.created_at);
            const filterTo = new Date(createdTo);
            filterTo.setHours(23, 59, 59, 999); // End of day
            if (taskCreated > filterTo) return false;
        }

        return true;
    });

    currentPage = 1;
    renderTasks();
}

// Clear filters
function clearFilters() {
    document.getElementById('searchInput').value = '';
    document.getElementById('statusFilter').selectedIndex = -1;
    document.getElementById('typeFilter').selectedIndex = -1;
    document.getElementById('priorityFilter').selectedIndex = -1;
    document.getElementById('agentFilter').value = '';
    document.getElementById('projectFilter').value = '';
    document.getElementById('createdDateFrom').value = '';
    document.getElementById('createdDateTo').value = '';
    applyFilters();
}

// Sort tasks
function sortTasks(field) {
    if (currentSort.field === field) {
        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
    } else {
        currentSort.field = field;
        currentSort.direction = 'asc';
    }

    filteredTasks.sort((a, b) => {
        let aVal = a[field];
        let bVal = b[field];

        // Handle null/undefined
        if (aVal == null) aVal = '';
        if (bVal == null) bVal = '';

        // Handle dates
        if (field.includes('_at') || field.includes('date')) {
            aVal = new Date(aVal);
            bVal = new Date(bVal);
        }

        // Handle strings
        if (typeof aVal === 'string') {
            aVal = aVal.toLowerCase();
            bVal = bVal.toLowerCase();
        }

        let comparison = 0;
        if (aVal < bVal) comparison = -1;
        if (aVal > bVal) comparison = 1;

        return currentSort.direction === 'asc' ? comparison : -comparison;
    });

    // Update sort indicators
    document.querySelectorAll('th[data-sort]').forEach(header => {
        header.removeAttribute('data-sort-asc');
        header.removeAttribute('data-sort-desc');
        if (header.getAttribute('data-sort') === field) {
            header.setAttribute(`data-sort-${currentSort.direction}`, '');
        }
    });

    renderTasks();
}

// Render tasks table
function renderTasks() {
    const tbody = document.getElementById('tasksTableBody');
    tbody.innerHTML = '';

    const startIndex = (currentPage - 1) * PAGE_SIZE;
    const endIndex = startIndex + PAGE_SIZE;
    const pageTasks = filteredTasks.slice(startIndex, endIndex);

    if (pageTasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 40px;">No tasks found</td></tr>';
        updatePagination();
        return;
    }

    pageTasks.forEach(task => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${task.id}</td>
            <td>${escapeHtml(task.title || '')}</td>
            <td>${getTypeBadge(task.task_type)}</td>
            <td>${getStatusBadge(task.task_status)}</td>
            <td>${getPriorityBadge(task.priority)}</td>
            <td>${task.assigned_agent || '?'}</td>
            <td>${formatDate(task.created_at)}</td>
            <td>${formatDate(task.updated_at)}</td>
            <td class="actions-cell">
                <button class="btn btn-small btn-secondary" onclick="viewTaskDetails(${task.id})">View</button>
                ${task.task_status === 'in_progress' ? 
                    `<button class="btn btn-small btn-success" onclick="completeTask(${task.id})">Complete</button>
                     <button class="btn btn-small btn-warning" onclick="unlockTask(${task.id})">Unlock</button>` : 
                    ''}
            </td>
        `;
        tbody.appendChild(row);
    });

    updatePagination();
    updateTaskCount();
}

// Update pagination controls
function updatePagination() {
    const maxPage = Math.ceil(filteredTasks.length / PAGE_SIZE);
    document.getElementById('pageInfo').textContent = `Page ${currentPage} of ${maxPage || 1}`;
    document.getElementById('prevPage').disabled = currentPage === 1;
    document.getElementById('nextPage').disabled = currentPage >= maxPage;
}

// Update task count
function updateTaskCount() {
    const count = filteredTasks.length;
    document.getElementById('taskCount').textContent = `${count} task${count !== 1 ? 's' : ''}`;
}

// Badge helpers
function getStatusBadge(status) {
    const labels = {
        'available': 'Available',
        'in_progress': 'In Progress',
        'complete': 'Complete',
        'blocked': 'Blocked',
        'cancelled': 'Cancelled'
    };
    return `<span class="status-badge status-${status}">${labels[status] || status}</span>`;
}

function getPriorityBadge(priority) {
    const labels = {
        'low': 'Low',
        'medium': 'Medium',
        'high': 'High',
        'critical': 'Critical'
    };
    return `<span class="priority-badge priority-${priority || 'medium'}">${labels[priority] || priority || 'Medium'}</span>`;
}

function getTypeBadge(type) {
    const labels = {
        'concrete': 'Concrete',
        'abstract': 'Abstract',
        'epic': 'Epic'
    };
    return `<span class="type-badge type-${type}">${labels[type] || type}</span>`;
}

// Format date
function formatDate(dateString) {
    if (!dateString) return '?';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// View task details
async function viewTaskDetails(taskId) {
    showLoading();
    try {
        const task = await apiRequest(`/tasks/${taskId}`);
        
        // Get comments
        let comments = [];
        try {
            comments = await apiRequest(`/tasks/${taskId}/comments`);
        } catch (e) {
            console.warn('Could not load comments:', e);
        }

        const content = document.getElementById('taskDetailsContent');
        content.innerHTML = `
            <div class="task-details">
                <div class="detail-section">
                    <h3>Basic Information</h3>
                    <div class="detail-row">
                        <span class="detail-label">ID:</span>
                        <span class="detail-value">${task.id}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Title:</span>
                        <span class="detail-value">${escapeHtml(task.title || '')}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Type:</span>
                        <span class="detail-value">${getTypeBadge(task.task_type)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Status:</span>
                        <span class="detail-value">${getStatusBadge(task.task_status)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Priority:</span>
                        <span class="detail-value">${getPriorityBadge(task.priority)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Assigned Agent:</span>
                        <span class="detail-value">${task.assigned_agent || '?'}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Project ID:</span>
                        <span class="detail-value">${task.project_id || '?'}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Created:</span>
                        <span class="detail-value">${formatDate(task.created_at)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Updated:</span>
                        <span class="detail-value">${formatDate(task.updated_at)}</span>
                    </div>
                    ${task.completed_at ? `
                    <div class="detail-row">
                        <span class="detail-label">Completed:</span>
                        <span class="detail-value">${formatDate(task.completed_at)}</span>
                    </div>
                    ` : ''}
                </div>
                <div class="detail-section">
                    <h3>Task Instruction</h3>
                    <pre>${escapeHtml(task.task_instruction || '')}</pre>
                </div>
                <div class="detail-section">
                    <h3>Verification Instruction</h3>
                    <pre>${escapeHtml(task.verification_instruction || '')}</pre>
                </div>
                ${task.notes ? `
                <div class="detail-section">
                    <h3>Notes</h3>
                    <pre>${escapeHtml(task.notes)}</pre>
                </div>
                ` : ''}
                ${comments.length > 0 ? `
                <div class="detail-section">
                    <h3>Comments (${comments.length})</h3>
                    ${comments.map(c => `
                        <div class="detail-row">
                            <div>
                                <strong>${escapeHtml(c.agent_id || 'Unknown')}</strong> - ${formatDate(c.created_at)}
                                <pre style="margin-top: 5px;">${escapeHtml(c.content || '')}</pre>
                            </div>
                        </div>
                    `).join('')}
                </div>
                ` : ''}
            </div>
        `;

        document.getElementById('taskDetailsModal').style.display = 'flex';
    } catch (error) {
        console.error('Failed to load task details:', error);
    } finally {
        hideLoading();
    }
}

// Close task details modal
function closeTaskDetailsModal() {
    document.getElementById('taskDetailsModal').style.display = 'none';
}

// Create task modal
function openCreateModal() {
    document.getElementById('createTaskForm').reset();
    document.getElementById('createTaskModal').style.display = 'flex';
}

function closeCreateModal() {
    document.getElementById('createTaskModal').style.display = 'none';
}

// Create task
async function createTask(e) {
    e.preventDefault();
    
    const taskData = {
        title: document.getElementById('taskTitle').value,
        task_type: document.getElementById('taskType').value,
        task_instruction: document.getElementById('taskInstruction').value,
        verification_instruction: document.getElementById('taskVerification').value,
        priority: document.getElementById('taskPriority').value,
        notes: document.getElementById('taskNotes').value || null
    };

    const projectId = document.getElementById('taskProjectId').value;
    if (projectId) {
        taskData.project_id = parseInt(projectId);
    }

    try {
        await apiRequest('/tasks', {
            method: 'POST',
            body: JSON.stringify(taskData)
        });
        
        closeCreateModal();
        loadTasks();
        showSuccess('Task created successfully!');
    } catch (error) {
        console.error('Failed to create task:', error);
    }
}

// Complete task
async function completeTask(taskId) {
    if (!confirm('Are you sure you want to mark this task as complete?')) {
        return;
    }

    try {
        await apiRequest(`/tasks/${taskId}/complete`, {
            method: 'POST',
            body: JSON.stringify({ notes: 'Completed via web interface' })
        });
        loadTasks();
        showSuccess('Task marked as complete!');
    } catch (error) {
        console.error('Failed to complete task:', error);
    }
}

// Unlock task
async function unlockTask(taskId) {
    if (!confirm('Are you sure you want to unlock this task?')) {
        return;
    }

    try {
        await apiRequest(`/tasks/${taskId}/unlock`, {
            method: 'POST'
        });
        loadTasks();
        showSuccess('Task unlocked!');
    } catch (error) {
        console.error('Failed to unlock task:', error);
    }
}

// Export functions
function exportJSON() {
    const dataStr = JSON.stringify(filteredTasks, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `tasks_${new Date().toISOString().split('T')[0]}.json`;
    link.click();
    URL.revokeObjectURL(url);
}

function exportCSV() {
    const headers = ['ID', 'Title', 'Type', 'Status', 'Priority', 'Assigned Agent', 'Project ID', 'Created', 'Updated'];
    const rows = filteredTasks.map(task => [
        task.id,
        `"${(task.title || '').replace(/"/g, '""')}"`,
        task.task_type,
        task.task_status,
        task.priority || 'medium',
        task.assigned_agent || '',
        task.project_id || '',
        task.created_at || '',
        task.updated_at || ''
    ]);

    const csv = [
        headers.join(','),
        ...rows.map(row => row.join(','))
    ].join('\n');

    const dataBlob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `tasks_${new Date().toISOString().split('T')[0]}.csv`;
    link.click();
    URL.revokeObjectURL(url);
}

// UI helpers
function showLoading() {
    document.getElementById('loadingIndicator').style.display = 'block';
}

function hideLoading() {
    document.getElementById('loadingIndicator').style.display = 'none';
}

function showError(message) {
    const errorEl = document.getElementById('errorMessage');
    errorEl.textContent = message;
    errorEl.style.display = 'block';
    setTimeout(() => {
        hideError();
    }, 5000);
}

function hideError() {
    document.getElementById('errorMessage').style.display = 'none';
}

function showSuccess(message) {
    // Simple success notification (could be enhanced with a toast library)
    alert(message);
}

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
