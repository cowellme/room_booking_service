from fastapi.testclient import TestClient
from app import main
from app.database import get_db
from app.security import current_user, csrf_protected
from tests.test_audit_fixes import env  # noqa: F401

def test_guide_is_persisted_per_account_for_admin_and_user(env):
    who = {"user": env.anna}
    main.app.dependency_overrides[get_db] = lambda: env.db
    main.app.dependency_overrides[current_user] = lambda: who["user"]
    main.app.dependency_overrides[csrf_protected] = lambda: who["user"]
    try:
        client = TestClient(main.app)
        assert client.get("/api/profile/extra-rooms-guide").json() == {"seen": False}
        assert client.post("/api/profile/extra-rooms-guide/seen").json() == {"seen": True}
        env.db.expire_all()
        assert client.get("/api/profile/extra-rooms-guide").json() == {"seen": True}
        who["user"] = env.admin
        assert client.get("/api/profile/extra-rooms-guide").json() == {"seen": False}
        assert client.post("/api/profile/extra-rooms-guide/seen").json() == {"seen": True}
        who["user"] = env.anna
        assert client.get("/api/profile/extra-rooms-guide").json() == {"seen": True}
    finally:
        main.app.dependency_overrides.clear()
