"""
Authentication Models for DockMon
Pydantic models for authentication requests and responses
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Login request model with validation"""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class ChangePasswordRequest(BaseModel):
    """Change password request model"""
    current_password: str = Field(..., min_length=1, max_length=100)
    new_password: str = Field(..., min_length=8, max_length=100)  # Minimum 8 characters for security