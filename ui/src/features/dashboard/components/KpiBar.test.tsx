/**
 * Unit tests for KpiBar component - Phase 4c
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KpiBar } from './KpiBar'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import { useStatsContext } from '@/lib/stats/StatsProvider'
import { BrowserRouter } from 'react-router-dom'

// Mock dependencies
vi.mock('@/features/hosts/hooks/useHosts')
vi.mock('@/lib/stats/StatsProvider')

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

describe('KpiBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const renderWithRouter = (component: React.ReactElement) => {
    return render(<BrowserRouter>{component}</BrowserRouter>)
  }

  it('should render all 5 KPI cards', () => {
    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    expect(screen.getByText('Hosts')).toBeInTheDocument()
    expect(screen.getByText('Containers')).toBeInTheDocument()
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByText('Alerts')).toBeInTheDocument()
    expect(screen.getByText('Updates')).toBeInTheDocument()
  })

  it('should display correct host counts', () => {
    const mockHosts = [
      { id: '1', name: 'Host 1', status: 'online' },
      { id: '2', name: 'Host 2', status: 'online' },
      { id: '3', name: 'Host 3', status: 'offline' },
    ]

    vi.mocked(useHosts).mockReturnValue({ data: mockHosts, isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('2 online • 1 offline')).toBeInTheDocument()
  })

  it('should display correct container counts', () => {
    const mockContainerStats = new Map([
      ['host1:container1', { id: 'container1', host_id: 'host1', state: 'running' }],
      ['host1:container2', { id: 'container2', host_id: 'host1', state: 'running' }],
      ['host1:container3', { id: 'container3', host_id: 'host1', state: 'stopped' }],
      ['host2:container4', { id: 'container4', host_id: 'host2', state: 'running' }],
    ])

    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: mockContainerStats as any,
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    // Check specific text combinations that are unique to each card
    expect(screen.getByText('3 running • 1 stopped')).toBeInTheDocument()
    expect(screen.getByText('75% of total')).toBeInTheDocument()
  })

  it('should navigate to hosts page when Hosts card is clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    const hostsCard = screen.getByText('Hosts').closest('button')
    expect(hostsCard).toBeInTheDocument()

    await user.click(hostsCard!)

    expect(mockNavigate).toHaveBeenCalledWith('/hosts')
  })

  it('should navigate to containers page when Containers card is clicked', async () => {
    const user = userEvent.setup()
    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    const containersCard = screen.getByText('Containers').closest('button')
    expect(containersCard).toBeInTheDocument()

    await user.click(containersCard!)

    expect(mockNavigate).toHaveBeenCalledWith('/containers')
  })

  it('should show all hosts online when all are online', () => {
    const mockHosts = [
      { id: '1', name: 'Host 1', status: 'online' },
      { id: '2', name: 'Host 2', status: 'online' },
    ]

    vi.mocked(useHosts).mockReturnValue({ data: mockHosts, isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    expect(screen.getByText('2 online • 0 offline')).toBeInTheDocument()
  })

  it('should handle zero containers gracefully', () => {
    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    // Check that all values are zero
    expect(screen.getAllByText('0').length).toBeGreaterThan(0)
    expect(screen.getByText('0 running • 0 stopped')).toBeInTheDocument()
  })

  it('should show alerts count (placeholder for now)', () => {
    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    // Currently hardcoded to 0
    expect(screen.getByText('All clear')).toBeInTheDocument()
  })

  it('should show updates count (placeholder for now)', () => {
    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    // Currently hardcoded to 0
    expect(screen.getByText('Up to date')).toBeInTheDocument()
  })

  it('should calculate running percentage correctly', () => {
    const mockContainerStats = new Map([
      ['host1:container1', { id: 'container1', host_id: 'host1', state: 'running' }],
      ['host1:container2', { id: 'container2', host_id: 'host1', state: 'stopped' }],
    ])

    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: mockContainerStats as any,
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    renderWithRouter(<KpiBar />)

    // 1/2 = 50%
    expect(screen.getByText('50% of total')).toBeInTheDocument()
  })

  it('should use responsive grid layout', () => {
    vi.mocked(useHosts).mockReturnValue({ data: [], isLoading: false } as any)
    vi.mocked(useStatsContext).mockReturnValue({
      containerStats: new Map(),
      hostMetrics: new Map(),
      hostSparklines: new Map(),
      lastUpdate: null,
      isConnected: false,
    })

    const { container } = renderWithRouter(<KpiBar />)

    const gridElement = container.querySelector('.grid')
    expect(gridElement).toBeInTheDocument()
    expect(gridElement).toHaveClass('grid-cols-1')
    expect(gridElement).toHaveClass('xl:grid-cols-5')
  })
})
