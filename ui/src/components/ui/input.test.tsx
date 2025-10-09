/**
 * Input Component Tests
 *
 * COVERAGE:
 * - Rendering with design system styles
 * - All input types (text, password, email, number, etc.)
 * - User interaction (typing, clearing)
 * - Disabled state
 * - Placeholder text
 * - Custom className merging
 * - Accessibility (label association, autocomplete)
 * - Focus and blur events
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Input } from './input'

describe('Input', () => {
  describe('rendering', () => {
    it('should render input with design system styles', () => {
      render(<Input placeholder="Enter text" />)

      const input = screen.getByPlaceholderText('Enter text')
      expect(input).toBeInTheDocument()
      expect(input).toHaveClass(
        'rounded-lg',
        'border',
        'bg-input',
        'px-3',
        'py-1',
        'text-sm'
      )
    })

    it('should render all input types', () => {
      const { rerender } = render(<Input type="text" data-testid="input" />)
      expect(screen.getByTestId('input')).toHaveAttribute('type', 'text')

      rerender(<Input type="password" data-testid="input" />)
      expect(screen.getByTestId('input')).toHaveAttribute('type', 'password')

      rerender(<Input type="email" data-testid="input" />)
      expect(screen.getByTestId('input')).toHaveAttribute('type', 'email')

      rerender(<Input type="number" data-testid="input" />)
      expect(screen.getByTestId('input')).toHaveAttribute('type', 'number')

      rerender(<Input type="search" data-testid="input" />)
      expect(screen.getByTestId('input')).toHaveAttribute('type', 'search')
    })

    it('should display placeholder text', () => {
      render(<Input placeholder="Enter your username" />)

      const input = screen.getByPlaceholderText('Enter your username')
      expect(input).toBeInTheDocument()
      expect(input).toHaveClass('placeholder:text-gray-400')
    })

    it('should merge custom className', () => {
      render(<Input className="custom-input" data-testid="input" />)

      const input = screen.getByTestId('input')
      expect(input).toHaveClass('rounded-lg', 'custom-input')
    })

    it('should forward ref to input element', () => {
      const ref = vi.fn()

      render(<Input ref={ref} />)

      expect(ref).toHaveBeenCalled()
      expect(ref.mock.calls[0]?.[0]).toBeInstanceOf(HTMLInputElement)
    })
  })

  describe('interaction', () => {
    it('should accept user input', async () => {
      const user = userEvent.setup()

      render(<Input data-testid="input" />)

      const input = screen.getByTestId('input') as HTMLInputElement
      await user.type(input, 'test input')

      expect(input.value).toBe('test input')
    })

    it('should call onChange handler', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(<Input onChange={handleChange} data-testid="input" />)

      const input = screen.getByTestId('input')
      await user.type(input, 'a')

      expect(handleChange).toHaveBeenCalled()
    })

    it('should not accept input when disabled', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(<Input onChange={handleChange} disabled data-testid="input" />)

      const input = screen.getByTestId('input') as HTMLInputElement
      await user.type(input, 'test')

      expect(input.value).toBe('')
      expect(handleChange).not.toHaveBeenCalled()
    })

    it('should support controlled input', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      const { rerender } = render(
        <Input value="initial" onChange={handleChange} data-testid="input" />
      )

      const input = screen.getByTestId('input') as HTMLInputElement
      expect(input.value).toBe('initial')

      await user.type(input, 'a')
      expect(handleChange).toHaveBeenCalled()

      // Simulate parent component updating value
      rerender(
        <Input value="updated" onChange={handleChange} data-testid="input" />
      )
      expect(input.value).toBe('updated')
    })
  })

  describe('states', () => {
    it('should have disabled styles when disabled', () => {
      render(<Input disabled data-testid="input" />)

      const input = screen.getByTestId('input')
      expect(input).toBeDisabled()
      expect(input).toHaveClass('disabled:cursor-not-allowed', 'disabled:opacity-50')
    })

    it('should show focus styles for accessibility', () => {
      render(<Input data-testid="input" />)

      const input = screen.getByTestId('input')
      expect(input).toHaveClass(
        'focus-visible:outline-none',
        'focus-visible:border-primary',
        'focus-visible:ring-1'
      )
    })
  })

  describe('accessibility', () => {
    it('should work with labels', () => {
      render(
        <div>
          <label htmlFor="username">Username</label>
          <Input id="username" type="text" />
        </div>
      )

      const label = screen.getByText('Username')
      const input = screen.getByLabelText('Username')

      expect(label).toBeInTheDocument()
      expect(input).toBeInTheDocument()
      expect(input).toHaveAttribute('id', 'username')
    })

    it('should support autocomplete attribute', () => {
      render(<Input autoComplete="username" data-testid="input" />)

      const input = screen.getByTestId('input')
      expect(input).toHaveAttribute('autocomplete', 'username')
    })

    it('should support required attribute', () => {
      render(<Input required data-testid="input" />)

      const input = screen.getByTestId('input')
      expect(input).toBeRequired()
    })

    it('should support aria-label for screen readers', () => {
      render(<Input aria-label="Search containers" data-testid="input" />)

      const input = screen.getByTestId('input')
      expect(input).toHaveAttribute('aria-label', 'Search containers')
    })
  })

  describe('custom props', () => {
    it('should pass through native input attributes', () => {
      render(
        <Input
          name="email"
          maxLength={50}
          minLength={5}
          pattern="[a-z]+"
          data-testid="input"
        />
      )

      const input = screen.getByTestId('input')
      expect(input).toHaveAttribute('name', 'email')
      expect(input).toHaveAttribute('maxlength', '50')
      expect(input).toHaveAttribute('minlength', '5')
      expect(input).toHaveAttribute('pattern', '[a-z]+')
    })

    it('should handle focus and blur events', async () => {
      const handleFocus = vi.fn()
      const handleBlur = vi.fn()

      render(
        <Input onFocus={handleFocus} onBlur={handleBlur} data-testid="input" />
      )

      const input = screen.getByTestId('input')

      input.focus()
      expect(handleFocus).toHaveBeenCalledTimes(1)

      input.blur()
      expect(handleBlur).toHaveBeenCalledTimes(1)
    })
  })
})
