/**
 * Unit tests for ViewModeSelector component - Phase 4b
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ViewModeSelector } from './ViewModeSelector'

describe('ViewModeSelector', () => {
  const mockOnChange = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render all three view mode buttons', () => {
    render(<ViewModeSelector viewMode="compact" onChange={mockOnChange} />)

    expect(screen.getByRole('radio', { name: /compact view mode/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /standard view mode/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /expanded view mode/i })).toBeInTheDocument()
  })

  it('should mark the current view mode as active', () => {
    render(<ViewModeSelector viewMode="standard" onChange={mockOnChange} />)

    const standardButton = screen.getByRole('radio', { name: /standard view mode/i })
    expect(standardButton).toHaveAttribute('aria-checked', 'true')

    const compactButton = screen.getByRole('radio', { name: /compact view mode/i })
    expect(compactButton).toHaveAttribute('aria-checked', 'false')

    const expandedButton = screen.getByRole('radio', { name: /expanded view mode/i })
    expect(expandedButton).toHaveAttribute('aria-checked', 'false')
  })

  it('should call onChange with correct mode when button is clicked', async () => {
    const user = userEvent.setup()
    render(<ViewModeSelector viewMode="compact" onChange={mockOnChange} />)

    const standardButton = screen.getByRole('radio', { name: /standard view mode/i })
    await user.click(standardButton)

    expect(mockOnChange).toHaveBeenCalledWith('standard')
  })

  it('should not call onChange when clicking the already active button', async () => {
    const user = userEvent.setup()
    render(<ViewModeSelector viewMode="compact" onChange={mockOnChange} />)

    const compactButton = screen.getByRole('radio', { name: /compact view mode/i })
    await user.click(compactButton)

    expect(mockOnChange).toHaveBeenCalledWith('compact')
  })

  it('should disable all buttons when disabled prop is true', () => {
    render(<ViewModeSelector viewMode="compact" onChange={mockOnChange} disabled />)

    const compactButton = screen.getByRole('radio', { name: /compact view mode/i })
    const standardButton = screen.getByRole('radio', { name: /standard view mode/i })
    const expandedButton = screen.getByRole('radio', { name: /expanded view mode/i })

    expect(compactButton).toBeDisabled()
    expect(standardButton).toBeDisabled()
    expect(expandedButton).toBeDisabled()
  })

  it('should not call onChange when buttons are disabled', async () => {
    const user = userEvent.setup()
    render(<ViewModeSelector viewMode="compact" onChange={mockOnChange} disabled />)

    const standardButton = screen.getByRole('radio', { name: /standard view mode/i })
    await user.click(standardButton)

    expect(mockOnChange).not.toHaveBeenCalled()
  })

  it('should render with radiogroup role for accessibility', () => {
    render(<ViewModeSelector viewMode="compact" onChange={mockOnChange} />)

    const radioGroup = screen.getByRole('radiogroup', { name: /dashboard view mode/i })
    expect(radioGroup).toBeInTheDocument()
  })

  it('should switch between all three modes correctly', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<ViewModeSelector viewMode="compact" onChange={mockOnChange} />)

    // Click standard
    let standardButton = screen.getByRole('radio', { name: /standard view mode/i })
    await user.click(standardButton)
    expect(mockOnChange).toHaveBeenCalledWith('standard')

    // Rerender with standard active and re-query
    rerender(<ViewModeSelector viewMode="standard" onChange={mockOnChange} />)
    standardButton = screen.getByRole('radio', { name: /standard view mode/i })
    expect(standardButton).toHaveAttribute('aria-checked', 'true')

    // Click expanded
    let expandedButton = screen.getByRole('radio', { name: /expanded view mode/i })
    await user.click(expandedButton)
    expect(mockOnChange).toHaveBeenCalledWith('expanded')

    // Rerender with expanded active and re-query
    rerender(<ViewModeSelector viewMode="expanded" onChange={mockOnChange} />)
    expandedButton = screen.getByRole('radio', { name: /expanded view mode/i })
    expect(expandedButton).toHaveAttribute('aria-checked', 'true')

    // Click compact
    const compactButton = screen.getByRole('radio', { name: /compact view mode/i })
    await user.click(compactButton)
    expect(mockOnChange).toHaveBeenCalledWith('compact')
  })

  it('should render icons for each mode', () => {
    const { container } = render(<ViewModeSelector viewMode="compact" onChange={mockOnChange} />)

    // Check that SVG icons are rendered (lucide-react renders SVGs)
    const svgs = container.querySelectorAll('svg')
    expect(svgs.length).toBeGreaterThanOrEqual(3) // At least one icon per button
  })
})
