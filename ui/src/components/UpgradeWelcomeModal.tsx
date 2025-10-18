import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { AlertTriangle, CheckCircle2, ExternalLink, X } from 'lucide-react';
import { apiClient } from '@/lib/api/client';
import { useAppVersion } from '@/lib/contexts/AppVersionContext';

interface UpgradeWelcomeModalProps {
  open: boolean;
  onClose: () => void;
}

export function UpgradeWelcomeModal({
  open,
  onClose
}: UpgradeWelcomeModalProps) {
  const { version } = useAppVersion();
  const githubReleasesUrl = `https://github.com/darthnorse/dockmon/releases/tag/v${version}`;
  const [dismissing, setDismissing] = useState(false);

  const handleDismiss = async () => {
    try {
      setDismissing(true);
      await apiClient.post('/upgrade-notice/dismiss', {});
      onClose();
    } catch (error) {
      console.error('Failed to dismiss upgrade notice:', error);
    } finally {
      setDismissing(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={handleDismiss}
    >
      <div
        className="relative w-full max-w-3xl max-h-[90vh] rounded-2xl border border-border bg-background shadow-lg overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-border">
          <div>
            <h2 className="text-2xl font-semibold">Welcome to DockMon v2!</h2>
            <p className="text-sm text-muted-foreground mt-1">
              A complete rewrite with powerful new features
            </p>
          </div>
          <button
            onClick={handleDismiss}
            disabled={dismissing}
            className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 disabled:opacity-50"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="space-y-6">
            <p className="text-base">
              DockMon v2 is a complete rewrite that brings everything we learned from v1
              and makes it significantly better!
            </p>

            {/* Highlights */}
            <div>
              <h4 className="font-semibold text-base mb-3">What's New</h4>
              <div className="grid gap-2">
                {[
                  'Customizable dashboard with drag-and-drop widgets',
                  'Tag support for better container organization',
                  'Bulk operations (start/stop/restart multiple containers)',
                  'Automatic container updates with schedules',
                  'Enhanced metrics and monitoring',
                  'Modern React-based interface',
                  'Improved security (Alpine Linux, OpenSSL 3.x)',
                ].map((feature, idx) => (
                  <div key={idx} className="flex items-start gap-2">
                    <CheckCircle2 className="h-4 w-4 text-success mt-0.5 shrink-0" />
                    <span className="text-sm">{feature}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border-t border-border pt-6" />

            {/* Breaking Change Warning */}
            <div className="rounded-lg border-l-4 border-danger bg-danger/10 p-4">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-5 w-5 text-danger shrink-0 mt-0.5" />
                <div className="flex-1">
                  <h4 className="text-base font-semibold text-danger mb-2">
                    Action Required: Migration Checklist
                  </h4>
                  <div className="space-y-4 text-sm">
                    <p>
                      Your hosts, containers, and event history have been preserved, but v2 has some breaking changes that require action:
                    </p>

                    <div>
                      <div className="font-semibold mb-2">1. Alert Rules (if applicable)</div>
                      <p className="mb-2">
                        v2 has a completely redesigned alert system. Your old alert rules were not migrated and need to be recreated using the new alerts interface.
                      </p>
                    </div>

                    <div>
                      <div className="font-semibold mb-2">2. mTLS Certificates (if applicable)</div>
                      <p className="mb-2">
                        If you have remote Docker hosts with mTLS enabled, you need to regenerate certificates due to Alpine's stricter security requirements.
                      </p>
                      <ol className="list-decimal list-inside space-y-2 pl-2">
                        <li>
                          On each remote host, download the updated script:
                          <div className="mt-1 bg-background/50 p-2 rounded font-mono text-xs overflow-x-auto">
                            curl -O https://raw.githubusercontent.com/darthnorse/dockmon/main/scripts/setup-docker-mtls.sh
                          </div>
                        </li>
                        <li>
                          Make it executable and run it:
                          <div className="mt-1 bg-background/50 p-2 rounded font-mono text-xs overflow-x-auto">
                            chmod +x setup-docker-mtls.sh && ./setup-docker-mtls.sh
                          </div>
                        </li>
                        <li>Restart Docker on the remote host</li>
                        <li>
                          In DockMon, edit each mTLS host and follow the instructions from the mTLS script to copy/paste the new certificates (ca.pem, cert.pem, key.pem)
                        </li>
                      </ol>
                    </div>

                    <Button
                      variant="outline"
                      size="sm"
                      asChild
                      className="mt-2"
                    >
                      <a href={githubReleasesUrl} target="_blank" rel="noopener noreferrer">
                        <ExternalLink className="h-3 w-3 mr-1" />
                        View detailed migration guide
                      </a>
                    </Button>
                  </div>
                </div>
              </div>
            </div>

            <div className="text-sm text-muted-foreground bg-muted/30 p-4 rounded-md">
              <p>
                We don't like breaking changes, but this was necessary to provide better
                security and enable future features. Thank you for your understanding!
              </p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 p-4 border-t border-border">
          <Button variant="outline" asChild>
            <a href={githubReleasesUrl} target="_blank" rel="noopener noreferrer">
              View Full Release Notes
            </a>
          </Button>
          <Button onClick={handleDismiss} disabled={dismissing}>
            {dismissing ? 'Dismissing...' : "Got it, don't show this again"}
          </Button>
        </div>
      </div>
    </div>
  );
}
