"""
Unit tests for Docker Compose file parsing.

TDD Phase: RED - Write tests first for compose parsing

Tests cover:
- Parse valid compose v3 files
- Parse compose v2 files (legacy support)
- Extract services list
- Extract networks list
- Extract volumes list
- Variable substitution (${VAR} syntax)
"""

import pytest
from deployment.compose_parser import ComposeParser, ComposeParseError


class TestComposeParserV3:
    """Test parsing Docker Compose v3 files"""

    def test_parse_simple_compose_v3(self):
        """Should parse simple compose v3 file with one service"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:latest
    ports:
      - "80:80"
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)

        assert result['version'] == '3.8'
        assert 'services' in result
        assert 'web' in result['services']
        assert result['services']['web']['image'] == 'nginx:latest'
        assert result['services']['web']['ports'] == ['80:80']

    def test_parse_multi_service_compose(self):
        """Should parse compose file with multiple services"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: wordpress:latest
    depends_on:
      - db
  db:
    image: mysql:5.7
    environment:
      MYSQL_ROOT_PASSWORD: example
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)

        assert len(result['services']) == 2
        assert 'web' in result['services']
        assert 'db' in result['services']
        assert result['services']['web']['depends_on'] == ['db']
        assert result['services']['db']['environment']['MYSQL_ROOT_PASSWORD'] == 'example'

    def test_parse_compose_with_networks(self):
        """Should extract networks from compose file"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:latest
    networks:
      - frontend
networks:
  frontend:
    driver: bridge
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)

        assert 'networks' in result
        assert 'frontend' in result['networks']
        assert result['networks']['frontend']['driver'] == 'bridge'
        assert result['services']['web']['networks'] == ['frontend']

    def test_parse_compose_with_volumes(self):
        """Should extract volumes from compose file"""
        compose_yaml = """
version: '3.8'
services:
  db:
    image: postgres:latest
    volumes:
      - postgres_data:/var/lib/postgresql/data
volumes:
  postgres_data:
    driver: local
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)

        assert 'volumes' in result
        assert 'postgres_data' in result['volumes']
        assert result['volumes']['postgres_data']['driver'] == 'local'
        assert result['services']['db']['volumes'] == ['postgres_data:/var/lib/postgresql/data']

    def test_extract_services_list(self):
        """Should extract ordered list of service names"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:latest
  db:
    image: postgres:latest
  cache:
    image: redis:latest
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)
        services = parser.get_service_names(result)

        assert isinstance(services, list)
        assert len(services) == 3
        assert 'web' in services
        assert 'db' in services
        assert 'cache' in services

    def test_extract_networks_list(self):
        """Should extract list of network names"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:latest
networks:
  frontend:
  backend:
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)
        networks = parser.get_network_names(result)

        assert isinstance(networks, list)
        assert len(networks) == 2
        assert 'frontend' in networks
        assert 'backend' in networks

    def test_extract_volumes_list(self):
        """Should extract list of named volume names"""
        compose_yaml = """
version: '3.8'
services:
  db:
    image: postgres:latest
volumes:
  postgres_data:
  mysql_data:
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)
        volumes = parser.get_volume_names(result)

        assert isinstance(volumes, list)
        assert len(volumes) == 2
        assert 'postgres_data' in volumes
        assert 'mysql_data' in volumes


class TestComposeParserV2:
    """Test parsing Docker Compose v2 files (legacy support)"""

    def test_parse_compose_v2(self):
        """Should parse compose v2 file format"""
        compose_yaml = """
version: '2'
services:
  web:
    image: nginx:latest
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)

        assert result['version'] == '2'
        assert 'web' in result['services']
        assert result['services']['web']['image'] == 'nginx:latest'

    def test_parse_compose_v2_with_links(self):
        """Should parse compose v2 links (deprecated in v3)"""
        compose_yaml = """
version: '2'
services:
  web:
    image: wordpress:latest
    links:
      - db:mysql
  db:
    image: mysql:5.7
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml)

        assert result['services']['web']['links'] == ['db:mysql']


class TestComposeVariableSubstitution:
    """Test variable substitution in compose files"""

    def test_substitute_simple_variable(self):
        """Should substitute ${VAR} syntax with provided values"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:${NGINX_VERSION}
"""
        parser = ComposeParser()
        variables = {'NGINX_VERSION': 'alpine'}
        result = parser.parse(compose_yaml, variables=variables)

        assert result['services']['web']['image'] == 'nginx:alpine'

    def test_substitute_multiple_variables(self):
        """Should substitute multiple variables in one value"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: ${REGISTRY}/${IMAGE}:${TAG}
"""
        parser = ComposeParser()
        variables = {
            'REGISTRY': 'docker.io',
            'IMAGE': 'nginx',
            'TAG': 'latest'
        }
        result = parser.parse(compose_yaml, variables=variables)

        assert result['services']['web']['image'] == 'docker.io/nginx:latest'

    def test_substitute_with_default_value(self):
        """Should use default value when variable not provided"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:${VERSION:-latest}
"""
        parser = ComposeParser()
        result = parser.parse(compose_yaml, variables={})

        assert result['services']['web']['image'] == 'nginx:latest'

    def test_substitute_with_provided_override_default(self):
        """Should use provided value over default"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: nginx:${VERSION:-latest}
"""
        parser = ComposeParser()
        variables = {'VERSION': 'alpine'}
        result = parser.parse(compose_yaml, variables=variables)

        assert result['services']['web']['image'] == 'nginx:alpine'

    def test_missing_required_variable_raises_error(self):
        """Should raise error when required variable (no default) is missing"""
        compose_yaml = """
version: '3.8'
services:
  web:
    image: ${REQUIRED_IMAGE}
"""
        parser = ComposeParser()

        with pytest.raises(ComposeParseError, match="Missing required variable"):
            parser.parse(compose_yaml, variables={})


class TestComposeParserErrorHandling:
    """Test error handling for invalid compose files"""

    def test_invalid_yaml_raises_error(self):
        """Should raise error for invalid YAML syntax"""
        invalid_yaml = """
version: '3.8'
services:
  web:
    image: nginx:latest
    : invalid
"""
        parser = ComposeParser()

        with pytest.raises(ComposeParseError, match="Invalid YAML"):
            parser.parse(invalid_yaml)

    def test_missing_version_raises_error(self):
        """Should raise error when version field is missing"""
        compose_yaml = """
services:
  web:
    image: nginx:latest
"""
        parser = ComposeParser()

        with pytest.raises(ComposeParseError, match="Missing 'version' field"):
            parser.parse(compose_yaml)

    def test_missing_services_raises_error(self):
        """Should raise error when services field is missing"""
        compose_yaml = """
version: '3.8'
"""
        parser = ComposeParser()

        with pytest.raises(ComposeParseError, match="Missing 'services' field"):
            parser.parse(compose_yaml)

    def test_empty_services_raises_error(self):
        """Should raise error when services is empty"""
        compose_yaml = """
version: '3.8'
services: {}
"""
        parser = ComposeParser()

        with pytest.raises(ComposeParseError, match="No services defined"):
            parser.parse(compose_yaml)

    def test_unsupported_version_warns(self):
        """Should warn but parse unsupported compose versions"""
        compose_yaml = """
version: '1.0'
services:
  web:
    image: nginx:latest
"""
        parser = ComposeParser()

        # Should parse but may log warning
        result = parser.parse(compose_yaml)
        assert result['version'] == '1.0'
