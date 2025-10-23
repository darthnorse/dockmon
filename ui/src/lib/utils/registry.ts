/**
 * Registry URL Utilities
 *
 * Generate links to container registry pages for different registry providers
 */

/**
 * Get registry URL for a container image
 *
 * @param imageName - Full image name (e.g., "nginx:1.25", "ghcr.io/user/app:latest")
 * @returns URL to the registry page for this image
 */
export function getRegistryUrl(imageName: string): string {
  // Strip digest first (e.g., "image@sha256:abc123..." -> "image")
  let cleanedImage = imageName.split('@')[0] || imageName

  // Then remove tag (e.g., "image:latest" -> "image")
  cleanedImage = cleanedImage.split(':')[0] || cleanedImage

  const parts = cleanedImage.split('/')

  // Check if first part is a registry (contains . or :)
  const hasRegistry = parts.length > 1 && parts[0] && (parts[0].includes('.') || parts[0].includes(':'))

  // Docker Hub official image - ONLY single part names (e.g., "nginx", "redis")
  if (!hasRegistry && parts.length === 1) {
    return `https://hub.docker.com/_/${cleanedImage}`
  }

  // Docker Hub user image - two parts without registry (e.g., "portainer/portainer-ce")
  if (!hasRegistry && parts.length === 2) {
    return `https://hub.docker.com/r/${cleanedImage}`
  }

  const registry = parts[0] || ''
  const imagePath = parts.slice(1).join('/')

  // Linux Server Container Registry (lscr.io)
  if (registry === 'lscr.io') {
    // lscr.io/linuxserver/qbittorrent -> hub.docker.com/r/linuxserver/qbittorrent
    // imagePath already includes the full path (e.g., "linuxserver/qbittorrent")
    return `https://hub.docker.com/r/${imagePath}`
  }

  // GitHub Container Registry
  if (registry === 'ghcr.io') {
    // ghcr.io/org/repo -> https://github.com/org/repo/pkgs/container/repo
    const pathParts = imagePath.split('/')
    if (pathParts.length >= 2 && pathParts[0] && pathParts[1]) {
      const org = pathParts[0]
      const repo = pathParts[1]
      return `https://github.com/${org}/${repo}/pkgs/container/${repo}`
    }
    // Fallback for non-standard paths
    return `https://github.com/orgs/${pathParts[0] || 'unknown'}/packages`
  }

  // Quay.io
  if (registry === 'quay.io') {
    return `https://quay.io/repository/${imagePath}`
  }

  // GitLab Container Registry
  if (registry.includes('gitlab')) {
    return `https://${registry}/${imagePath}/container_registry`
  }

  // Docker Hub with explicit docker.io registry
  if (registry === 'docker.io') {
    return `https://hub.docker.com/r/${imagePath}`
  }

  // Generic registry - return base URL
  return `https://${registry}/${imagePath}`
}

/**
 * Get registry display name
 *
 * @param imageName - Full image name
 * @returns Human-readable registry name
 */
export function getRegistryName(imageName: string): string {
  // lscr.io images redirect to Docker Hub, so display "Docker Hub"
  if (imageName.startsWith('lscr.io/')) return 'Docker Hub'
  if (imageName.startsWith('ghcr.io/')) return 'GitHub Container Registry'
  if (imageName.startsWith('quay.io/')) return 'Quay.io'
  if (imageName.includes('gitlab')) return 'GitLab Container Registry'
  if (imageName.startsWith('docker.io/')) return 'Docker Hub'

  // Check for user/image format (Docker Hub)
  const parts = imageName.split('/')
  const firstPart = parts[0]
  if (parts.length === 2 && firstPart && !firstPart.includes('.') && !firstPart.includes(':') && !firstPart.includes('@')) {
    return 'Docker Hub'
  }

  // Default to Docker Hub for single-part images (official images)
  if (parts.length === 1 || (firstPart && !firstPart.includes('.') && !firstPart.includes('@'))) {
    return 'Docker Hub'
  }

  // Extract registry hostname
  return firstPart || 'Unknown Registry'
}
