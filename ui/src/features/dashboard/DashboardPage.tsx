/**
 * Dashboard Page - Phase 2 MVP
 *
 * TODO: Will be enhanced with widgets, real-time updates, etc.
 */

import { useAuth } from '@/features/auth/AuthContext'

export function DashboardPage() {
  const { user, logout } = useAuth()

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <h1 style={styles.title}>DockMon Dashboard</h1>
        <div style={styles.userInfo}>
          <span style={styles.username}>Welcome, {user?.username}</span>
          <button onClick={() => void logout()} style={styles.logoutButton}>
            Logout
          </button>
        </div>
      </header>

      <main style={styles.main}>
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>✅ Phase 2 - React Foundation Complete!</h2>
          <ul style={styles.list}>
            <li>✅ React 18 + TypeScript + Vite</li>
            <li>✅ Cookie-based authentication (HttpOnly, Secure, SameSite=strict)</li>
            <li>✅ API client (stable boundary)</li>
            <li>✅ TanStack Query for server state</li>
            <li>✅ Feature-first structure</li>
            <li>✅ Protected routes</li>
          </ul>
          <p style={styles.note}>
            Next: Dashboard widgets, real-time updates, container management
          </p>
        </div>
      </main>
    </div>
  )
}

const styles = {
  container: {
    minHeight: '100vh',
    backgroundColor: '#0f172a',
    color: '#f8fafc',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '1rem 2rem',
    backgroundColor: '#1e293b',
    borderBottom: '1px solid #334155',
  },
  title: {
    margin: 0,
    fontSize: '1.5rem',
    fontWeight: 'bold',
  },
  userInfo: {
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
  },
  username: {
    fontSize: '0.875rem',
    color: '#94a3b8',
  },
  logoutButton: {
    padding: '0.5rem 1rem',
    backgroundColor: '#3b82f6',
    border: 'none',
    borderRadius: '0.25rem',
    color: '#ffffff',
    fontSize: '0.875rem',
    fontWeight: '500',
    cursor: 'pointer',
  },
  main: {
    padding: '2rem',
    maxWidth: '800px',
    margin: '0 auto',
  },
  card: {
    backgroundColor: '#1e293b',
    borderRadius: '0.5rem',
    padding: '2rem',
    border: '1px solid #334155',
  },
  cardTitle: {
    margin: '0 0 1rem 0',
    fontSize: '1.25rem',
    color: '#22c55e',
  },
  list: {
    marginBottom: '1rem',
    paddingLeft: '1.5rem',
    lineHeight: '1.8',
  },
  note: {
    marginTop: '1.5rem',
    padding: '1rem',
    backgroundColor: '#334155',
    borderRadius: '0.25rem',
    fontSize: '0.875rem',
    color: '#94a3b8',
  },
}
