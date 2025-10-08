# DockMon UI (v2.0 - React)

Modern React frontend for DockMon Docker monitoring system.

## Tech Stack

- **React 18** - Modern React with hooks and concurrent features
- **TypeScript** - Strict mode for type safety
- **Vite** - Fast build tooling and HMR
- **TanStack Query** - Server state management
- **React Router** - Client-side routing

## Architecture

### Feature-First Structure
```
src/
├── features/        # Feature-first organization
│   ├── auth/       # Authentication (login, context)
│   └── dashboard/  # Dashboard page
├── lib/            # Shared libraries (stable boundaries)
│   ├── api/        # API client (swappable)
│   ├── websocket/  # WebSocket client (swappable)
│   └── adapters/   # Library adapters (grid, table, charts)
├── components/     # Shared UI components
└── types/          # TypeScript type definitions
```

### Stable Boundaries (Swappable)
- **API Client** (`lib/api/client.ts`) - Can swap fetch → Orval → gRPC
- **WebSocket Client** (`lib/websocket/client.ts`) - Can swap WebSocket → WebTransport
- **Adapters** (`lib/adapters/`) - Wrap external libraries for easy swapping

## Security

### Cookie-Based Authentication
- ✅ HttpOnly cookies (XSS protection - JavaScript cannot access)
- ✅ Secure flag (HTTPS only)
- ✅ SameSite=strict (CSRF protection)
- ✅ No tokens in localStorage/sessionStorage
- ✅ Automatic session validation

### Content Security
- No inline scripts or styles in production
- Credentials included for all API requests
- Error messages don't reveal sensitive info

## Development

```bash
# Install dependencies
npm install

# Start dev server (proxies to backend at https://localhost:8001)
npm run dev

# Type check
npm run type-check

# Lint
npm run lint

# Build for production
npm run build
```

## Environment

- **Dev Server**: `http://localhost:3000`
- **API Proxy**: `/api` → `https://localhost:8001/api`
- **WebSocket Proxy**: `/ws` → `wss://localhost:8001/ws`

## Phase 2 Status

### ✅ Complete
- React 18 + TypeScript + Vite setup
- Strict TypeScript configuration
- Cookie-based authentication
- Protected routes
- API client (stable boundary)
- TanStack Query integration
- Login page
- Basic dashboard

### 🚧 TODO (Future Phases)
- Dashboard widgets with real-time updates
- Container management UI
- Event logs and alerts
- WebSocket client for real-time updates
- Grid/table/chart adapters
- Testing infrastructure (Vitest + RTL)
- Bundle size optimization

## Best Practices

1. **Never call `fetch()` directly** - Use `apiClient` from `lib/api/client.ts`
2. **Use TanStack Query** - Server state goes through Query, not useState
3. **Feature isolation** - Features should be self-contained with their own routes
4. **Type everything** - Strict TypeScript, no `any` types
5. **Error boundaries** - Wrap features in error boundaries
6. **Accessibility** - Use semantic HTML, ARIA labels, focus management

## Security Checklist

- [x] HttpOnly, Secure, SameSite=strict cookies
- [x] No tokens in localStorage
- [x] Credentials included in API requests
- [x] Input validation on all forms
- [x] Error messages don't leak sensitive info
- [x] HTTPS only (Secure flag)
- [ ] CSP headers (TODO: Add to nginx config)
- [ ] Rate limiting UI (TODO: Show user-friendly messages)

## Bundle Budget

- **Target**: < 500KB gzipped
- **Enforcement**: CI check (TODO: Add size-limit)
- **Current**: TBD (measure after build)

## License

Same as parent DockMon project
