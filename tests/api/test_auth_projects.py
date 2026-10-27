from tests.api.conftest import ORIGIN, PASSWORD


def test_login_me_logout(make_user):
    client = make_user("a@example.edu", login=False)
    r = client.post(
        "/api/auth/login", json={"email": "a@example.edu", "password": "wrong"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"

    r = client.post(
        "/api/auth/login", json={"email": "A@example.edu ", "password": PASSWORD}
    )
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower()
    assert r.json() == {
        "id": client.user_id,
        "email": "a@example.edu",
        "display_name": "a",
        "is_admin": False,
    }
    assert client.get("/api/auth/me").json()["email"] == "a@example.edu"

    assert client.post("/api/auth/logout").status_code == 204
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "AUTH_REQUIRED", "message": "请先登录"}}


def test_non_get_requires_origin(owner):
    r = owner.post(
        "/api/projects", json={"name": "x"}, headers={"Origin": "http://evil.example"}
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ORIGIN_REJECTED"
    del owner.headers["Origin"]
    assert owner.post("/api/projects", json={"name": "x"}).status_code == 403
    owner.headers["Origin"] = ORIGIN
    assert owner.post("/api/projects", json={"name": "x"}).status_code == 200


def test_validation_error_shape(owner):
    r = owner.post("/api/projects", json={"name": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_projects_and_members(owner, project, make_user):
    assert project["role"] == "owner"
    listing = owner.get("/api/projects").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == project["id"]

    other = make_user("other@example.edu")
    assert other.get(f"/api/projects/{project['id']}").status_code == 404
    assert other.get("/api/projects").json() == {"items": [], "total": 0}

    found = owner.get("/api/users", params={"email": "Other@example.edu"}).json()
    assert found["id"] == other.user_id
    assert (
        owner.get("/api/users", params={"email": "none@example.edu"}).status_code == 404
    )

    pid = project["id"]
    r = owner.put(
        f"/api/projects/{pid}/members/{other.user_id}", json={"role": "viewer"}
    )
    assert r.json() == {
        "user_id": other.user_id,
        "email": "other@example.edu",
        "role": "viewer",
    }
    assert other.get(f"/api/projects/{pid}").json()["role"] == "viewer"
    members = owner.get(f"/api/projects/{pid}/members").json()
    assert members["total"] == 2

    # viewer cannot manage members
    r = other.put(
        f"/api/projects/{pid}/members/{owner.user_id}", json={"role": "viewer"}
    )
    assert r.status_code == 403

    # the last owner cannot be demoted or removed
    r = owner.put(
        f"/api/projects/{pid}/members/{owner.user_id}", json={"role": "editor"}
    )
    assert r.status_code == 409
    assert (
        owner.delete(f"/api/projects/{pid}/members/{owner.user_id}").status_code == 409
    )

    assert (
        owner.delete(f"/api/projects/{pid}/members/{other.user_id}").status_code == 204
    )
    assert other.get(f"/api/projects/{pid}").status_code == 404


def test_role_matrix(owner, project, member, make_user):
    pid = project["id"]
    body = {"name": "作文", "language": "en"}
    for role, allowed in (("viewer", False), ("annotator", False), ("editor", True)):
        client = member(role)
        r = client.post(f"/api/projects/{pid}/corpora", json=body)
        assert (r.status_code == 200) is allowed, (role, r.text)
        listing = client.get("/api/corpora", params={"project_id": pid})
        assert listing.status_code == 200

    corpus = owner.post(f"/api/projects/{pid}/corpora", json=body).json()
    outsider = make_user("out@example.edu")
    assert outsider.get(f"/api/corpora/{corpus['id']}").status_code == 404
    assert outsider.get("/api/corpora", params={"project_id": pid}).status_code == 404


def test_builtin_corpora_admin_only(owner, project, make_user, member):
    admin = make_user("admin@example.edu", admin=True)
    body = {"name": "Tatoeba 中英", "language": "zh"}
    assert owner.post("/api/corpora", json=body).status_code == 403
    builtin = admin.post("/api/corpora", json=body).json()
    assert builtin["project_id"] is None and builtin["status"] == "empty"

    own = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "我的", "language": "zh"},
    ).json()
    listing = owner.get("/api/corpora", params={"project_id": project["id"]}).json()
    assert [c["id"] for c in listing["items"]] == [builtin["id"], own["id"]]
    assert owner.get("/api/corpora").json()["total"] == 1

    # any signed-in user reads built-in corpora; only admins change them
    viewer = member("viewer")
    assert viewer.get(f"/api/corpora/{builtin['id']}").status_code == 200
    assert owner.delete(f"/api/corpora/{builtin['id']}").status_code == 403
    assert owner.post(f"/api/corpora/{builtin['id']}/reindex").status_code == 403
    assert admin.delete(f"/api/corpora/{builtin['id']}").status_code == 204
