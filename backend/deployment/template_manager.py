"""
Deployment template manager for DockMon v2.1

Manages reusable deployment templates with variable substitution.
Templates allow users to save container configurations and reuse them
with different parameters (ports, environment variables, etc.).

Usage:
    manager = TemplateManager()

    # Create template
    template_id = manager.create_template(
        name="Nginx Web Server",
        category="web-servers",
        deployment_type="container",
        template_definition={
            "image": "nginx:${VERSION}",
            "ports": {"80": "${PORT}"}
        },
        variables={
            "VERSION": {"default": "1.25", "type": "string", "description": "Nginx version"},
            "PORT": {"default": 8080, "type": "integer", "description": "Host port"}
        }
    )

    # Render template with values
    config = manager.render_template(template_id, {"VERSION": "1.26", "PORT": 9090})
"""

import json
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from database import DeploymentTemplate, DatabaseManager

logger = logging.getLogger(__name__)


class TemplateManager:
    """
    Manages deployment templates with variable substitution.

    Supports:
    - Template CRUD operations
    - Variable substitution (${VAR_NAME})
    - Built-in system templates vs user templates
    - Template categories for organization
    """

    def __init__(self, database_manager: DatabaseManager):
        """Initialize template manager with database access."""
        self.db = database_manager

    def _generate_template_id(self) -> str:
        """Generate template ID (format: tpl_<12_chars>)."""
        return f"tpl_{secrets.token_hex(6)}"  # tpl_a1b2c3d4e5f6

    def create_template(
        self,
        name: str,
        deployment_type: str,
        template_definition: Dict[str, Any],
        category: Optional[str] = None,
        description: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        is_builtin: bool = False,
    ) -> str:
        """
        Create a new deployment template.

        Args:
            name: Template name (must be unique)
            deployment_type: 'container' or 'stack'
            template_definition: Container/stack configuration with ${VAR} placeholders
            category: Optional category (e.g., 'web-servers', 'databases')
            description: Optional description
            variables: Variable definitions with defaults and types
            is_builtin: Whether this is a system template (default: False)

        Returns:
            Template ID (e.g., 'tpl_a1b2c3d4e5f6')

        Raises:
            ValueError: If name already exists or deployment_type invalid

        Example:
            >>> manager.create_template(
            ...     name="PostgreSQL Database",
            ...     deployment_type="container",
            ...     template_definition={
            ...         "image": "postgres:${VERSION}",
            ...         "environment": {
            ...             "POSTGRES_PASSWORD": "${DB_PASSWORD}",
            ...             "POSTGRES_DB": "${DB_NAME}"
            ...         },
            ...         "ports": {"5432": "${PORT}"}
            ...     },
            ...     variables={
            ...         "VERSION": {"default": "16", "type": "string"},
            ...         "DB_PASSWORD": {"default": "", "type": "password", "required": True},
            ...         "DB_NAME": {"default": "mydb", "type": "string"},
            ...         "PORT": {"default": 5432, "type": "integer"}
            ...     },
            ...     category="databases"
            ... )
        """
        with self.db.get_session() as session:
            # Validate deployment type
            if deployment_type not in ('container', 'stack'):
                raise ValueError(f"Invalid deployment_type: {deployment_type}")

            # Check for duplicate name
            existing = session.query(DeploymentTemplate).filter_by(name=name).first()
            if existing:
                raise ValueError(f"Template with name '{name}' already exists")

            # Generate template ID
            template_id = self._generate_template_id()
            utcnow = datetime.now(timezone.utc)

            # Create template
            template = DeploymentTemplate(
                id=template_id,
                name=name,
                category=category,
                description=description,
                deployment_type=deployment_type,
                template_definition=json.dumps(template_definition),
                variables=json.dumps(variables) if variables else None,
                is_builtin=is_builtin,
                created_at=utcnow,
                updated_at=utcnow,
            )

            session.add(template)
            session.commit()

            logger.info(f"Created template {template_id} ({name})")
            return template_id

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Get template by ID.

        Args:
            template_id: Template ID

        Returns:
            Template dict or None if not found
        """
        with self.db.get_session() as session:
            template = session.query(DeploymentTemplate).filter_by(id=template_id).first()
            if not template:
                return None

            return self._template_to_dict(template)

    def list_templates(
        self,
        category: Optional[str] = None,
        deployment_type: Optional[str] = None,
        include_builtin: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List templates with optional filters.

        Args:
            category: Filter by category (optional)
            deployment_type: Filter by type (optional)
            include_builtin: Include system templates (default: True)

        Returns:
            List of template dicts
        """
        with self.db.get_session() as session:
            query = session.query(DeploymentTemplate)

            if category:
                query = query.filter_by(category=category)

            if deployment_type:
                query = query.filter_by(deployment_type=deployment_type)

            if not include_builtin:
                query = query.filter_by(is_builtin=False)

            templates = query.order_by(DeploymentTemplate.name).all()
            return [self._template_to_dict(t) for t in templates]

    def update_template(
        self,
        template_id: str,
        name: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        template_definition: Optional[Dict[str, Any]] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update template fields.

        Args:
            template_id: Template ID
            name: New name (optional)
            category: New category (optional)
            description: New description (optional)
            template_definition: New definition (optional)
            variables: New variables (optional)

        Returns:
            True if updated, False if template not found

        Raises:
            ValueError: If new name conflicts with existing template
            RuntimeError: If trying to modify built-in template
        """
        with self.db.get_session() as session:
            template = session.query(DeploymentTemplate).filter_by(id=template_id).first()
            if not template:
                return False

            # Prevent modification of built-in templates
            if template.is_builtin:
                raise RuntimeError("Cannot modify built-in system templates")

            # Check for name conflict
            if name and name != template.name:
                existing = session.query(DeploymentTemplate).filter_by(name=name).first()
                if existing:
                    raise ValueError(f"Template with name '{name}' already exists")
                template.name = name

            # Update fields
            if category is not None:
                template.category = category
            if description is not None:
                template.description = description
            if template_definition is not None:
                template.template_definition = json.dumps(template_definition)
            if variables is not None:
                template.variables = json.dumps(variables)

            template.updated_at = datetime.now(timezone.utc)
            session.commit()

            logger.info(f"Updated template {template_id}")
            return True

    def delete_template(self, template_id: str) -> bool:
        """
        Delete template.

        Args:
            template_id: Template ID

        Returns:
            True if deleted, False if not found

        Raises:
            RuntimeError: If trying to delete built-in template
        """
        with self.db.get_session() as session:
            template = session.query(DeploymentTemplate).filter_by(id=template_id).first()
            if not template:
                return False

            # Prevent deletion of built-in templates
            if template.is_builtin:
                raise RuntimeError("Cannot delete built-in system templates")

            session.delete(template)
            session.commit()

            logger.info(f"Deleted template {template_id}")
            return True

    def render_template(
        self,
        template_id: str,
        values: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Render template with variable substitution.

        Replaces ${VAR_NAME} placeholders with provided values.
        Falls back to default values if not provided.

        Args:
            template_id: Template ID
            values: Variable values (overrides defaults)

        Returns:
            Rendered configuration dictionary

        Raises:
            ValueError: If template not found or required variable missing

        Example:
            >>> template_id = "tpl_nginx"
            >>> config = manager.render_template(template_id, {"PORT": 8080, "VERSION": "1.26"})
            >>> print(config)
            {"image": "nginx:1.26", "ports": {"80": 8080}}
        """
        with self.db.get_session() as session:
            template = session.query(DeploymentTemplate).filter_by(id=template_id).first()
            if not template:
                raise ValueError(f"Template {template_id} not found")

            # Parse template definition and variables
            template_def = json.loads(template.template_definition)
            variables = json.loads(template.variables) if template.variables else {}

            # Build final values (defaults + overrides)
            final_values = {}
            for var_name, var_config in variables.items():
                if var_name in values:
                    final_values[var_name] = values[var_name]
                elif 'default' in var_config:
                    final_values[var_name] = var_config['default']
                elif var_config.get('required', False):
                    raise ValueError(f"Required variable '{var_name}' not provided")

            # Perform variable substitution
            rendered = self._substitute_variables(template_def, final_values)

            logger.debug(f"Rendered template {template_id} with {len(final_values)} variables")
            return rendered

    def _substitute_variables(self, obj: Any, values: Dict[str, Any]) -> Any:
        """
        Recursively substitute ${VAR_NAME} in strings.

        Args:
            obj: Object to process (dict, list, str, or primitive)
            values: Variable values

        Returns:
            Object with variables substituted
        """
        if isinstance(obj, str):
            # Replace ${VAR_NAME} with value
            def replacer(match):
                var_name = match.group(1)
                if var_name not in values:
                    logger.warning(f"Variable ${{{var_name}}} not found in values")
                    return match.group(0)  # Keep placeholder
                return str(values[var_name])

            return re.sub(r'\$\{([A-Z_][A-Z0-9_]*)\}', replacer, obj)

        elif isinstance(obj, dict):
            return {k: self._substitute_variables(v, values) for k, v in obj.items()}

        elif isinstance(obj, list):
            return [self._substitute_variables(item, values) for item in obj]

        else:
            # Primitive (int, bool, None, etc.) - return as-is
            return obj

    def _template_to_dict(self, template: DeploymentTemplate) -> Dict[str, Any]:
        """Convert template model to dict for API responses."""
        return {
            'id': template.id,
            'name': template.name,
            'category': template.category,
            'description': template.description,
            'deployment_type': template.deployment_type,
            'template_definition': json.loads(template.template_definition),
            'variables': json.loads(template.variables) if template.variables else {},
            'is_builtin': template.is_builtin,
            'created_at': template.created_at.isoformat() + 'Z' if template.created_at else None,
            'updated_at': template.updated_at.isoformat() + 'Z' if template.updated_at else None,
        }
