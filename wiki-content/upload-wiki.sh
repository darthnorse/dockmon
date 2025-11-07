#!/bin/bash
#
# DockMon Wiki Upload Script
# This script clones the wiki repository and uploads all prepared content
#

set -e  # Exit on error

WIKI_REPO="https://github.com/darthnorse/dockmon.wiki.git"
WIKI_DIR="/tmp/dockmon-wiki"
CONTENT_DIR="$(dirname "$0")"

echo "========================================="
echo "DockMon Wiki Upload Script"
echo "========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "$CONTENT_DIR/Home.md" ]; then
    echo "ERROR: Home.md not found in current directory"
    echo "Please run this script from the wiki-content directory"
    exit 1
fi

echo "📁 Content directory: $CONTENT_DIR"
echo "📦 Wiki repository: $WIKI_REPO"
echo ""

# Clean up any existing wiki directory
if [ -d "$WIKI_DIR" ]; then
    echo "🧹 Removing existing wiki directory..."
    rm -rf "$WIKI_DIR"
fi

# Clone the wiki repository
echo "📥 Cloning wiki repository..."
if ! git clone "$WIKI_REPO" "$WIKI_DIR"; then
    echo ""
    echo "========================================="
    echo "⚠️  WIKI NOT INITIALIZED YET"
    echo "========================================="
    echo ""
    echo "The wiki repository doesn't exist yet. You need to:"
    echo ""
    echo "1. Go to: https://github.com/darthnorse/dockmon/wiki"
    echo "2. Click the 'Create the first page' button"
    echo "3. Title: Home"
    echo "4. Content: (anything, we'll replace it)"
    echo "5. Save"
    echo ""
    echo "Then run this script again!"
    echo ""
    exit 1
fi

echo "✅ Wiki repository cloned successfully"
echo ""

# Copy all markdown files
echo "📋 Copying wiki content..."
cp -v "$CONTENT_DIR"/*.md "$WIKI_DIR/"
echo ""

# Change to wiki directory
cd "$WIKI_DIR"

# Configure git if needed
if [ -z "$(git config user.name)" ]; then
    echo "⚙️  Configuring git..."
    git config user.name "$(git config --global user.name || echo "DockMon Bot")"
    git config user.email "$(git config --global user.email || echo "bot@dockmon.local")"
fi

# Add all files
echo "➕ Adding files to git..."
git add .

# Show what will be committed
echo ""
echo "📝 Files to be uploaded:"
git status --short
echo ""

# Commit
echo "💾 Committing changes..."
git commit -m "Update wiki documentation - complete overhaul with new structure" || {
    echo "⚠️  No changes to commit (wiki already up to date)"
    cd - > /dev/null
    rm -rf "$WIKI_DIR"
    exit 0
}

# Push
echo ""
echo "🚀 Pushing to GitHub..."
if git push origin master; then
    echo ""
    echo "========================================="
    echo "✅ SUCCESS!"
    echo "========================================="
    echo ""
    echo "Wiki has been updated successfully!"
    echo ""
    echo "View at: https://github.com/darthnorse/dockmon/wiki"
    echo ""
else
    echo ""
    echo "========================================="
    echo "❌ PUSH FAILED"
    echo "========================================="
    echo ""
    echo "Possible reasons:"
    echo "1. Authentication failed (check GitHub credentials)"
    echo "2. No write permission to repository"
    echo "3. Network issues"
    echo ""
    echo "Try:"
    echo "1. Check: git remote -v"
    echo "2. Verify: GitHub access token or SSH key"
    echo "3. Manual push from: $WIKI_DIR"
    echo ""
    exit 1
fi

# Clean up
cd - > /dev/null
rm -rf "$WIKI_DIR"

echo "🧹 Cleaned up temporary files"
echo ""
echo "Done! 🎉"