/**
 * Card Component Tests
 *
 * COVERAGE:
 * - Rendering Card and all subcomponents
 * - Proper semantic HTML structure
 * - Design system classes applied
 * - Custom className merging
 * - Composition of Card parts
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from './card'

describe('Card', () => {
  describe('Card', () => {
    it('should render card with design system styles', () => {
      render(<Card data-testid="card">Card content</Card>)

      const card = screen.getByTestId('card')
      expect(card).toBeInTheDocument()
      expect(card).toHaveClass('rounded-2xl', 'border', 'bg-card', 'shadow-card')
    })

    it('should merge custom className', () => {
      render(
        <Card data-testid="card" className="custom-class">
          Content
        </Card>
      )

      const card = screen.getByTestId('card')
      expect(card).toHaveClass('rounded-2xl', 'custom-class')
    })

    it('should forward ref to div element', () => {
      const ref = { current: null }

      render(<Card ref={ref}>Content</Card>)

      expect(ref.current).toBeInstanceOf(HTMLDivElement)
    })
  })

  describe('CardHeader', () => {
    it('should render card header with proper spacing', () => {
      render(<CardHeader data-testid="header">Header content</CardHeader>)

      const header = screen.getByTestId('header')
      expect(header).toBeInTheDocument()
      expect(header).toHaveClass('flex', 'flex-col', 'space-y-1.5', 'p-5')
    })

    it('should merge custom className', () => {
      render(
        <CardHeader data-testid="header" className="custom-header">
          Header
        </CardHeader>
      )

      const header = screen.getByTestId('header')
      expect(header).toHaveClass('flex', 'custom-header')
    })
  })

  describe('CardTitle', () => {
    it('should render as h3 with proper styling', () => {
      render(<CardTitle>Card Title</CardTitle>)

      const title = screen.getByText('Card Title')
      expect(title.tagName).toBe('H3')
      expect(title).toHaveClass('text-xl', 'font-semibold', 'leading-none')
    })

    it('should merge custom className', () => {
      render(<CardTitle className="custom-title">Title</CardTitle>)

      const title = screen.getByText('Title')
      expect(title).toHaveClass('text-xl', 'custom-title')
    })
  })

  describe('CardDescription', () => {
    it('should render as p with muted text', () => {
      render(<CardDescription>Card description</CardDescription>)

      const description = screen.getByText('Card description')
      expect(description.tagName).toBe('P')
      expect(description).toHaveClass('text-sm', 'text-muted-foreground')
    })

    it('should merge custom className', () => {
      render(
        <CardDescription className="custom-desc">Description</CardDescription>
      )

      const description = screen.getByText('Description')
      expect(description).toHaveClass('text-sm', 'custom-desc')
    })
  })

  describe('CardContent', () => {
    it('should render with proper padding', () => {
      render(<CardContent data-testid="content">Content</CardContent>)

      const content = screen.getByTestId('content')
      expect(content).toBeInTheDocument()
      expect(content).toHaveClass('p-5', 'pt-0')
    })

    it('should merge custom className', () => {
      render(
        <CardContent data-testid="content" className="custom-content">
          Content
        </CardContent>
      )

      const content = screen.getByTestId('content')
      expect(content).toHaveClass('p-5', 'custom-content')
    })
  })

  describe('CardFooter', () => {
    it('should render with flex layout', () => {
      render(<CardFooter data-testid="footer">Footer</CardFooter>)

      const footer = screen.getByTestId('footer')
      expect(footer).toBeInTheDocument()
      expect(footer).toHaveClass('flex', 'items-center', 'p-5', 'pt-0')
    })

    it('should merge custom className', () => {
      render(
        <CardFooter data-testid="footer" className="custom-footer">
          Footer
        </CardFooter>
      )

      const footer = screen.getByTestId('footer')
      expect(footer).toHaveClass('flex', 'custom-footer')
    })
  })

  describe('composition', () => {
    it('should render complete card with all parts', () => {
      render(
        <Card data-testid="complete-card">
          <CardHeader>
            <CardTitle>Test Card</CardTitle>
            <CardDescription>This is a test card</CardDescription>
          </CardHeader>
          <CardContent>
            <p>Main content goes here</p>
          </CardContent>
          <CardFooter>
            <button>Action</button>
          </CardFooter>
        </Card>
      )

      expect(screen.getByTestId('complete-card')).toBeInTheDocument()
      expect(screen.getByText('Test Card')).toBeInTheDocument()
      expect(screen.getByText('This is a test card')).toBeInTheDocument()
      expect(screen.getByText('Main content goes here')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /action/i })).toBeInTheDocument()
    })

    it('should work with partial composition', () => {
      render(
        <Card>
          <CardHeader>
            <CardTitle>Simple Card</CardTitle>
          </CardHeader>
          <CardContent>Content only, no footer</CardContent>
        </Card>
      )

      expect(screen.getByText('Simple Card')).toBeInTheDocument()
      expect(screen.getByText('Content only, no footer')).toBeInTheDocument()
    })
  })
})
