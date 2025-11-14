#!/bin/bash
# Setup script for creating GitHub repository

set -e

echo "🚀 Setting up TODO MCP Service repository"

# Check if gh CLI is available
if command -v gh &> /dev/null; then
    echo "GitHub CLI found. Creating repository..."
    
    # Check if already authenticated
    if ! gh auth status &>/dev/null; then
        echo "Please authenticate with GitHub:"
        gh auth login
    fi
    
    # Create public repository
    REPO_NAME="todorama-mcp-service"
    echo "Creating public repository: $REPO_NAME"
    
    gh repo create "$REPO_NAME" \
        --public \
        --description "Standalone SQLite-based task management service for AI agents with MCP API support" \
        --source=. \
        --remote=origin \
        --push || echo "Repository may already exist"
    
    echo "✅ Repository created: https://github.com/$(gh api user --jq .login)/$REPO_NAME"
else
    echo "⚠️  GitHub CLI (gh) not found."
    echo ""
    echo "To create the repository manually:"
    echo "1. Go to https://github.com/new"
    echo "2. Create a new public repository named 'todorama-mcp-service'"
    echo "3. Do NOT initialize with README, .gitignore, or license"
    echo "4. Then run:"
    echo "   git remote add origin https://github.com/YOUR_USERNAME/todorama-mcp-service.git"
    echo "   git branch -M main"
    echo "   git push -u origin main"
fi

