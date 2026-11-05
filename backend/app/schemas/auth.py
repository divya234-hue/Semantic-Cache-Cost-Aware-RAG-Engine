from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

RoleName = Literal["ADMIN", "EDITOR", "VIEWER"]


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    tenant_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)


class CreateUserRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    role: RoleName


class LoginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    display_name: str
    tenant_id: str
    role: RoleName
    is_active: bool = True


class UserListResponse(BaseModel):
    users: list[LoginResponse]


class UpdateRoleRequest(BaseModel):
    role: RoleName


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class DocumentPermissionInput(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    can_read: bool = True
    can_edit: bool = False

    @model_validator(mode="after")
    def edit_requires_read(self) -> "DocumentPermissionInput":
        if self.can_edit and not self.can_read:
            raise ValueError("Edit permission also requires read permission.")
        return self


class DocumentPermissionsRequest(BaseModel):
    permissions: list[DocumentPermissionInput]

    @model_validator(mode="after")
    def unique_users(self) -> "DocumentPermissionsRequest":
        user_ids = [permission.user_id for permission in self.permissions]
        if len(user_ids) != len(set(user_ids)):
            raise ValueError("A user can only appear once in the permission list.")
        return self


class DocumentPermissionsResponse(BaseModel):
    permissions: list[DocumentPermissionInput]
