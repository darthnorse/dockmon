/**
 * LoadingSkeleton Tests
 * Tests loading state display
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LoadingSkeleton } from './LoadingSkeleton'

describe('LoadingSkeleton', () => {
  describe('rendering', () => {
    it('should render container icon', () => {
      render(<LoadingSkeleton />)

      const icon = document.querySelector('.animate-pulse')
      expect(icon).toBeInTheDocument()
    })

    it('should have centered layout', () => {
      const { container } = render(<LoadingSkeleton />)

      const wrapper = container.querySelector('.flex.min-h-screen.items-center.justify-center')
      expect(wrapper).toBeInTheDocument()
    })

    it('should have background color', () => {
      const { container } = render(<LoadingSkeleton />)

      const wrapper = container.querySelector('.bg-background')
      expect(wrapper).toBeInTheDocument()
    })

    it('should render skeleton loaders', () => {
      render(<LoadingSkeleton />)

      const skeletons = document.querySelectorAll('.h-6, .h-4')
      expect(skeletons.length).toBeGreaterThan(0)
    })
  })

  describe('animation', () => {
    it('should have pulse animation on icon', () => {
      render(<LoadingSkeleton />)

      const icon = document.querySelector('.animate-pulse')
      expect(icon).toBeInTheDocument()
    })
  })

  describe('accessibility', () => {
    it('should be in a centered text container', () => {
      const { container } = render(<LoadingSkeleton />)

      const textCenter = container.querySelector('.text-center')
      expect(textCenter).toBeInTheDocument()
    })
  })
})
