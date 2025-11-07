# Private Registry Credentials

DockMon supports authentication with private container registries, enabling you to monitor and update containers from registries that require authentication.

## Security Notice

### How Credentials Are Stored

- Registry credentials are **encrypted using Fernet symmetric encryption** before being stored in the database
- The encryption key is stored in `/app/data/encryption.key` within the Docker volume
- This protects against:
  - ✅ Accidental database dumps or exports
  - ✅ Database file being shared or backed up separately
  - ✅ Direct database access without the encryption key

### Security Limitations

**Important:** Understand these limitations before adding credentials:

- ❌ **Does NOT protect against full container compromise** - If an attacker gains access to both the database file AND the encryption key, they can decrypt credentials
- ❌ **Does NOT protect against volume compromise** - Both the database and encryption key are stored in the same Docker volume (`/app/data`)
- ❌ **Does NOT protect against memory dumps** - Credentials are decrypted in memory during update checks

### Best Practices

To minimize security risks:

1. **Use read-only access tokens** instead of passwords when possible
   - Most registries support creating tokens with pull-only permissions
   - This limits damage if credentials are compromised

2. **Use service accounts** with minimal permissions
   - Don't use personal credentials
   - Create dedicated service accounts for DockMon

3. **Rotate credentials** regularly
   - Change passwords/tokens periodically
   - Update credentials in DockMon settings after rotation

4. **Delete unused credentials** promptly
   - Remove credentials when no longer needed
   - Reduce attack surface

5. **Secure your Docker volumes**
   - Use proper file permissions
   - Regular backup security audits
   - Consider encrypted host volumes for sensitive environments

6. **Use Docker's config.json for high-security environments**
   - Store credentials outside DockMon's database
   - Future feature: import from Docker config.json (planned)

---

## Supported Registries

DockMon works with any OCI-compliant container registry, including:

- **Docker Hub** (docker.io)
- **GitHub Container Registry** (ghcr.io)
- **Google Container Registry** (gcr.io)
- **AWS Elastic Container Registry** (ECR)
- **Azure Container Registry** (ACR)
- **Harbor** (self-hosted)
- **Quay.io** (Red Hat Quay)
- **Self-hosted Docker Registry**
- Any other OCI-compliant registry

---

## Adding Credentials

### Via Web UI

1. Navigate to **Settings → Container Updates**
2. Scroll to **Registry Credentials** section
3. Click **Add Credential**
4. Fill in the form:
   - **Registry URL**: The registry hostname (e.g., `ghcr.io`, `registry.example.com`)
     - Do NOT include `http://` or `https://` - just the hostname
     - Include port if non-standard (e.g., `registry.example.com:5000`)
   - **Username**: Your registry username or service account
   - **Password**: Your password or access token
5. Click **Create**

### Registry URL Examples

| Registry | URL to Enter |
|----------|--------------|
| Docker Hub | `docker.io` |
| GitHub Container Registry | `ghcr.io` |
| Google Container Registry | `gcr.io` |
| Harbor (custom) | `harbor.example.com` |
| Self-hosted Registry | `registry.example.com:5000` |

**Note:** The registry URL is normalized to lowercase and protocols are stripped automatically.

---

## Updating Credentials

To change username or password:

1. Go to **Settings → Container Updates → Registry Credentials**
2. Click the **Edit** icon (pencil) next to the credential
3. Modify the username and/or enter a new password
4. Click **Update**

**Note:** You cannot change the registry URL. If you need a different URL, delete the credential and create a new one.

---

## Deleting Credentials

To remove credentials:

1. Go to **Settings → Container Updates → Registry Credentials**
2. Click the **Delete** icon (trash) next to the credential
3. Confirm deletion

**Warning:** After deletion, update checks for containers using this registry will fail if authentication is required.

---

## How It Works

### Update Check Flow

When DockMon checks a container for updates:

1. **Extract registry from image name**
   - Example: `ghcr.io/user/app:latest` → registry is `ghcr.io`

2. **Look up credentials**
   - Query database for matching registry URL
   - If found, decrypt the password

3. **Authenticate with registry**
   - Pass username and password to registry API
   - Obtain auth token (cached for 4 minutes)

4. **Check for updates**
   - Query registry for latest image digest
   - Compare with current running image

### Credential Matching

Credentials are matched by exact registry URL:

- ✅ Image `ghcr.io/user/app:latest` matches credential for `ghcr.io`
- ✅ Image `registry.example.com:5000/app:v1` matches `registry.example.com:5000`
- ❌ Image `nginx:1.25` (Docker Hub) matches `docker.io` (must add Docker Hub credentials)

---

## Using Access Tokens

### GitHub Container Registry (ghcr.io)

1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Generate new token (classic)
3. Select scopes: `read:packages`
4. Copy the token
5. In DockMon:
   - Registry URL: `ghcr.io`
   - Username: Your GitHub username
   - Password: Paste the token

### Docker Hub

1. Go to Docker Hub → Account Settings → Security
2. Create New Access Token
3. Select permissions: Public Repo Read-only (or appropriate level)
4. Copy the token
5. In DockMon:
   - Registry URL: `docker.io`
   - Username: Your Docker Hub username
   - Password: Paste the token

### Harbor

1. Log in to Harbor web UI
2. Go to User Profile → User Settings
3. Copy CLI secret or create Robot Account
4. In DockMon:
   - Registry URL: Your Harbor hostname
   - Username: Your Harbor username or robot account name
   - Password: CLI secret or robot account token

---

## Troubleshooting

### Update Checks Failing

**Symptoms:** Container shows "Update check failed" or no update information

**Possible causes:**

1. **Incorrect credentials**
   - Verify username and password are correct
   - Try logging in manually: `docker login <registry>`

2. **Wrong registry URL**
   - Check the image name in container details
   - Ensure registry URL matches exactly (case-insensitive)

3. **Token expired**
   - Some tokens have expiration dates
   - Generate new token and update credentials

4. **Insufficient permissions**
   - Token needs `read` or `pull` permissions
   - Check token permissions in registry UI

### Credential Decryption Errors

**Symptoms:** Logs show "Failed to decrypt credentials"

**Possible causes:**

1. **Encryption key changed or deleted**
   - If `/app/data/encryption.key` is deleted, credentials cannot be decrypted
   - You must re-add all credentials

2. **Database corruption**
   - Restore from backup
   - Re-add credentials

**Solution:** Delete and re-create the affected credential.

### Security Concerns

**Q: Should I add credentials for Docker Hub public images?**

A: No, public images don't require authentication. However, Docker Hub has rate limits for anonymous users (100 pulls/6 hours). Adding credentials increases this to 200 pulls/6 hours for free accounts.

**Q: Can I use the same credentials for multiple registries?**

A: Each registry requires separate credentials. You cannot reuse credentials across registries.

**Q: What happens if I lose the encryption key?**

A: All encrypted credentials become unrecoverable. You must delete and re-create all credentials.

---

## API Access

For automation or custom integrations:

### List Credentials

```bash
curl -X GET https://dockmon.example.com/api/registry-credentials \
  -H "Cookie: session_id=..."
```

### Create Credential

```bash
curl -X POST https://dockmon.example.com/api/registry-credentials \
  -H "Cookie: session_id=..." \
  -H "Content-Type: application/json" \
  -d '{
    "registry_url": "ghcr.io",
    "username": "myuser",
    "password": "my_token_here"
  }'
```

### Update Credential

```bash
curl -X PUT https://dockmon.example.com/api/registry-credentials/1 \
  -H "Cookie: session_id=..." \
  -H "Content-Type: application/json" \
  -d '{
    "password": "new_token_here"
  }'
```

### Delete Credential

```bash
curl -X DELETE https://dockmon.example.com/api/registry-credentials/1 \
  -H "Cookie: session_id=..."
```

**Note:** Passwords are NEVER returned in API responses for security.

---

## Future Enhancements

Planned features for future releases:

- **Import from Docker config.json** - Automatically detect and import credentials from Docker's config file
- **Credential helpers support** - Integration with Docker credential helpers (e.g., `docker-credential-gcr`)
- **Per-host credentials** - Different credentials for the same registry on different Docker hosts
- **Credential testing** - Test button to verify credentials work before saving
- **Audit logging** - Track credential access and usage

---

## Related Documentation

- [Container Updates](./container-updates.md) - Update detection and tracking modes
- [Update Policies](./update-policies.md) - Validation rules for protected containers
- [Security Best Practices](./security.md) - General security recommendations

---

*Last updated: 2025-01-21*
