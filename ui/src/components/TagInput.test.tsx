/**
 * TagInput Component Tests - Phase 3d Sub-Phase 6
 *
 * COVERAGE:
 * - Rendering with tags
 * - Adding tags (Enter key, suggestions)
 * - Removing tags (X button, Backspace)
 * - Tag validation and normalization
 * - Autocomplete suggestions
 * - Keyboard navigation (Arrow keys, Escape)
 * - Max tags limit
 * - Disabled state
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TagInput } from './TagInput'

describe('TagInput', () => {
  describe('rendering', () => {
    it('should render empty input with placeholder', () => {
      render(
        <TagInput
          value={[]}
          onChange={vi.fn()}
          placeholder="Add tags..."
        />
      )

      const input = screen.getByPlaceholderText('Add tags...')
      expect(input).toBeInTheDocument()
    })

    it('should render existing tags as chips', () => {
      render(
        <TagInput
          value={['production', 'web-server']}
          onChange={vi.fn()}
        />
      )

      expect(screen.getByText('production')).toBeInTheDocument()
      expect(screen.getByText('web-server')).toBeInTheDocument()
    })

    it('should show tag count and max limit', () => {
      render(
        <TagInput
          value={['tag1', 'tag2']}
          onChange={vi.fn()}
          maxTags={50}
        />
      )

      expect(screen.getByText(/2\/50 tags/)).toBeInTheDocument()
    })

    it('should hide input when max tags reached', () => {
      render(
        <TagInput
          value={['tag1', 'tag2']}
          onChange={vi.fn()}
          maxTags={2}
        />
      )

      expect(screen.getByText('Max tags reached')).toBeInTheDocument()
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    })

    it('should show error message when provided', () => {
      render(
        <TagInput
          value={[]}
          onChange={vi.fn()}
          error="Tags are required"
        />
      )

      expect(screen.getByText('Tags are required')).toBeInTheDocument()
    })
  })

  describe('adding tags', () => {
    it('should add tag on Enter key', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput value={[]} onChange={handleChange} />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'production{Enter}')

      expect(handleChange).toHaveBeenCalledWith(['production'])
    })

    it('should normalize tags to lowercase', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput value={[]} onChange={handleChange} />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'PRODUCTION{Enter}')

      expect(handleChange).toHaveBeenCalledWith(['production'])
    })

    it('should replace spaces with hyphens', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput value={[]} onChange={handleChange} />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'web server{Enter}')

      expect(handleChange).toHaveBeenCalledWith(['web-server'])
    })

    it('should not add duplicate tags', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput value={['production']} onChange={handleChange} />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'production{Enter}')

      expect(handleChange).not.toHaveBeenCalled()
    })

    it('should not add empty tags', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput value={[]} onChange={handleChange} />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, '   {Enter}')

      expect(handleChange).not.toHaveBeenCalled()
    })

    it('should clear input after adding tag', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput value={[]} onChange={handleChange} />
      )

      const input = screen.getByRole('textbox') as HTMLInputElement
      await user.type(input, 'production{Enter}')

      expect(input.value).toBe('')
    })
  })

  describe('removing tags', () => {
    it('should remove tag on X button click', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput
          value={['production', 'staging']}
          onChange={handleChange}
        />
      )

      const removeButtons = screen.getAllByRole('button', { name: /Remove/ })
      await user.click(removeButtons[0])

      expect(handleChange).toHaveBeenCalledWith(['staging'])
    })

    it('should remove last tag on Backspace with empty input', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput
          value={['production', 'staging']}
          onChange={handleChange}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, '{Backspace}')

      expect(handleChange).toHaveBeenCalledWith(['production'])
    })

    it('should not remove tag on Backspace with text in input', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput
          value={['production']}
          onChange={handleChange}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'test{Backspace}')

      expect(handleChange).not.toHaveBeenCalled()
    })
  })

  describe('autocomplete suggestions', () => {
    it('should show suggestions when typing', async () => {
      const user = userEvent.setup()

      render(
        <TagInput
          value={[]}
          onChange={vi.fn()}
          suggestions={['production', 'staging', 'development']}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'prod')

      expect(screen.getByText('production')).toBeInTheDocument()
    })

    it('should filter suggestions based on input', async () => {
      const user = userEvent.setup()

      render(
        <TagInput
          value={[]}
          onChange={vi.fn()}
          suggestions={['production', 'staging', 'development']}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'dev')

      expect(screen.getByText('development')).toBeInTheDocument()
      expect(screen.queryByText('production')).not.toBeInTheDocument()
    })

    it('should not show already selected tags in suggestions', async () => {
      const user = userEvent.setup()

      render(
        <TagInput
          value={['production']}
          onChange={vi.fn()}
          suggestions={['production', 'staging']}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 's')

      // Wait for suggestions to appear
      await waitFor(() => {
        expect(screen.getByText('staging')).toBeInTheDocument()
      })

      // staging should be in suggestions, production should not (except as a selected tag chip)
      expect(screen.getByText('staging')).toBeInTheDocument()

      // Get all buttons - suggestion buttons should not include 'production' (except the Remove button for the selected tag)
      const suggestionButtons = screen.getAllByRole('button').filter(btn => {
        const text = btn.textContent
        // Filter out the "Remove production" button (which is for the selected tag chip)
        return text && !text.includes('Remove')
      })

      // Should have a button for 'staging' but not for 'production'
      expect(suggestionButtons.some(btn => btn.textContent?.includes('staging'))).toBe(true)
      expect(suggestionButtons.filter(btn => btn.textContent?.includes('production')).length).toBe(0)
    })

    it('should add tag from suggestion on click', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput
          value={[]}
          onChange={handleChange}
          suggestions={['production']}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'prod')

      const suggestion = screen.getByText('production').closest('button')
      await user.click(suggestion!)

      expect(handleChange).toHaveBeenCalledWith(['production'])
    })

    it('should close suggestions on Escape key', async () => {
      const user = userEvent.setup()

      render(
        <TagInput
          value={[]}
          onChange={vi.fn()}
          suggestions={['production']}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'prod')
      expect(screen.getByText('production')).toBeInTheDocument()

      await user.type(input, '{Escape}')
      expect(screen.queryByText('production')).not.toBeInTheDocument()
    })
  })

  describe('keyboard navigation', () => {
    it('should navigate suggestions with arrow keys', async () => {
      const user = userEvent.setup()

      render(
        <TagInput
          value={[]}
          onChange={vi.fn()}
          suggestions={['production', 'preview', 'development']}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'p')

      // Should show "production" and "preview" (both match "p")
      expect(screen.getByText('production')).toBeInTheDocument()
      expect(screen.getByText('preview')).toBeInTheDocument()

      // Arrow down to select first suggestion
      await user.type(input, '{ArrowDown}')
      const firstButton = screen.getByText('production').closest('button')
      expect(firstButton).toHaveClass('bg-accent')

      // Arrow down again
      await user.type(input, '{ArrowDown}')
      const secondButton = screen.getByText('preview').closest('button')
      expect(secondButton).toHaveClass('bg-accent')
    })

    it('should select suggestion with Enter key', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput
          value={[]}
          onChange={handleChange}
          suggestions={['production', 'staging']}
        />
      )

      const input = screen.getByRole('textbox')
      await user.type(input, 'p')
      await user.type(input, '{ArrowDown}') // Select first
      await user.type(input, '{Enter}')

      expect(handleChange).toHaveBeenCalledWith(['production'])
    })
  })

  describe('disabled state', () => {
    it('should disable input and hide remove buttons when disabled', () => {
      render(
        <TagInput
          value={['production']}
          onChange={vi.fn()}
          disabled
        />
      )

      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
    })

    it('should not show suggestions when disabled', async () => {
      const user = userEvent.setup()

      render(
        <TagInput
          value={[]}
          onChange={vi.fn()}
          suggestions={['production']}
          disabled
        />
      )

      const input = screen.queryByRole('textbox')
      expect(input).not.toBeInTheDocument()
    })
  })

  describe('max tags validation', () => {
    it('should not add tag when max limit reached', async () => {
      const user = userEvent.setup()
      const handleChange = vi.fn()

      render(
        <TagInput
          value={['tag1', 'tag2']}
          onChange={handleChange}
          maxTags={2}
        />
      )

      // Input should be hidden
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
      expect(handleChange).not.toHaveBeenCalled()
    })
  })
})
