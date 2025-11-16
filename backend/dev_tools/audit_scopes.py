"""
Development tool to audit API endpoint scope enforcement.

Purpose:
- Verify that all mutating endpoints (POST/PUT/PATCH/DELETE) have scope checks
- Identify security gaps where scope enforcement is missing
- Run as part of CI/CD pipeline

Usage:
    python backend/dev_tools/audit_scopes.py

Output:
    ✅ Endpoints with proper scope enforcement
    ⚠️  Endpoints missing scope checks (SECURITY ISSUE)
    ℹ️  Public/auth endpoints (no scope check needed)

Exit codes:
    0 - All checks passed
    1 - Missing scope enforcement found
"""

import sys
import os
from typing import List, Dict, Set
import re

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from main import app
except ImportError as e:
    print(f"Error importing app: {e}")
    print("Make sure you're running from the DockMon root directory")
    sys.exit(1)


class EndpointAuditor:
    """Audit API endpoints for scope enforcement"""

    def __init__(self):
        self.endpoints: List[Dict] = []
        self.issues: List[str] = []
        self.total = 0
        self.passed = 0
        self.failed = 0

    def scan_endpoints(self) -> None:
        """Scan all endpoints in the FastAPI app"""
        for route in app.routes:
            # Skip routes without methods or path
            if not hasattr(route, 'methods') or not hasattr(route, 'path'):
                continue

            # Skip internal routes
            if self._is_internal_route(route.path):
                continue

            self.total += 1

            method = list(route.methods)[0] if route.methods else "UNKNOWN"
            dependencies = getattr(route, 'dependencies', [])

            endpoint_info = {
                'method': method,
                'path': route.path,
                'has_scope_check': self._has_scope_check(dependencies),
                'has_auth': self._has_auth(dependencies),
                'dependencies': dependencies
            }

            self.endpoints.append(endpoint_info)

    def _is_internal_route(self, path: str) -> bool:
        """Check if route is internal (docs, health, etc)"""
        internal_prefixes = [
            '/docs',
            '/openapi',
            '/redoc',
            '/.well-known',
            '/health',
            '/'
        ]
        return any(path.startswith(prefix) for prefix in internal_prefixes)

    def _has_scope_check(self, dependencies) -> bool:
        """Check if dependencies include scope enforcement"""
        if not dependencies:
            return False
        return any('require_scope' in str(dep) for dep in dependencies)

    def _has_auth(self, dependencies) -> bool:
        """Check if dependencies include authentication"""
        if not dependencies:
            return False
        dep_str = str(dependencies)
        return any(auth in dep_str for auth in [
            'get_current_user',
            'get_current_user_or_api_key',
            'Depends'
        ])

    def validate(self) -> bool:
        """Validate scope enforcement

        Returns:
            True if all endpoints pass validation, False otherwise
        """
        for endpoint in self.endpoints:
            method = endpoint['method']
            path = endpoint['path']
            has_scope = endpoint['has_scope_check']
            has_auth = endpoint['has_auth']

            # Determine if scope check is needed
            needs_scope = method in ['POST', 'PUT', 'PATCH', 'DELETE']

            # Check for public/auth endpoints
            is_login = '/auth' in path or '/login' in path or '/logout' in path

            # Validation logic
            if is_login:
                # Auth endpoints don't need scope check
                self.passed += 1
            elif needs_scope and not has_scope:
                # CRITICAL: Mutating endpoint without scope check!
                self.failed += 1
                self.issues.append(
                    f"MISSING SCOPE: {method:6} {path:50} - "
                    f"Mutating endpoint requires scope enforcement"
                )
            elif needs_scope and has_scope:
                # Good: Mutating endpoint has scope check
                self.passed += 1
            elif not needs_scope and has_auth:
                # Good: Read endpoint has auth
                self.passed += 1
            else:
                # Unknown endpoint type
                if not has_auth:
                    self.failed += 1
                    self.issues.append(
                        f"NO AUTH: {method:6} {path:50} - "
                        f"Endpoint has no authentication"
                    )
                else:
                    self.passed += 1

        return self.failed == 0

    def report(self) -> None:
        """Print audit report"""
        print("\n" + "=" * 90)
        print("API ENDPOINT SCOPE ENFORCEMENT AUDIT")
        print("=" * 90 + "\n")

        # Print each endpoint
        print("ENDPOINT DETAILS:")
        print("-" * 90)

        for endpoint in sorted(self.endpoints, key=lambda e: (e['method'], e['path'])):
            method = endpoint['method']
            path = endpoint['path']
            has_scope = endpoint['has_scope_check']
            has_auth = endpoint['has_auth']
            needs_scope = method in ['POST', 'PUT', 'PATCH', 'DELETE']

            if '/auth' in path or '/login' in path:
                status = "ℹ️  AUTH"
            elif needs_scope and has_scope:
                status = "✅ SCOPE"
            elif not needs_scope and has_auth:
                status = "✅ READ"
            elif needs_scope and not has_scope:
                status = "❌ FAIL"
            else:
                status = "⚠️  WARN"

            print(f"{status}  {method:6} {path:50}")

        # Print summary
        print("\n" + "=" * 90)
        print("SUMMARY")
        print("=" * 90)
        print(f"Total endpoints scanned: {self.total}")
        print(f"Passed validation:      {self.passed}")
        print(f"Failed validation:      {self.failed}")

        if self.issues:
            print(f"\n⚠️  {len(self.issues)} ISSUES FOUND:\n")
            for issue in self.issues:
                print(f"  {issue}")
            print("\n🔒 ACTION REQUIRED:")
            print("   Add require_scope('write') or require_scope('admin') to failing endpoints")
            print("   Example:")
            print("     @app.post('/api/...')")
            print("     async def endpoint(")
            print("         ...,")
            print("         current_user: dict = Depends(get_current_user_or_api_key),")
            print("         _check: dict = Depends(require_scope('write'))  # ADD THIS")
            print("     ):")
        else:
            print("\n✅ All endpoints have proper scope enforcement!")

        print("=" * 90 + "\n")

    def suggest_scope(self, method: str) -> str:
        """Suggest appropriate scope for endpoint"""
        if method in ['POST', 'PUT', 'PATCH']:
            return "write"
        elif method == 'DELETE':
            return "write"
        else:
            return "read"


def main():
    """Run the audit"""
    print("🔍 Scanning endpoints...")

    auditor = EndpointAuditor()
    auditor.scan_endpoints()

    print(f"   Found {auditor.total} endpoints")

    print("✓ Validating scope enforcement...")

    is_valid = auditor.validate()

    auditor.report()

    if is_valid:
        print("✅ AUDIT PASSED - All endpoints properly secured")
        return 0
    else:
        print("❌ AUDIT FAILED - Security issues found (see above)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
