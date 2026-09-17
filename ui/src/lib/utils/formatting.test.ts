import { describe, it, expect } from 'vitest'
import { formatBytes, formatMemory } from './formatting'

describe('formatBytes', () => {
  describe('Null/undefined handling', () => {
    it('should handle null bytes', () => {
      expect(formatBytes(null)).toBe('0 B')
    })

    it('should handle undefined bytes', () => {
      expect(formatBytes(undefined)).toBe('0 B')
    })

    it('should handle 0 bytes', () => {
      expect(formatBytes(0)).toBe('0 B')
    })
  })

  describe('Byte formatting', () => {
    it('should format values in bytes (< 1KB)', () => {
      expect(formatBytes(512)).toBe('512 B')
      expect(formatBytes(1023)).toBe('1023 B')
    })
  })

  describe('KB formatting', () => {
    it('should format values in KB with 1 decimal', () => {
      expect(formatBytes(1024)).toBe('1.0 KB')
      expect(formatBytes(512 * 1024)).toBe('512.0 KB')
      expect(formatBytes(1023 * 1024)).toBe('1023.0 KB')
    })
  })

  describe('MB formatting', () => {
    it('should format values in MB with 1 decimal', () => {
      expect(formatBytes(1024 * 1024)).toBe('1.0 MB')
      expect(formatBytes(256 * 1024 * 1024)).toBe('256.0 MB')
      expect(formatBytes(512.5 * 1024 * 1024)).toBe('512.5 MB')
    })
  })

  describe('GB formatting', () => {
    it('should format values in GB with 2 decimals', () => {
      expect(formatBytes(1024 * 1024 * 1024)).toBe('1.00 GB')
      expect(formatBytes(2.41 * 1024 * 1024 * 1024)).toBe('2.41 GB')
      expect(formatBytes(16 * 1024 * 1024 * 1024)).toBe('16.00 GB')
    })
  })

  describe('TB formatting', () => {
    it('should format very large values in TB with 2 decimals', () => {
      expect(formatBytes(1024 * 1024 * 1024 * 1024)).toBe('1.00 TB')
      expect(formatBytes(5.5 * 1024 * 1024 * 1024 * 1024)).toBe('5.50 TB')
    })
  })

  describe('Real-world container examples', () => {
    it('should format typical container memory values correctly', () => {
      expect(formatBytes(128 * 1024 * 1024)).toBe('128.0 MB')

      expect(formatBytes(512 * 1024 * 1024)).toBe('512.0 MB')

      expect(formatBytes(2.41 * 1024 * 1024 * 1024)).toBe('2.41 GB')

      expect(formatBytes(16 * 1024 * 1024 * 1024)).toBe('16.00 GB')
    })

    it('should handle tiny containers (< 1MB)', () => {
      expect(formatBytes(512 * 1024)).toBe('512.0 KB')
      expect(formatBytes(100 * 1024)).toBe('100.0 KB')
    })
  })

  describe('Edge cases', () => {
    it('should handle boundary between units', () => {
      expect(formatBytes(1023 * 1024)).toBe('1023.0 KB') // Just under 1MB
      expect(formatBytes(1024 * 1024)).toBe('1.0 MB') // Exactly 1MB
      expect(formatBytes(1025 * 1024)).toBe('1.0 MB') // Just over 1MB
    })
  })
})

describe('formatMemory', () => {
  describe('MB formatting (values < 1GB)', () => {
    it('should format small values as MB with no decimals', () => {
      expect(formatMemory(256 * 1024 * 1024)).toBe('256MB')
      expect(formatMemory(512 * 1024 * 1024)).toBe('512MB')
      expect(formatMemory(1000 * 1024 * 1024)).toBe('1000MB')
    })

    it('should round MB to nearest integer', () => {
      expect(formatMemory(256.7 * 1024 * 1024)).toBe('257MB') // Rounds up
      expect(formatMemory(256.3 * 1024 * 1024)).toBe('256MB') // Rounds down
      expect(formatMemory(256.5 * 1024 * 1024)).toBe('257MB') // Rounds up at .5
    })

    it('should handle very small values', () => {
      expect(formatMemory(1024)).toBe('0MB') // 1KB rounds to 0MB
      expect(formatMemory(0.5 * 1024 * 1024)).toBe('1MB') // 0.5MB rounds to 1MB
      expect(formatMemory(1024 * 1024)).toBe('1MB') // Exactly 1MB
    })
  })

  describe('GB formatting (values >= 1GB)', () => {
    it('should format values >= 1GB as GB with 2 decimals', () => {
      expect(formatMemory(1024 * 1024 * 1024)).toBe('1.00GB')
      expect(formatMemory(2.41 * 1024 * 1024 * 1024)).toBe('2.41GB')
      expect(formatMemory(16 * 1024 * 1024 * 1024)).toBe('16.00GB')
    })

    it('should format GB with exactly 2 decimals (rounding)', () => {
      expect(formatMemory(2.4156789 * 1024 * 1024 * 1024)).toBe('2.42GB') // Rounds up
      expect(formatMemory(2.4123456 * 1024 * 1024 * 1024)).toBe('2.41GB') // Rounds down
      expect(formatMemory(2.415 * 1024 * 1024 * 1024)).toBe('2.42GB') // Rounds up at .5
    })

    it('should handle large values', () => {
      expect(formatMemory(128 * 1024 * 1024 * 1024)).toBe('128.00GB')
      expect(formatMemory(256.75 * 1024 * 1024 * 1024)).toBe('256.75GB')
    })
  })

  describe('Edge cases and boundaries', () => {
    it('should handle 0 bytes', () => {
      expect(formatMemory(0)).toBe('0MB')
    })

    it('should handle boundary: exactly 1024MB (becomes 1.00GB)', () => {
      expect(formatMemory(1024 * 1024 * 1024)).toBe('1.00GB')
    })

    it('should handle boundary: just under 1024MB (stays MB)', () => {
      expect(formatMemory(1023 * 1024 * 1024)).toBe('1023MB')
      expect(formatMemory(1023.9 * 1024 * 1024)).toBe('1024MB') // Rounds to 1024MB
    })

    it('should handle boundary: just over 1024MB (becomes GB)', () => {
      expect(formatMemory(1025 * 1024 * 1024)).toBe('1.00GB')
    })
  })

  describe('Real-world examples from Issue #58', () => {
    it('should format the reported container memory (2.41GB)', () => {
      // User reported container showing "11MB" when it should be "2.41GB"
      // Container had memory_usage of 2.41GB
      expect(formatMemory(2.41 * 1024 * 1024 * 1024)).toBe('2.41GB')
    })

    it('should NOT format percentage as memory (regression test)', () => {
      // Old bug: showed memory_percent (11.2%) as "11MB"
      // This test verifies formatMemory() requires actual bytes, not percentage
      const memoryPercent = 11.2 // This is a percentage, not bytes
      const result = formatMemory(memoryPercent)
      expect(result).toBe('0MB') // 11.2 bytes = 0MB (proves function expects bytes)
    })

    it('should match typical container memory values', () => {
      expect(formatMemory(128 * 1024 * 1024)).toBe('128MB') // Small container
      expect(formatMemory(512 * 1024 * 1024)).toBe('512MB') // Medium container
      expect(formatMemory(1.5 * 1024 * 1024 * 1024)).toBe('1.50GB') // Large container
      expect(formatMemory(4 * 1024 * 1024 * 1024)).toBe('4.00GB') // Very large container
    })
  })
})
