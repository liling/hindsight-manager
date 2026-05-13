from hindsight_manager.models.user import User, UserRole


def test_user_role_enum_values():
    assert UserRole.ADMIN.value == "admin"
    assert UserRole.USER.value == "user"


def test_user_role_field_exists():
    u = User(
        username="testuser",
        display_name="Test",
        auth_provider="local",
        role=UserRole.USER,
    )
    assert u.role == UserRole.USER

    admin = User(
        username="admin",
        display_name="Admin",
        auth_provider="local",
        role=UserRole.ADMIN,
    )
    assert admin.role == UserRole.ADMIN
