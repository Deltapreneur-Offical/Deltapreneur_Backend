from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_sockjs_probe_endpoints_do_not_404():
    checks = [
        ("get", "/ws"),
        ("post", "/ws"),
        ("get", "/ws/info"),
        ("get", "/ws/iframe.html"),
        ("get", "/ws/000/session123/xhr_streaming"),
        ("post", "/ws/000/session123/xhr_streaming"),
        ("post", "/ws/000/session123/xhr_send"),
        ("get", "/ws/000/session123/xhr"),
        ("post", "/ws/000/session123/xhr"),
        ("get", "/ws/000/session123/eventsource"),
        ("get", "/ws/000/session123/jsonp"),
        ("post", "/ws/000/session123/jsonp_send"),
        ("get", "/ws/unexpected/probe"),
        ("post", "/ws/unexpected/probe"),
    ]

    for method, path in checks:
        response = getattr(client, method)(path)
        assert response.status_code != 404, f"{method.upper()} {path} returned 404"
