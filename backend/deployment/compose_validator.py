"""
Docker Compose YAML security validator.

Validates compose YAML files for safety before passing to Go Compose Service.
The Go Compose Service (using official Docker Compose SDK) handles all
structural validation, dependency checking, and configuration validation.
"""


class ComposeValidationError(Exception):
    """Raised when compose file validation fails"""
    pass


class ComposeValidator:
    """
    Security validator for Docker Compose files.

    Only performs security checks before YAML is sent to Go Compose Service.
    All structural validation is handled by the Go service.
    """

    # Dangerous YAML tags that could execute code
    DANGEROUS_TAGS = [
        '!!python/object',
        '!!python/name',
        '!!python/module',
        '!!python/object/apply',
        '!!python/object/new',
    ]

    def validate_yaml_safety(self, compose_yaml: str) -> None:
        """
        Validate YAML doesn't contain dangerous tags.

        This is a security check to prevent code execution via YAML deserialization.
        Must be called before passing YAML to Go Compose Service.

        Args:
            compose_yaml: YAML content as string

        Raises:
            ComposeValidationError: If unsafe tags found
        """
        for tag in self.DANGEROUS_TAGS:
            if tag in compose_yaml:
                raise ComposeValidationError(
                    f"Unsafe YAML tag detected: {tag}. This could execute arbitrary code."
                )
