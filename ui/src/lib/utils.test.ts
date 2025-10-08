/**
 * Utils Tests - cn() function
 *
 * COVERAGE:
 * - Basic class merging
 * - Conditional classes with clsx
 * - Tailwind class deduplication
 * - Handling undefined/null values
 * - Complex scenarios with multiple conditions
 */

import { describe, it, expect } from 'vitest'
import { cn } from './utils'

describe('cn utility', () => {
  describe('basic functionality', () => {
    it('should merge multiple class strings', () => {
      const result = cn('class1', 'class2', 'class3')
      expect(result).toBe('class1 class2 class3')
    })

    it('should handle single class string', () => {
      const result = cn('single-class')
      expect(result).toBe('single-class')
    })

    it('should handle empty input', () => {
      const result = cn()
      expect(result).toBe('')
    })

    it('should handle undefined and null values', () => {
      const result = cn('class1', undefined, null, 'class2')
      expect(result).toBe('class1 class2')
    })
  })

  describe('conditional classes (clsx)', () => {
    it('should include classes when condition is truthy', () => {
      const isActive = true
      const result = cn('base', isActive && 'active')
      expect(result).toBe('base active')
    })

    it('should exclude classes when condition is falsy', () => {
      const isActive = false
      const result = cn('base', isActive && 'active')
      expect(result).toBe('base')
    })

    it('should handle object syntax for conditional classes', () => {
      const result = cn({
        'class1': true,
        'class2': false,
        'class3': true,
      })
      expect(result).toBe('class1 class3')
    })

    it('should handle arrays of classes', () => {
      const result = cn(['class1', 'class2'], 'class3')
      expect(result).toBe('class1 class2 class3')
    })
  })

  describe('Tailwind class deduplication (tailwind-merge)', () => {
    it('should deduplicate conflicting Tailwind classes - last wins', () => {
      const result = cn('px-2 py-1', 'px-4')
      expect(result).toBe('py-1 px-4')
    })

    it('should keep non-conflicting Tailwind classes', () => {
      const result = cn('px-4 py-2', 'text-sm')
      expect(result).toBe('px-4 py-2 text-sm')
    })

    it('should handle color variants properly', () => {
      const result = cn('bg-red-500', 'bg-blue-500')
      expect(result).toBe('bg-blue-500')
    })

    it('should handle responsive modifiers', () => {
      const result = cn('px-2', 'md:px-4', 'lg:px-6')
      expect(result).toBe('px-2 md:px-4 lg:px-6')
    })

    it('should deduplicate same responsive modifiers', () => {
      const result = cn('md:px-2', 'md:px-4')
      expect(result).toBe('md:px-4')
    })

    it('should handle state variants', () => {
      const result = cn('hover:bg-red-500', 'hover:bg-blue-500')
      expect(result).toBe('hover:bg-blue-500')
    })
  })

  describe('complex real-world scenarios', () => {
    it('should handle component variant merging', () => {
      // Simulating shadcn/ui button variants
      const baseClasses = 'inline-flex items-center rounded-lg'
      const variantClasses = 'bg-primary text-white'
      const customClasses = 'mt-4 bg-secondary'

      const result = cn(baseClasses, variantClasses, customClasses)

      // bg-secondary should override bg-primary, other classes preserved
      expect(result).toContain('inline-flex')
      expect(result).toContain('items-center')
      expect(result).toContain('rounded-lg')
      expect(result).toContain('text-white')
      expect(result).toContain('mt-4')
      expect(result).toContain('bg-secondary')
      expect(result).not.toContain('bg-primary')
    })

    it('should handle conditional component states', () => {
      const isLoading = true
      const isDisabled = false
      const size = 'lg'

      const result = cn(
        'button-base',
        isLoading && 'opacity-50 cursor-wait',
        isDisabled && 'opacity-50 cursor-not-allowed',
        {
          'h-8 px-3': size === 'sm',
          'h-10 px-4': size === 'md',
          'h-12 px-6': size === 'lg',
        }
      )

      expect(result).toContain('button-base')
      expect(result).toContain('opacity-50')
      expect(result).toContain('cursor-wait')
      expect(result).toContain('h-12')
      expect(result).toContain('px-6')
      expect(result).not.toContain('cursor-not-allowed')
    })

    it('should preserve custom non-Tailwind classes', () => {
      const result = cn('custom-animation', 'px-4', 'my-special-class')
      expect(result).toBe('custom-animation px-4 my-special-class')
    })

    it('should handle empty strings and whitespace', () => {
      const result = cn('class1', '', '  ', 'class2')
      expect(result).toBe('class1 class2')
    })
  })

  describe('edge cases', () => {
    it('should handle only falsy values', () => {
      const result = cn(false, null, undefined, '')
      expect(result).toBe('')
    })

    it('should handle nested arrays', () => {
      const result = cn(['class1', ['class2', 'class3']], 'class4')
      expect(result).toBe('class1 class2 class3 class4')
    })

    it('should handle multiple object conditions', () => {
      const result = cn(
        { 'class1': true, 'class2': false },
        { 'class3': true, 'class4': true }
      )
      expect(result).toBe('class1 class3 class4')
    })
  })
})
