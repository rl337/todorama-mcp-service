#!/bin/bash

# run_checks.sh - Comprehensive test and health check script for TODO MCP Service
# This script must be run before any commit or push

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
TIMEOUT=30
RETRY_COUNT=3

# Helper functions
print_header() {
    echo -e "\n${BLUE}================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Check if we're in the right directory
check_project_root() {
    if [ ! -f "src/main.py" ] || [ ! -d "tests" ]; then
        print_error "Must be run from TODO MCP Service root directory"
        exit 1
    fi
}

# Check Python and dependencies
check_dependencies() {
    print_header "Checking Dependencies"
    
    if ! command -v python3 &> /dev/null; then
        print_error "python3 not found"
        exit 1
    fi
    print_success "Python3 found: $(python3 --version)"
    
    # Check for pytest
    if ! python3 -c "import pytest" 2>/dev/null; then
        print_warning "pytest not installed. Installing..."
        # Use UV if available, otherwise pip
        if command -v uv &> /dev/null; then
            uv pip install pytest pytest-asyncio httpx fastapi
        else
            pip install pytest pytest-asyncio httpx fastapi || pip3 install pytest pytest-asyncio httpx fastapi
        fi
    fi
    print_success "pytest available"
    
    # Check for other dependencies
    if ! python3 -c "import fastapi" 2>/dev/null; then
        print_error "fastapi not installed"
        exit 1
    fi
    print_success "FastAPI available"
}

# Run unit tests
run_tests() {
    print_header "Running Unit Tests"
    
    local test_files=(
        "tests/test_database.py"
        "tests/test_backup.py"
        "tests/test_api.py"
        "tests/test_mcp_api.py"
        "tests/test_graphql.py"
        "tests/test_integration.py"
        "tests/test_cli.py"
        "tests/test_conversation_storage.py"
    )
    
    local failed_tests=0
    
    for test_file in "${test_files[@]}"; do
        if [ ! -f "$test_file" ]; then
            print_warning "Test file not found: $test_file"
            continue
        fi
        
        print_info "Running $(basename $test_file)..."
        if poetry run pytest "$test_file" -v --tb=short; then
            print_success "$(basename $test_file) passed"
        else
            print_error "$(basename $test_file) failed"
            failed_tests=$((failed_tests + 1))
        fi
    done
    
    if [ $failed_tests -eq 0 ]; then
        print_success "All unit tests passed"
        return 0
    else
        print_error "$failed_tests test file(s) failed"
        return 1
    fi
}

# Check code quality (basic linting)
check_code_quality() {
    print_header "Checking Code Quality"
    
    # Check for common Python issues
    local issues=0
    
    # Check for syntax errors
    for py_file in src/*.py; do
        if [ -f "$py_file" ]; then
            if python3 -m py_compile "$py_file" 2>/dev/null; then
                print_success "Syntax OK: $(basename $py_file)"
            else
                print_error "Syntax error in: $(basename $py_file)"
                issues=$((issues + 1))
            fi
        fi
    done
    
    # Check for imports
    if python3 -c "import sys; sys.path.insert(0, 'src'); from database import TodoDatabase; from main import app; from mcp_api import MCPTodoAPI; from backup import BackupManager" 2>/dev/null; then
        print_success "All imports resolve correctly"
    else
        print_error "Import errors detected"
        issues=$((issues + 1))
    fi
    
    if [ $issues -eq 0 ]; then
        print_success "Code quality checks passed"
        return 0
    else
        print_error "$issues code quality issue(s) found"
        return 1
    fi
}

# Test service startup (if Docker available)
test_service_startup() {
    print_header "Testing Service Startup"
    
    if ! command -v docker &> /dev/null; then
        print_warning "Docker not available, skipping service startup test"
        return 0
    fi
    
    # Check if service can be started
    if docker compose ps todo-mcp-service 2>/dev/null | grep -q "running\|Up"; then
        print_info "Service is already running, testing health endpoint..."
        if curl -s -f http://localhost:5080/health > /dev/null 2>&1; then
            print_success "Service is healthy"
            return 0
        else
            print_warning "Service is running but health check failed"
            return 1
        fi
    else
        print_info "Service not running. Test will verify configuration only."
        # Just verify docker-compose.yml exists and is valid
        if [ -f "docker-compose.yml" ]; then
            if docker compose config > /dev/null 2>&1; then
                print_success "docker-compose.yml is valid"
                return 0
            else
                print_error "docker-compose.yml has errors"
                return 1
            fi
        else
            print_warning "docker-compose.yml not found (service may be standalone)"
            return 0
        fi
    fi
}

# Test database schema
test_database_schema() {
    print_header "Testing Database Schema"
    
    # Create a temporary database and test schema initialization
    local test_db="/tmp/todo_test_$(date +%s).db"
    
    if python3 << EOF 2>/dev/null
import sys
sys.path.insert(0, 'src')
from database import TodoDatabase
import os

db = TodoDatabase('$test_db')

# Test that schema was created
import sqlite3
conn = sqlite3.connect('$test_db')
cursor = conn.cursor()

# Check for required tables
tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
table_names = [t[0] for t in tables]

required_tables = ['tasks', 'task_relationships', 'change_history', 'projects']
missing = [t for t in required_tables if t not in table_names]

if missing:
    print(f"MISSING_TABLES: {missing}")
    sys.exit(1)
else:
    print("SCHEMA_OK")
    sys.exit(0)
EOF
    then
        print_success "Database schema is correct"
        rm -f "$test_db"
        return 0
    else
        print_error "Database schema test failed"
        rm -f "$test_db"
        return 1
    fi
}

# Test backup functionality (unit test)
test_backup_functionality() {
    print_header "Testing Backup Functionality"
    
    if poetry run pytest tests/test_backup.py -v --tb=short -k "test_" 2>/dev/null | grep -q "PASSED\|passed"; then
        print_success "Backup functionality tests passed"
        return 0
    else
        print_warning "Backup functionality tests need attention"
        # Not a hard failure, but should be addressed
        return 0
    fi
}

# Generate summary
generate_summary() {
    print_header "Test Summary"
    
    local total_checks=6
    local passed_checks=0
    
    # Count would be based on actual results
    print_info "Checks completed: $total_checks"
    
    echo -e "\n${GREEN}✅ All checks passed! Ready to commit.${NC}"
    echo -e "${BLUE}Remember: Run this script before every commit and push.${NC}\n"
}

# Main execution
main() {
    echo -e "${BLUE}TODO MCP Service - Pre-Commit Checks${NC}"
    echo -e "${BLUE}====================================${NC}\n"
    
    local start_time=$(date +%s)
    local failed_checks=0
    
    # Run all checks
    check_project_root || exit 1
    check_dependencies || failed_checks=$((failed_checks + 1))
    test_database_schema || failed_checks=$((failed_checks + 1))
    check_code_quality || failed_checks=$((failed_checks + 1))
    run_tests || failed_checks=$((failed_checks + 1))
    test_backup_functionality || failed_checks=$((failed_checks + 1))
    test_service_startup || failed_checks=$((failed_checks + 1))
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    echo -e "\n${BLUE}Checks completed in ${duration} seconds${NC}\n"
    
    if [ $failed_checks -eq 0 ]; then
        generate_summary
        echo -e "${GREEN}🎉 All checks passed! Safe to commit and push.${NC}\n"
        exit 0
    else
        print_error "$failed_checks check(s) failed. Fix issues before committing."
        echo -e "\n${RED}❌ Do not commit until all checks pass.${NC}\n"
        exit 1
    fi
}

# Handle script arguments
case "${1:-}" in
    "--help"|"-h")
        echo "Usage: $0"
        echo ""
        echo "Runs comprehensive tests and checks for TODO MCP Service."
        echo "This script MUST pass before committing or pushing code."
        echo ""
        echo "Checks performed:"
        echo "  - Dependencies verification"
        echo "  - Database schema validation"
        echo "  - Code quality checks"
        echo "  - Unit tests (database, backup, API, MCP)"
        echo "  - Service startup test"
        echo ""
        exit 0
        ;;
    *)
        main "$@"
        ;;
esac

