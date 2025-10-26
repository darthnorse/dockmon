"""
Docker Compose file parser.

Parses Docker Compose YAML files and extracts service, network, and volume information.
Supports variable substitution and validates compose file structure.
"""

import re
import yaml


class ComposeParseError(Exception):
    """Raised when compose file cannot be parsed"""
    pass


class ComposeParser:
    """Parser for Docker Compose files"""

    def parse(self, compose_yaml: str, variables: dict = None):
        """
        Parse Docker Compose YAML content.

        Args:
            compose_yaml: YAML content as string
            variables: Dict of variables for ${VAR} substitution

        Returns:
            Parsed compose data as dict

        Raises:
            ComposeParseError: If YAML is invalid or required fields missing
        """
        if variables is None:
            variables = {}

        # Perform variable substitution
        yaml_with_vars = self._substitute_variables(compose_yaml, variables)

        # Parse YAML
        try:
            data = yaml.safe_load(yaml_with_vars)
        except yaml.YAMLError as e:
            raise ComposeParseError(f"Invalid YAML syntax: {e}")

        # Validate required fields
        if not isinstance(data, dict):
            raise ComposeParseError("Compose file must be a YAML object")

        # Note: 'version' is optional in Docker Compose Specification
        # (only required in legacy Compose file format v1/v2/v3)

        if 'services' not in data:
            raise ComposeParseError("Missing 'services' field")

        if not data['services']:
            raise ComposeParseError("No services defined")

        return data

    def _substitute_variables(self, yaml_content: str, variables: dict) -> str:
        """
        Substitute ${VAR} and ${VAR:-default} syntax with values.

        Args:
            yaml_content: YAML string with variables
            variables: Dict of variable values

        Returns:
            YAML string with variables substituted

        Raises:
            ComposeParseError: If required variable is missing
        """
        # Pattern matches ${VAR} or ${VAR:-default}
        pattern = r'\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}'

        def replace_var(match):
            var_name = match.group(1)
            has_default = match.group(2) is not None
            default_value = match.group(3) if has_default else None

            # Check if variable provided
            if var_name in variables:
                return variables[var_name]

            # Use default if available
            if has_default:
                return default_value

            # No variable and no default = error
            raise ComposeParseError(f"Missing required variable: {var_name}")

        return re.sub(pattern, replace_var, yaml_content)

    def get_service_names(self, compose_data: dict) -> list:
        """Extract list of service names from parsed compose data"""
        if 'services' not in compose_data:
            return []
        return list(compose_data['services'].keys())

    def get_network_names(self, compose_data: dict) -> list:
        """Extract list of network names from parsed compose data"""
        if 'networks' not in compose_data:
            return []
        return list(compose_data['networks'].keys())

    def get_volume_names(self, compose_data: dict) -> list:
        """Extract list of named volume names from parsed compose data"""
        if 'volumes' not in compose_data:
            return []
        return list(compose_data['volumes'].keys())
