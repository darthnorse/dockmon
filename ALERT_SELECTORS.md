# Alert Rule Selectors - Advanced Filtering

Alert rules can target specific hosts, containers, or groups of containers using selectors. This allows you to create flexible rules without manually specifying every container ID.

## Selector Types

### 1. Host Selector (`host_selector_json`)

Filter alerts to specific hosts by name or ID.

**Exact Match:**
```json
{
  "host_name": "production-server-01"
}
```

**Regex Match:**
```json
{
  "host_name": "regex:prod-.*"
}
```
Matches: `prod-web`, `prod-db`, `prod-cache`, etc.

**By Host ID:**
```json
{
  "host_id": "abc123..."
}
```

### 2. Container Selector (`container_selector_json`)

Filter alerts to specific containers by name or ID.

**Exact Match:**
```json
{
  "container_name": "nginx-prod"
}
```

**Regex Match:**
```json
{
  "container_name": "regex:nginx-.*"
}
```
Matches: `nginx-prod`, `nginx-staging`, `nginx-test`, etc.

**By Container ID:**
```json
{
  "container_id": "def456..."
}
```

### 3. Labels Selector (`labels_json`)

Filter alerts to containers with specific Docker labels. **This is the most powerful selector for dynamic environments.**

**Single Label:**
```json
{
  "env": "production"
}
```

**Multiple Labels (AND logic):**
```json
{
  "env": "production",
  "team": "backend",
  "critical": "true"
}
```
All labels must match.

## Common Use Cases

### Production Containers Only
```json
{
  "labels_json": "{\"env\": \"production\"}"
}
```

### All Web Servers
```json
{
  "container_selector_json": "{\"container_name\": \"regex:.*-web.*\"}"
}
```

### Specific Team's Containers
```json
{
  "labels_json": "{\"team\": \"backend\", \"monitored\": \"true\"}"
}
```

### Staging Hosts
```json
{
  "host_selector_json": "{\"host_name\": \"regex:staging-.*\"}"
}
```

### Critical Infrastructure
```json
{
  "labels_json": "{\"tier\": \"critical\", \"backup\": \"required\"}"
}
```

## Combining Selectors

You can combine multiple selectors - all conditions must match (AND logic):

```json
{
  "host_selector_json": "{\"host_name\": \"regex:prod-.*\"}",
  "labels_json": "{\"env\": \"production\", \"critical\": \"true\"}"
}
```

This matches: containers with labels `env=production` AND `critical=true` running on hosts matching `prod-*`

## Adding Labels to Containers

To use label-based filtering, add labels when creating containers:

**Docker CLI:**
```bash
docker run -l env=production -l team=backend -l critical=true nginx
```

**Docker Compose:**
```yaml
services:
  web:
    image: nginx
    labels:
      env: production
      team: backend
      critical: true
```

## API Usage

When creating alert rules via API, selectors are JSON strings:

```json
{
  "name": "Production Containers Down",
  "scope": "container",
  "kind": "container_stopped",
  "labels_json": "{\"env\": \"production\"}",
  "enabled": true
}
```

## Notes

- **Regex Prefix:** Use `regex:` prefix for pattern matching (`"regex:prod-.*"`)
- **Exact Match:** Without `regex:` prefix, matching is exact (`"nginx-prod"`)
- **Case Sensitive:** All matching is case-sensitive
- **AND Logic:** Multiple labels/selectors use AND logic (all must match)
- **Empty Selector:** If selector field is null/empty, it matches everything in the scope

## Performance

- Selectors are evaluated in-memory (very fast)
- Regex matching is compiled on-demand
- Label matching is dictionary lookup (O(1))
- No database queries during evaluation
