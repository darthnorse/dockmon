# DockMon v2.1 Deployment Feature - E2E Test Plan

**Date:** 2025-10-25
**Phase:** Week 4 - Frontend TDD (RED Phase)
**Approach:** Test-Driven Development - Write tests first, implement UI to make them pass

---

## Test Coverage Goals

### Critical User Workflows
1. **Create Deployment** - User can create a new container deployment
2. **Execute Deployment** - User can start deployment and see progress
3. **Monitor Progress** - User sees real-time layer-by-layer progress (like updates)
4. **View Deployments** - User can see list of all deployments
5. **Template Management** - User can create, edit, and use templates
6. **Error Handling** - User sees clear errors when deployment fails
7. **Rollback Behavior** - User understands what happened when deployment rolls back

### Test Files

#### `deployments.spec.ts` - Core Deployment Workflows
- [x] Navigation: Can access deployments page
- [x] Create: Can create new deployment from form
- [x] Create: Can select template and fill variables
- [x] Execute: Can trigger deployment execution
- [x] Progress: Can see real-time progress (0-100%)
- [x] Layer Progress: Can see layer-by-layer download tracking
- [x] Layer Progress: Can see download speeds (MB/s)
- [x] Completion: Can see successful completion state
- [x] Failure: Can see error message when deployment fails
- [x] Rollback: Can see rollback state and understand what was cleaned up
- [x] List: Can view all deployments with filters (by host, by status)
- [x] Delete: Can delete completed/failed deployments
- [x] Validation: Cannot delete in-progress deployments

#### `templates.spec.ts` - Template Management
- [x] List: Can view all available templates
- [x] Create: Can create new template with variables
- [x] Edit: Can update template definition
- [x] Delete: Can delete template
- [x] Variables: Can use ${VAR_NAME} syntax in templates
- [x] Defaults: Can specify default values for variables
- [x] Render Preview: Can preview rendered template before deployment

#### `deployment-security.spec.ts` - Security Validation
- [x] Critical Violations: Deployment blocked for privileged containers
- [x] High Violations: Warning shown but deployment allowed for dangerous capabilities
- [x] Error Display: Security violations formatted clearly for user
- [x] Multi-Violation: All violations shown when multiple issues exist

#### `deployment-concurrent.spec.ts` - Concurrent Operations
- [x] Multiple Deployments: Can run multiple deployments simultaneously
- [x] Progress Tracking: Each deployment tracks progress independently
- [x] No Conflicts: Deployments don't interfere with each other

---

## Test Data Strategy

### Test Deployments
```typescript
// Simple deployment for basic tests
const simpleDeployment = {
  name: "test-alpine-deployment",
  image: "alpine:latest",
  host_id: "<default-host>"
}

// Deployment with layer progress (medium size image)
const layeredDeployment = {
  name: "test-redis-deployment",
  image: "redis:7.2-alpine", // 8 layers, 11.6 MB
  host_id: "<default-host>"
}

// Security violation (should be blocked)
const privilegedDeployment = {
  name: "test-privileged-blocked",
  image: "alpine:latest",
  privileged: true  // CRITICAL violation
}

// Template with variables
const nginxTemplate = {
  name: "NGINX Web Server",
  variables: [
    {name: "PORT", default: "8080"},
    {name: "VERSION", default: "latest"}
  ],
  definition: {
    image: "nginx:${VERSION}",
    ports: ["${PORT}:80"]
  }
}
```

### Test Cleanup
- Delete all test deployments after each test
- Delete all test templates after each test
- Use name prefix "test-" for easy cleanup
- Cleanup in afterEach hooks to prevent data pollution

---

## WebSocket Event Testing

### Events to Verify
```typescript
// Events we expect to receive during deployment
const expectedEvents = [
  'deployment_created',           // After POST /api/deployments
  'deployment_progress',          // During execution (0-100%)
  'deployment_layer_progress',    // Layer-by-layer tracking (like updates)
  'deployment_completed',         // Success
  'deployment_failed',            // Failure with error_message
  'deployment_rolled_back'        // After failure before commitment point
]
```

### Event Data Structure
```typescript
interface DeploymentProgressEvent {
  type: 'deployment_progress'
  data: {
    host_id: string
    entity_id: string  // deployment_id
    progress: number   // 0-100
    stage: string      // "pulling", "creating", "starting", "completed"
    message: string
  }
}

interface DeploymentLayerProgressEvent {
  type: 'deployment_layer_progress'
  data: {
    host_id: string
    entity_id: string
    overall_progress: number  // 0-100
    layers: Array<{
      id: string
      status: string  // "downloading", "extracting", "complete"
      current: number
      total: number
      percent: number
    }>
    total_layers: number
    remaining_layers: number
    summary: string  // "Downloading 3 of 8 layers (45%) @ 12.5 MB/s"
    speed_mbps?: number
  }
}
```

---

## UI Component Expectations

Based on existing DockMon patterns (updates, containers, etc.):

### Navigation
- **Location**: Sidebar navigation (add "Deployments" link)
- **Route**: `/deployments`
- **Icon**: Package or Rocket icon
- **Access**: Authenticated users only

### Deployments Page (`/deployments`)
- **Layout**: Similar to ContainersPage with table + filters
- **Filters**: By host, by status (all, planning, executing, completed, failed, rolled_back)
- **Actions**:
  - "New Deployment" button (top right)
  - Per-deployment: Execute, Delete, View Details
- **Columns**: Name, Host, Status, Progress, Created, Actions

### Deployment Creation Modal/Page
- **Fields**:
  - Deployment Name (required, unique per host)
  - Deployment Type (Container or Stack)
  - Host Selection (dropdown)
  - Template Selection (optional, "From Template" button)
  - Image (required for container)
  - Ports (optional, format: "8080:80")
  - Environment Variables (key-value pairs)
  - Volumes (optional, format: "/host:/container")
  - Labels (optional, key-value pairs)
- **Validation**:
  - Name required
  - Image required (unless from template)
  - Port format validation
  - Security validation feedback (show warnings/errors)
- **Actions**: "Create Deployment" (planning state), "Create & Execute" (immediate)

### Deployment Progress View
- **Simple Progress Bar**: 0-100% with current stage
- **Layer-by-Layer View** (expandable, like updates):
  - Overall progress percentage
  - Download speed (MB/s)
  - Layer list with individual progress bars
  - Summary text: "Downloading 3 of 8 layers (45%) @ 12.5 MB/s"
- **Status Indicators**:
  - Planning: Gray/neutral
  - Executing: Blue/progress animation
  - Completed: Green checkmark
  - Failed: Red X with error message
  - Rolled Back: Yellow with explanation

### Template Browser/Editor
- **List View**: Grid or table of available templates
- **Create Template**: Modal with:
  - Name (required, unique)
  - Description
  - Variable definitions (name, default value)
  - Definition JSON editor
- **Edit Template**: Same modal, prefilled
- **Delete Template**: Confirmation modal
- **Use Template**: Pre-fills deployment form with template values

---

## Expected Data Flow

### 1. Create Deployment
```
User fills form → POST /api/deployments → deployment_created event → UI shows in list
```

### 2. Execute Deployment
```
User clicks Execute → POST /api/deployments/{id}/execute →
  deployment_progress events (0% → 10% → 50% → 100%) →
  deployment_layer_progress events (layer details) →
  deployment_completed event →
  UI shows completion state
```

### 3. Deployment Failure
```
User executes → POST /api/deployments/{id}/execute →
  deployment_progress events →
  deployment_failed event (with error_message) →
  deployment_rolled_back event (if before commitment point) →
  UI shows error and rollback state
```

### 4. Template Usage
```
User selects template → GET /api/templates/{id} →
POST /api/templates/{id}/render with variables →
Form prefilled with rendered values →
User creates deployment
```

---

## Accessibility & UX Requirements

### Test Attributes
- All interactive elements have `data-testid` attributes
- Form inputs have proper `name` attributes
- Buttons have descriptive text
- Modals have `role="dialog"`
- Progress bars have `role="progressbar"`

### User Feedback
- Loading states during API calls
- Success toasts on completion
- Error toasts with actionable messages
- Progress indicators for long operations
- Confirmation dialogs for destructive actions

### Error Messages
- Security violations: Clear explanation + guidance
- Validation errors: Field-specific feedback
- API errors: User-friendly messages (not stack traces)
- Network errors: Retry options

---

## Test Execution Strategy

### Phase 1: Write All Tests (RED Phase)
1. Write `deployments.spec.ts` - All tests will fail (no UI exists)
2. Write `templates.spec.ts` - All tests will fail
3. Write `deployment-security.spec.ts` - All tests will fail
4. Write `deployment-concurrent.spec.ts` - All tests will fail
5. Run tests: `npx playwright test` - Expect 100% failure rate ✅

### Phase 2: Implement UI (GREEN Phase)
1. Create deployment types (TypeScript interfaces)
2. Create API hooks (useDeployments, useTemplates, useExecuteDeployment)
3. Create DeploymentPage component
4. Create DeploymentForm component
5. Create DeploymentProgressView component
6. Create TemplateManager component
7. Add routing + navigation
8. Integrate WebSocket events
9. Run tests incrementally until all pass

### Phase 3: Polish & Edge Cases
1. UI/UX improvements
2. Edge case handling
3. Performance optimization
4. Final test run - Expect 100% pass rate ✅

---

## Success Criteria

### RED Phase Complete ✅
- All E2E tests written (comprehensive coverage)
- All tests fail appropriately (UI doesn't exist yet)
- Tests documented and peer-reviewed

### GREEN Phase Complete ✅
- All E2E tests passing (UI fully functional)
- Backend integration verified
- WebSocket events working
- Zero manual testing needed

### Production Ready ✅
- 100% E2E test pass rate
- UI polished and user-friendly
- Security validation working
- Layer-by-layer progress tracking beautiful
- Same confidence in frontend as backend

---

## Test Maintenance

### Continuous Integration
- Tests run on every commit
- Tests run before merge to main
- Screenshots captured on failure
- HTML report generated

### Test Evolution
- Add tests for new features
- Update tests when requirements change
- Remove tests for deprecated features
- Keep test data fresh and realistic

---

**Author**: Claude Code (TDD Phase 1)
**Status**: Test Plan Complete - Ready to Write Tests
**Next**: Write `deployments.spec.ts` (RED phase)