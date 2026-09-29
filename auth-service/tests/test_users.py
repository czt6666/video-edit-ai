import pytest

from app import users as u


def test_create_and_fetch(conn):
    created = u.create_user(conn, "alice", "password1", is_admin=False)
    assert created["id"] > 0
    assert created["username"] == "alice"
    assert created["is_admin"] is False

    by_id = u.get_user_by_id(conn, created["id"])
    by_name = u.get_user_by_name(conn, "alice")
    assert by_id == by_name
    # Public views never leak the hash.
    assert "password_hash" not in by_id


def test_duplicate_username_rejected(conn):
    u.create_user(conn, "bob", "password1")
    with pytest.raises(u.DuplicateUser):
        u.create_user(conn, "bob", "otherpass")


@pytest.mark.parametrize("bad", ["", "a b", "no/slash", "x" * 65, "eé"])
def test_username_validation(conn, bad):
    with pytest.raises(u.ValidationError):
        u.create_user(conn, bad, "password1")


@pytest.mark.parametrize("bad", ["", "x" * 73])
def test_password_validation(conn, bad):
    with pytest.raises(u.ValidationError):
        u.create_user(conn, "gooduser", bad)


def test_short_password_allowed(conn):
    # Login is intentionally low-friction: short passwords are fine.
    assert u.create_user(conn, "shortpw", "1")["username"] == "shortpw"


def test_authenticate(conn):
    u.create_user(conn, "carol", "s3cretpw")
    assert u.authenticate(conn, "carol", "s3cretpw")["username"] == "carol"
    assert u.authenticate(conn, "carol", "wrong") is None
    assert u.authenticate(conn, "ghost", "whatever") is None
    assert u.authenticate(conn, None, None) is None


def test_list_and_count(conn):
    assert u.count_users(conn) == 0
    u.create_user(conn, "a", "password1")
    u.create_user(conn, "b", "password1")
    listed = u.list_users(conn)
    assert [x["username"] for x in listed] == ["a", "b"]
    assert u.count_users(conn) == 2


def test_delete_user(conn):
    a = u.create_user(conn, "keep", "password1", is_admin=True)
    b = u.create_user(conn, "drop", "password1")
    u.delete_user(conn, b["id"])
    assert u.get_user_by_id(conn, b["id"]) is None
    with pytest.raises(u.UserNotFound):
        u.delete_user(conn, 99999)
    # Deleting the last admin is refused.
    with pytest.raises(u.ValidationError):
        u.delete_user(conn, a["id"])


def test_seed_admin_idempotent(conn):
    u.seed_admin(conn, "admin", "admin-pass")
    u.seed_admin(conn, "admin", "admin-pass")  # second call is a no-op
    admins = [x for x in u.list_users(conn) if x["is_admin"]]
    assert len(admins) == 1
    assert admins[0]["username"] == "admin"
