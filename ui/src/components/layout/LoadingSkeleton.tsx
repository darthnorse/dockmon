/**
 * Loading Skeleton - Full Page
 *
 * Used while checking authentication status
 */

import { Container } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'

export function LoadingSkeleton() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center">
        <div className="mb-4 flex justify-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-primary/10">
            <Container className="h-8 w-8 animate-pulse text-primary" />
          </div>
        </div>
        <Skeleton className="mx-auto h-6 w-32" />
        <Skeleton className="mx-auto mt-2 h-4 w-48" />
      </div>
    </div>
  )
}
