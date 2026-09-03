"""In-memory showcase cancel helpers — no database."""

from app.service.domain.showcase_domain_service import (
    _finish_status,
    _start_status,
    get_generation_status,
    request_cancel_in_memory,
)


def test_request_cancel_in_memory_marks_running_generation():
    _start_status("gen-1", "random", 20, 10)
    request_cancel_in_memory("gen-1")
    status = get_generation_status("gen-1")
    assert status is not None
    assert status["cancelRequested"] is True
    assert "Stopping" in (status.get("phase") or "")


def test_finish_status_cancelled_does_not_look_like_complete():
    _start_status("gen-2", "keyword", 20, 5)
    _finish_status("gen-2", cancelled=True, message="Stopped. 3 candidate(s) kept.")
    status = get_generation_status("gen-2")
    assert status["state"] == "cancelled"
    assert status["phase"] == "Stopped."
    assert "3 candidate" in status["message"]
