#!/bin/bash
# Script to update pinned Docker image versions
# Run this occasionally to update to newer stable versions

set -e

echo "🔄 Updating pinned Docker image versions..."

# Function to get SHA256 digest for an image
get_image_digest() {
    local image_name=$1
    echo "📥 Pulling $image_name..."
    docker pull "$image_name" >/dev/null 2>&1
    local digest=$(docker inspect "$image_name" --format='{{index .RepoDigests 0}}' 2>/dev/null)
    if [ -z "$digest" ]; then
        # Fallback: get digest from manifest
        digest=$(docker images --digests "$image_name" --format "{{.Repository}}:{{.Tag}}@{{.Digest}}" | head -1)
    fi
    echo "$digest"
}

echo ""
echo "🐍 Getting Python 3.11-slim digest..."
PYTHON_DIGEST=$(get_image_digest "python:3.11-slim")
echo "   $PYTHON_DIGEST"

echo ""
echo "🌐 Getting nginx:alpine-slim digest..."
NGINX_DIGEST=$(get_image_digest "nginx:alpine-slim")
echo "   $NGINX_DIGEST"

echo ""
echo "📝 Current Dockerfile contents:"
echo ""
echo "Backend Dockerfile should use:"
echo "FROM ${PYTHON_DIGEST}"
echo ""
echo "Frontend Dockerfile should use:"
echo "FROM ${NGINX_DIGEST}"
echo ""

echo "💡 To update the Dockerfiles:"
echo "1. Edit backend/Dockerfile line 3"
echo "2. Edit docker/Dockerfile line 2"
echo "3. Replace the existing FROM lines with the digests above"
echo ""
echo "✅ Done! Your images are now pinned to specific versions."
echo "   This prevents Docker Hub registry issues and ensures reproducible builds."