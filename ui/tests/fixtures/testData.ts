/**
 * Sample test data for E2E tests.
 */

export const TEST_HOST = {
  id: '7be442c9-24bc-4047-b33a-41bbf51ea2f9',
  name: 'test-host',
  type: 'local' as const,
};

export const TEST_CONTAINER = {
  id: 'abc123def456',
  name: 'test-nginx',
  image: 'nginx:latest',
  status: 'running',
};

export const TEST_MANAGED_CONTAINER = {
  id: 'managed123',
  name: 'deployed-app',
  image: 'myapp:v1',
  status: 'running',
  deployment_id: '7be442c9-24bc-4047-b33a-41bbf51ea2f9:deploy-uuid',
  is_managed: true,
};
