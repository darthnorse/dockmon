# DockMon Agent v2.2.0 - Build and Distribution

**Date:** October 31, 2025

## Overview

The DockMon Agent is distributed as a Docker container image via GitHub Container Registry (GHCR). The build process uses GitHub Actions to create multi-architecture images for both AMD64 and ARM64.

## Distribution

### Published Images

Once the workflow runs, images will be available at:
```
ghcr.io/darthnorse/dockmon-agent:latest
ghcr.io/darthnorse/dockmon-agent:2.2.0
ghcr.io/darthnorse/dockmon-agent:2.2
ghcr.io/darthnorse/dockmon-agent:2
```

### Supported Architectures

- `linux/amd64` - Intel/AMD 64-bit
- `linux/arm64` - ARM 64-bit (Raspberry Pi 4+, AWS Graviton, etc.)

## GitHub Actions Workflow

### Workflow File

`.github/workflows/build-agent.yml`

### Triggers

The workflow runs on:
- **Tag push** (v*) - Creates versioned releases
- **Push to main** - Creates latest/edge builds
- **Pull requests** - Builds but doesn't push (validation only)
- **Manual dispatch** - Can be triggered manually from GitHub Actions UI

### Build Process

1. **Checkout repository** - Clones the full repo (includes agent/ and shared/ directories)
2. **Setup QEMU** - Enables multi-architecture emulation
3. **Setup Docker Buildx** - Enables advanced Docker build features
4. **Login to GHCR** - Authenticates with GitHub Container Registry
5. **Extract metadata** - Generates tags and labels
6. **Build and push** - Builds for both amd64 and arm64, pushes to GHCR

### Build Arguments

- `VERSION` - Set from git tag or branch name
- `COMMIT` - Set from git SHA

## Dockerfile Structure

### Dockerfile.multiarch

Located at `agent/Dockerfile.multiarch`, this Dockerfile:

1. **Build Stage:**
   - Uses `golang:1.21-alpine` as base
   - Copies both `shared/` and `agent/` directories
   - Adjusts go.mod replace directive for build context
   - Downloads dependencies
   - Builds static binary with version/commit info
   - Supports cross-compilation via TARGETOS/TARGETARCH

2. **Runtime Stage:**
   - Uses `alpine:3.19` as minimal base
   - Installs ca-certificates and tzdata
   - Creates non-root user (UID/GID 1000)
   - Creates `/data` volume for persistent storage
   - Runs as non-root user

## Triggering a Build

### For a Release

1. Tag a release:
   ```bash
   git tag -a v2.2.0 -m "Release v2.2.0"
   git push origin v2.2.0
   ```

2. GitHub Actions will automatically:
   - Build multi-arch images
   - Push to GHCR with tags: `2.2.0`, `2.2`, `2`, `latest`

### For Development/Testing

1. Push to main branch:
   ```bash
   git push origin main
   ```

2. GitHub Actions will build and push with `main` tag

### Manual Trigger

1. Go to GitHub Actions → "Build and Publish DockMon Agent"
2. Click "Run workflow"
3. Select branch and click "Run workflow"

## Local Development

For local development without pushing to registry:

```bash
# Build locally (single architecture)
cd /root/dockmon
docker build -f agent/Dockerfile.multiarch -t dockmon-agent:dev .
```

**Note:** Local builds may encounter issues with the shared module path. For production builds, always use the GitHub Actions workflow.

## Installation Instructions

### For Users

Once the agent is published to GHCR, users can install it with:

```bash
docker run -d \
  --name dockmon-agent \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e DOCKMON_URL=http://YOUR_DOCKMON_HOST:8080 \
  -e REGISTRATION_TOKEN=<token-from-ui> \
  ghcr.io/darthnorse/dockmon-agent:2.2.0
```

The registration token is generated from the DockMon UI (Agents page → Generate Token).

## Updating the UI

The UI installation command is located in:
- `ui/src/features/agents/components/AgentRegistration.tsx`

Update the image reference if changing the repository or registry.

## CI/CD Integration

### Permissions Required

The workflow requires:
- `contents: read` - To checkout the repository
- `packages: write` - To push to GitHub Container Registry

These are automatically provided via `GITHUB_TOKEN`.

### Registry Authentication

Authentication to GHCR is handled automatically via:
```yaml
username: ${{ github.actor }}
password: ${{ secrets.GITHUB_TOKEN }}
```

No additional secrets need to be configured.

## Troubleshooting

### Build Fails

1. **Go module issues:**
   - Check that both `agent/` and `shared/` directories exist
   - Verify go.mod replace directive in agent/go.mod
   - Ensure Dockerfile.multiarch correctly adjusts the path

2. **Push fails:**
   - Verify repository has packages permission enabled
   - Check GITHUB_TOKEN has `packages: write` permission
   - Ensure the repository is not archived

### Image Pull Fails

1. **Authentication:**
   ```bash
   docker login ghcr.io -u USERNAME
   ```
   Use a GitHub Personal Access Token with `read:packages` scope

2. **Image not found:**
   - Check that the workflow completed successfully
   - Verify the tag exists: https://github.com/darthnorse/dockmon/pkgs/container/dockmon-agent

3. **Architecture mismatch:**
   - The workflow builds for both amd64 and arm64
   - Docker should automatically pull the correct architecture
   - Force a specific arch: `docker pull --platform linux/amd64 ghcr.io/darthnorse/dockmon-agent:latest`

## Version Management

### Semantic Versioning

Follow semantic versioning for releases:
- `v2.2.0` - Full version
- `v2.2.1` - Patch release
- `v2.3.0` - Minor version
- `v3.0.0` - Major version

### Tags Generated

For tag `v2.2.0`, the following image tags are created:
- `2.2.0` - Exact version
- `2.2` - Minor version (updated with patches)
- `2` - Major version (updated with minors)
- `latest` - Latest stable release
- `sha-abc123f` - Git commit SHA

## Future Improvements

1. **Binary artifacts** - Upload compiled binaries as GitHub release assets
2. **Signature verification** - Sign images with cosign
3. **SBOM generation** - Generate Software Bill of Materials
4. **Vulnerability scanning** - Integrate Trivy or similar
5. **Multi-registry** - Also push to Docker Hub
6. **Release notes** - Auto-generate from commits

## Current Status

- ✅ Workflow created (`.github/workflows/build-agent.yml`)
- ✅ Multi-arch Dockerfile created (`agent/Dockerfile.multiarch`)
- ✅ UI updated with correct image path
- ⏳ Workflow not yet executed (needs push to GitHub)
- ⏳ Images not yet published to GHCR

## Next Steps

1. **Commit and push** the workflow files to GitHub
2. **Tag a release** (v2.2.0)
3. **Verify workflow** runs successfully
4. **Test agent installation** using published image
5. **Update documentation** with actual GHCR URLs

---

**Note:** Until the workflow runs and publishes images to GHCR, users cannot install the agent. The UI will show the installation command, but the image will not be pullable.
