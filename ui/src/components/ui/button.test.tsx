/**
 * Button Component Tests
 *
 * COVERAGE:
 * - Rendering all variants (default, destructive, outline, ghost, link)
 * - Rendering all sizes (default, sm, lg, icon)
 * - Disabled state
 * - asChild prop (Radix Slot composition)
 * - Custom className merging
 * - Accessibility (button semantics, disabled handling)
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button } from './button'

describe('Button', () => {
  describe('rendering', () => {
    it('should render button with default variant and size', () => {
      render(<Button>Click me</Button>)

      const button = screen.getByRole('button', { name: /click me/i })
      expect(button).toBeInTheDocument()
      expect(button).toHaveClass('bg-primary', 'text-primary-foreground')
    })

    it('should render all button variants', () => {
      const { rerender } = render(<Button variant="default">Default</Button>)
      expect(screen.getByRole('button')).toHaveClass('bg-primary')

      rerender(<Button variant="destructive">Destructive</Button>)
      expect(screen.getByRole('button')).toHaveClass('bg-destructive')

      rerender(<Button variant="outline">Outline</Button>)
      expect(screen.getByRole('button')).toHaveClass('border', 'bg-secondary')

      rerender(<Button variant="ghost">Ghost</Button>)
      expect(screen.getByRole('button')).toHaveClass('hover:bg-surface-1')

      rerender(<Button variant="link">Link</Button>)
      expect(screen.getByRole('button')).toHaveClass('underline-offset-4')
    })

    it('should render all button sizes', () => {
      const { rerender } = render(<Button size="default">Default</Button>)
      expect(screen.getByRole('button')).toHaveClass('h-9', 'px-4')

      rerender(<Button size="sm">Small</Button>)
      expect(screen.getByRole('button')).toHaveClass('h-8', 'px-3')

      rerender(<Button size="lg">Large</Button>)
      expect(screen.getByRole('button')).toHaveClass('h-11', 'px-8')

      rerender(<Button size="icon">Icon</Button>)
      expect(screen.getByRole('button')).toHaveClass('h-9', 'w-9')
    })

    it('should merge custom className with variants', () => {
      render(
        <Button variant="default" className="custom-class">
          Custom
        </Button>
      )

      const button = screen.getByRole('button')
      expect(button).toHaveClass('bg-primary', 'custom-class')
    })

    it('should render as child component when asChild is true', () => {
      render(
        <Button asChild>
          <a href="/test">Link Button</a>
        </Button>
      )

      const link = screen.getByRole('link', { name: /link button/i })
      expect(link).toBeInTheDocument()
      expect(link).toHaveClass('bg-primary') // Button classes applied to <a>
      expect(link).toHaveAttribute('href', '/test')
    })
  })

  describe('interaction', () => {
    it('should call onClick handler when clicked', async () => {
      const user = userEvent.setup()
      const handleClick = vi.fn()

      render(<Button onClick={handleClick}>Click me</Button>)

      const button = screen.getByRole('button')
      await user.click(button)

      expect(handleClick).toHaveBeenCalledTimes(1)
    })

    it('should not call onClick when disabled', async () => {
      const user = userEvent.setup()
      const handleClick = vi.fn()

      render(
        <Button onClick={handleClick} disabled>
          Disabled
        </Button>
      )

      const button = screen.getByRole('button')
      await user.click(button)

      expect(handleClick).not.toHaveBeenCalled()
    })
  })

  describe('accessibility', () => {
    it('should have disabled attribute when disabled', () => {
      render(<Button disabled>Disabled</Button>)

      const button = screen.getByRole('button')
      expect(button).toBeDisabled()
      expect(button).toHaveClass('disabled:pointer-events-none', 'disabled:opacity-50')
    })

    it('should have proper button semantics', () => {
      render(<Button type="submit">Submit</Button>)

      const button = screen.getByRole('button')
      expect(button.tagName).toBe('BUTTON')
      expect(button).toHaveAttribute('type', 'submit')
    })

    it('should support focus-visible styles for keyboard navigation', () => {
      render(<Button>Focus me</Button>)

      const button = screen.getByRole('button')
      expect(button).toHaveClass('focus-visible:outline-none', 'focus-visible:ring-2')
    })
  })

  describe('custom props', () => {
    it('should pass through native button attributes', () => {
      render(
        <Button type="submit" name="submit-btn" data-testid="custom-button">
          Submit
        </Button>
      )

      const button = screen.getByTestId('custom-button')
      expect(button).toHaveAttribute('type', 'submit')
      expect(button).toHaveAttribute('name', 'submit-btn')
    })

    it('should forward ref to button element', () => {
      const ref = vi.fn()

      render(<Button ref={ref}>Button</Button>)

      expect(ref).toHaveBeenCalled()
      expect(ref.mock.calls[0]?.[0]).toBeInstanceOf(HTMLButtonElement)
    })
  })
})
