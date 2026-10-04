import uuid

import jwt
import pytest

from lumen.auth import hash_password, issue_access_token, verify_password
from lumen.config import get_settings
from lumen.models import Role


def test_password_hash_and_verification():
    encoded = hash_password("correct horse battery staple")
    assert encoded != "correct horse battery staple"
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_password_length_is_enforced():
    with pytest.raises(ValueError):
        hash_password("short")


def test_access_token_is_tenant_and_role_scoped():
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    token = issue_access_token(user_id, tenant_id, Role.admin)
    claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    assert claims["sub"] == str(user_id)
    assert claims["tid"] == str(tenant_id)
    assert claims["role"] == "admin"
