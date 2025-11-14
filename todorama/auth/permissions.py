"""
Permission constants and utilities for RBAC system.
"""
import json
import logging
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger(__name__)

# Permission constants
TASK_CREATE = "TASK_CREATE"
TASK_UPDATE = "TASK_UPDATE"
TASK_DELETE = "TASK_DELETE"
TASK_VIEW = "TASK_VIEW"

PROJECT_CREATE = "PROJECT_CREATE"
PROJECT_UPDATE = "PROJECT_UPDATE"
PROJECT_DELETE = "PROJECT_DELETE"
PROJECT_VIEW = "PROJECT_VIEW"

ORGANIZATION_CREATE = "ORGANIZATION_CREATE"
ORGANIZATION_UPDATE = "ORGANIZATION_UPDATE"
ORGANIZATION_DELETE = "ORGANIZATION_DELETE"
ORGANIZATION_VIEW = "ORGANIZATION_VIEW"
ORGANIZATION_MANAGE = "ORGANIZATION_MANAGE"

TEAM_CREATE = "TEAM_CREATE"
TEAM_UPDATE = "TEAM_UPDATE"
TEAM_DELETE = "TEAM_DELETE"
TEAM_VIEW = "TEAM_VIEW"
TEAM_MANAGE = "TEAM_MANAGE"

ROLE_CREATE = "ROLE_CREATE"
ROLE_UPDATE = "ROLE_UPDATE"
ROLE_DELETE = "ROLE_DELETE"
ROLE_VIEW = "ROLE_VIEW"
ROLE_MANAGE = "ROLE_MANAGE"

ADMIN = "ADMIN"  # Super permission - grants all permissions

# All permissions list
ALL_PERMISSIONS = [
    TASK_CREATE, TASK_UPDATE, TASK_DELETE, TASK_VIEW,
    PROJECT_CREATE, PROJECT_UPDATE, PROJECT_DELETE, PROJECT_VIEW,
    ORGANIZATION_CREATE, ORGANIZATION_UPDATE, ORGANIZATION_DELETE, ORGANIZATION_VIEW, ORGANIZATION_MANAGE,
    TEAM_CREATE, TEAM_UPDATE, TEAM_DELETE, TEAM_VIEW, TEAM_MANAGE,
    ROLE_CREATE, ROLE_UPDATE, ROLE_DELETE, ROLE_VIEW, ROLE_MANAGE,
    ADMIN
]

# Role hierarchy (higher roles inherit permissions from lower roles)
ROLE_HIERARCHY = {
    "admin": ["admin", "manager", "member"],
    "manager": ["manager", "member"],
    "member": ["member"]
}


def parse_permissions(permissions_json: str) -> Set[str]:
    """
    Parse permissions from JSON string.
    
    Args:
        permissions_json: JSON string containing permissions array
        
    Returns:
        Set of permission strings
    """
    try:
        permissions_data = json.loads(permissions_json)
        if isinstance(permissions_data, list):
            return set(permissions_data)
        elif isinstance(permissions_data, dict):
            # Support dict format with permissions key
            return set(permissions_data.get("permissions", []))
        else:
            logger.warning(f"Unexpected permissions format: {permissions_json}")
            return set()
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse permissions JSON: {e}")
        return set()


def has_permission(user_permissions: Set[str], required_permission: str) -> bool:
    """
    Check if user has the required permission.
    ADMIN permission grants all permissions.
    
    Args:
        user_permissions: Set of user's permissions
        required_permission: Permission to check
        
    Returns:
        True if user has permission, False otherwise
    """
    if ADMIN in user_permissions:
        return True
    return required_permission in user_permissions


def get_user_permissions_from_roles(roles: List[Dict[str, Any]]) -> Set[str]:
    """
    Extract all permissions from a list of roles.
    
    Args:
        roles: List of role dictionaries with 'permissions' field (JSON string)
        
    Returns:
        Set of all unique permissions
    """
    all_permissions = set()
    for role in roles:
        if role and "permissions" in role:
            permissions = parse_permissions(role["permissions"])
            all_permissions.update(permissions)
    return all_permissions


def check_role_hierarchy(role_name: str, required_role: str) -> bool:
    """
    Check if a role has sufficient hierarchy level.
    
    Args:
        role_name: Name of the role to check
        required_role: Required role level (admin, manager, member)
        
    Returns:
        True if role_name has sufficient hierarchy, False otherwise
    """
    role_name_lower = role_name.lower()
    required_role_lower = required_role.lower()
    
    if role_name_lower not in ROLE_HIERARCHY:
        return False
    
    return required_role_lower in ROLE_HIERARCHY[role_name_lower]
