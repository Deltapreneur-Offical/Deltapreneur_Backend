"""Virtual Assistant module unit tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.service.admin.virtual_assistant_admin_service import VirtualAssistantAdminService


def _make_role(**overrides):
    data = {
        "id": uuid.uuid4(),
        "application_id": uuid.uuid4(),
        "role_name": "Administrative Support",
        "status": "approved",
        "max_clients": 3,
        "current_clients": 0,
        "is_active": True,
        "reviewed_at": datetime.now(timezone.utc),
        "reviewed_by_id": str(uuid.uuid4()),
        "rejection_note": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _make_application(**overrides):
    data = {
        "id": uuid.uuid4(),
        "full_name": "Test VA",
        "email": "testva@example.com",
        "phone_number": "9876543210",
        "location": "Mumbai",
        "profile_photo_url": None,
        "profile_photo_key": "virtual-assistants/profile-photos/test-photo.jpg",
        "consent_adult": True,
        "short_bio": "Experienced VA",
        "roles": "Administrative Support,Customer Support",
        "skills": "Excel,Communication",
        "years_experience": "3-5 years",
        "languages_known": "English,Hindi",
        "linkedin_url": "https://linkedin.com/in/test",
        "portfolio_url": "https://portfolio.example.org",
        "resume_url": "https://drive.google.com/file/d/test-resume",
        "resume_filename": None,
        "resume_size": None,
        "availability": "available",
        "hours_per_week": "40",
        "expected_compensation": "₹20,000/month",
        "public_monthly_price_inr": 20000,
        "pricing_currency": "INR",
        "max_client_capacity": 3,
        "publish_status": "published",
        "overall_status": "approved",
        "published_at": datetime.now(timezone.utc),
        "featured": False,
        "workspace_locked": False,
        "is_deleted": False,
        "reference_number": "CB-VA-000001",
        "application_number": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TestAvailabilityCalculation:
    def test_available_when_zero_current(self):
        role = _make_role(max_clients=3, current_clients=0)
        result = VirtualAssistantAdminService._role_availability_status(role)
        assert result == "available"

    def test_limited_when_partial(self):
        role = _make_role(max_clients=3, current_clients=2)
        result = VirtualAssistantAdminService._role_availability_status(role)
        assert result == "limited"

    def test_not_available_when_full(self):
        role = _make_role(max_clients=3, current_clients=3)
        result = VirtualAssistantAdminService._role_availability_status(role)
        assert result == "not_available"

    def test_not_available_when_over(self):
        role = _make_role(max_clients=3, current_clients=5)
        result = VirtualAssistantAdminService._role_availability_status(role)
        assert result == "not_available"

    def test_available_when_no_max(self):
        role = _make_role(max_clients=None, current_clients=0)
        result = VirtualAssistantAdminService._role_availability_status(role)
        assert result == "available"

    def test_inactive_role_not_available(self):
        role = _make_role(max_clients=3, current_clients=0, is_active=False)
        result = VirtualAssistantAdminService._role_availability_status(role)
        assert result == "temporarily_unavailable"


class TestPublishValidation:
    def test_publish_requires_price(self):
        application = _make_application(public_monthly_price_inr=None, max_client_capacity=None)
        db = MagicMock()
        with patch.object(VirtualAssistantAdminService, 'list_application_roles', return_value=[]):
            errors = VirtualAssistantAdminService._validate_publish_requirements(db, application)
        assert any("price" in e.lower() for e in errors)

    def test_publish_requires_capacity(self):
        application = _make_application(public_monthly_price_inr=20000, max_client_capacity=None)
        db = MagicMock()
        with patch.object(VirtualAssistantAdminService, 'list_application_roles', return_value=[]):
            errors = VirtualAssistantAdminService._validate_publish_requirements(db, application)
        assert any("capacity" in e.lower() for e in errors)

    def test_publish_requires_approved_role(self):
        application = _make_application(public_monthly_price_inr=20000, max_client_capacity=3)
        db = MagicMock()
        with patch.object(VirtualAssistantAdminService, 'list_application_roles', return_value=[{"status": "pending"}]):
            errors = VirtualAssistantAdminService._validate_publish_requirements(db, application)
        assert any("approved" in e.lower() for e in errors)

    def test_publish_success(self):
        application = _make_application(public_monthly_price_inr=20000, max_client_capacity=3)
        db = MagicMock()
        with patch.object(VirtualAssistantAdminService, 'list_application_roles', return_value=[{"status": "approved"}]):
            errors = VirtualAssistantAdminService._validate_publish_requirements(db, application)
        assert len(errors) == 0


class TestCapacityUpdate:
    def test_capacity_update_success(self):
        role = _make_role(max_clients=3, current_clients=1)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = role
        result = VirtualAssistantAdminService.update_role_capacity(db, role.id, max_clients=5, current_clients=2, is_active=True)
        assert result["maxClients"] == 5
        assert result["currentClients"] == 2
        assert result["availabilityStatus"] == "limited"

    def test_capacity_update_negative_rejected(self):
        role = _make_role(max_clients=3, current_clients=1)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = role
        with pytest.raises(ValueError) as exc_info:
            VirtualAssistantAdminService.update_role_capacity(db, role.id, max_clients=-1, current_clients=1, is_active=True)
        assert "non-negative" in str(exc_info.value)

    def test_capacity_update_exceeds_max_rejected(self):
        role = _make_role(max_clients=3, current_clients=1)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = role
        with pytest.raises(ValueError) as exc_info:
            VirtualAssistantAdminService.update_role_capacity(db, role.id, max_clients=3, current_clients=5, is_active=True)
        assert "cannot exceed" in str(exc_info.value)


class TestWorkspaceUnlock:
    def test_workspace_unlocked_when_approved(self):
        application = _make_application(workspace_locked=True)
        db = MagicMock()
        row = _make_application(workspace_locked=True)
        db.query.return_value.filter.return_value.first.return_value = row
        db.query.return_value.filter.return_value.all.return_value = [_make_role(status="approved")]
        VirtualAssistantAdminService._recompute_workspace_lock(db, application.id)
        assert row.workspace_locked is False

    def test_workspace_remains_locked_when_rejected(self):
        application = _make_application(workspace_locked=True)
        db = MagicMock()
        row = _make_application(workspace_locked=True)
        db.query.return_value.filter.return_value.first.return_value = row
        db.query.return_value.filter.return_value.all.return_value = [_make_role(status="rejected")]
        VirtualAssistantAdminService._recompute_workspace_lock(db, application.id)
        assert row.workspace_locked is True


class TestVANotificationDeduplication:
    def test_notification_deduplication_identical_title_and_message(self):
        db = MagicMock()
        app_id = uuid.uuid4()
        user_id = uuid.uuid4()
        app_row = SimpleNamespace(id=app_id, user_id=user_id, email="test@example.com")
        db.query.return_value.filter.return_value.first.return_value = app_row

        VirtualAssistantAdminService._create_va_notification(
            db,
            app_id,
            "pricing_updated",
            message="Your customer monthly price has been updated to INR 35000.",
            title="Your customer monthly price has been updated to INR 35000.",
        )

        added = db.add.call_args[0][0]
        assert added.title == "Your customer monthly price has been updated to INR 35000."
        assert added.message is None

    def test_notification_deduplication_message_only(self):
        db = MagicMock()
        app_id = uuid.uuid4()
        user_id = uuid.uuid4()
        app_row = SimpleNamespace(id=app_id, user_id=user_id, email="test@example.com")
        db.query.return_value.filter.return_value.first.return_value = app_row

        VirtualAssistantAdminService._create_va_notification(
            db,
            app_id,
            "role_approved",
            message="Your role 'Data Entry' has been approved.",
        )

        added = db.add.call_args[0][0]
        assert added.title == "Your role 'Data Entry' has been approved."
        assert added.message is None

    def test_notification_preserves_distinct_title_and_message(self):
        db = MagicMock()
        app_id = uuid.uuid4()
        user_id = uuid.uuid4()
        app_row = SimpleNamespace(id=app_id, user_id=user_id, email="test@example.com")
        db.query.return_value.filter.return_value.first.return_value = app_row

        VirtualAssistantAdminService._create_va_notification(
            db,
            app_id,
            "application_submitted",
            message="Your application (VA-12345) has been submitted successfully.",
            title="Application Submitted",
        )

        added = db.add.call_args[0][0]
        assert added.title == "Application Submitted"
        assert added.message == "Your application (VA-12345) has been submitted successfully."


class TestPublicSerialization:
    def test_serialize_public_omits_private_fields(self):
        db = MagicMock()
        app = _make_application()
        with patch.object(
            VirtualAssistantAdminService,
            "_public_application_roles",
            return_value=[{
                "id": "role-1",
                "roleName": "Administrative Support",
                "status": "approved",
                "maxClients": 3,
                "currentClients": 0,
                "isActive": True,
                "availabilityStatus": "available",
            }],
        ):
            payload = VirtualAssistantAdminService._serialize_public(db, app)

        assert "expectedCompensation" not in payload
        assert "email" not in payload
        assert "phoneNumber" not in payload
        assert "adminNotes" not in payload
        assert "resumeUrl" not in payload
        assert payload["publicMonthlyPriceInr"] == 20000
        assert payload["roles"] == "Administrative Support"
        assert payload["publishStatus"] == "published"
        assert payload["overallStatus"] == "approved"
        assert payload["featured"] is False
        assert len(payload["applicationRoles"]) == 1


class TestPublicEligibility:
    def test_is_publicly_listable_requires_active_approved_role(self):
        db = MagicMock()
        app = _make_application()
        db.query.return_value.filter.return_value.first.return_value = uuid.uuid4()
        assert VirtualAssistantAdminService.is_publicly_listable(db, app) is True

    def test_is_publicly_listable_false_without_public_price(self):
        db = MagicMock()
        app = _make_application(public_monthly_price_inr=None)
        assert VirtualAssistantAdminService.is_publicly_listable(db, app) is False


class TestVaReferenceNumbers:
    def test_format_reference_number(self):
        from app.service.virtual_assistant.reference_number_service import format_reference_number

        assert format_reference_number(1) == "CB-VA-000001"
        assert format_reference_number(42) == "CB-VA-000042"

    def test_format_application_number_display(self):
        from app.service.virtual_assistant.reference_number_service import format_application_number_display

        assert format_application_number_display(1) == "01"
        assert format_application_number_display(12) == "12"

    def test_application_number_fields_from_row(self):
        from app.service.virtual_assistant.reference_number_service import application_number_fields

        row = _make_application(application_number=7, reference_number="CB-VA-000007")
        fields = application_number_fields(row)
        assert fields["applicationNumber"] == 7
        assert fields["applicationNumberDisplay"] == "07"

    def test_integrity_error_message_for_phone_required(self):
        from sqlalchemy.exc import IntegrityError
        from app.service.virtual_assistant.virtual_assistant_service import _integrity_error_message

        exc = IntegrityError("stmt", {}, Exception('null value in column "phone_number" violates not-null constraint'))
        assert _integrity_error_message(exc) == "Phone number is required."


class TestApplicantRoleSummaries:
    def test_list_applicant_role_summaries_returns_one_row_per_role(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        db = MagicMock()
        app_one = SimpleNamespace(
            id="app-1",
            reference_number="CB-VA-000001",
            roles="Customer Support",
            expected_compensation="₹35,000/month",
            public_monthly_price_inr=15000,
            pricing_currency="INR",
        )
        app_two = SimpleNamespace(
            id="app-2",
            reference_number="CB-VA-000002",
            roles="Social Media Manager",
            expected_compensation="₹35,000/month",
            public_monthly_price_inr=None,
            pricing_currency="INR",
        )
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            app_one,
            app_two,
        ]

        with (
            patch(
                "app.service.admin.virtual_assistant_admin_service.VirtualAssistantAdminService._ensure_roles"
            ),
            patch(
                "app.service.admin.virtual_assistant_admin_service.VirtualAssistantAdminService.list_application_roles",
                side_effect=[
                    [{"id": "role-1", "roleName": "Customer Support", "status": "approved"}],
                    [{"id": "role-2", "roleName": "Social Media Manager", "status": "pending"}],
                ],
            ),
        ):
            rows = VirtualAssistantAdminService.list_applicant_role_summaries(
                db, "applicant@example.com"
            )

        assert len(rows) == 2
        assert rows[0]["referenceNumber"] == "CB-VA-000001"
        assert rows[1]["referenceNumber"] == "CB-VA-000002"
        assert rows[0]["status"] == "approved"
        assert rows[1]["publicMonthlyPriceInr"] is None


class TestValidateLinkedinProfileUrl:
    def test_accepts_standard_profile_url(self):
        from app.service.virtual_assistant.va_media import validate_linkedin_profile_url

        assert (
            validate_linkedin_profile_url("https://www.linkedin.com/in/sushma-aiholli")
            == "https://www.linkedin.com/in/sushma-aiholli"
        )

    def test_normalizes_url_without_protocol(self):
        from app.service.virtual_assistant.va_media import validate_linkedin_profile_url

        assert (
            validate_linkedin_profile_url("linkedin.com/in/test-user")
            == "https://linkedin.com/in/test-user"
        )

    def test_rejects_empty_url(self):
        from fastapi import HTTPException

        from app.service.virtual_assistant.va_media import validate_linkedin_profile_url

        with pytest.raises(HTTPException) as exc:
            validate_linkedin_profile_url("")
        assert exc.value.detail == "LinkedIn Profile URL is required."

    def test_rejects_invalid_profile_url(self):
        from fastapi import HTTPException

        from app.service.virtual_assistant.va_media import validate_linkedin_profile_url

        with pytest.raises(HTTPException) as exc:
            validate_linkedin_profile_url("https://example.com/in/test")
        assert exc.value.detail == "Please enter a valid LinkedIn profile URL."


class TestAdminDirectAddValidation:
    def test_rejects_missing_linkedin_before_upload(self):
        from fastapi import HTTPException

        db = MagicMock()
        with pytest.raises(HTTPException) as exc:
            VirtualAssistantAdminService.create_application(
                db,
                full_name="Test VA",
                email="test@example.com",
                phone_number="9876543210",
                location="Bangalore",
                profile_photo=None,
                bio="A" * 100,
                roles=["Research"],
                skills="Excel",
                years_experience="3-5 years",
                languages="English",
                linkedin_url="",
                portfolio_url="",
                resume_url="https://drive.google.com/file/d/test",
                availability="available",
                hours_per_week="40",
                expected_compensation="20000",
                max_client_capacity=3,
                public_monthly_price_inr=20000,
            )
        assert exc.value.status_code == 400
        assert exc.value.detail == "LinkedIn Profile URL is required."

    def test_rejects_missing_public_price(self):
        from fastapi import HTTPException

        db = MagicMock()
        with pytest.raises(HTTPException) as exc:
            VirtualAssistantAdminService.create_application(
                db,
                full_name="Test VA",
                email="test@example.com",
                phone_number="9876543210",
                location="Bangalore",
                profile_photo=None,
                bio="A" * 100,
                roles=["Research"],
                skills="Excel",
                years_experience="3-5 years",
                languages="English",
                linkedin_url="https://www.linkedin.com/in/test-user",
                portfolio_url="",
                resume_url="https://drive.google.com/file/d/test",
                availability="available",
                hours_per_week="40",
                expected_compensation="20000",
                max_client_capacity=3,
                public_monthly_price_inr=None,
            )
        assert exc.value.status_code == 400
        assert "Customer Monthly Price" in exc.value.detail


class TestVaMediaResolution:
    def test_resolve_va_profile_photo_url_from_storage_key(self):
        key = "virtual-assistants/profile-photos/photo.jpg"
        with (
            patch(
                "app.service.virtual_assistant.va_media.public_object_url",
                return_value="https://cdn.example/public/photo.jpg",
            ) as public_url,
            patch(
                "app.service.virtual_assistant.va_media.resolve_media_url",
                return_value="https://cdn.example/signed/photo.jpg",
            ) as resolve,
        ):
            from app.service.virtual_assistant.va_media import resolve_va_profile_photo_url

            url = resolve_va_profile_photo_url(None, key)
            public_url.assert_called_once_with(key)
            resolve.assert_called_once_with("https://cdn.example/public/photo.jpg")
            assert url == "https://cdn.example/signed/photo.jpg"

    def test_resolve_va_profile_photo_url_filters_placeholder(self):
        from app.service.virtual_assistant.va_media import resolve_va_profile_photo_url

        assert resolve_va_profile_photo_url("https://example.com/photo.jpg", None) is None


class TestApplicantWorkspaceUnlock:
    def test_applicant_workspace_unlocked_when_any_role_approved(self):
        db = MagicMock()
        with patch(
            "app.service.admin.virtual_assistant_admin_service.VirtualAssistantAdminService.list_applicant_role_summaries",
            return_value=[
                {"status": "pending"},
                {"status": "approved"},
            ],
        ):
            assert VirtualAssistantAdminService.applicant_workspace_unlocked(db, "va@example.com")

    def test_applicant_workspace_locked_when_no_roles_approved(self):
        db = MagicMock()
        with patch(
            "app.service.admin.virtual_assistant_admin_service.VirtualAssistantAdminService.list_applicant_role_summaries",
            return_value=[
                {"status": "pending"},
                {"status": "rejected"},
            ],
        ):
            assert not VirtualAssistantAdminService.applicant_workspace_unlocked(db, "va@example.com")


class TestCreateAssignment:
    def test_create_assignment_requires_company_and_role(self):
        db = MagicMock()
        app_id = uuid.uuid4()
        with pytest.raises(ValueError, match="assignedCompany"):
            VirtualAssistantAdminService.create_assignment(
                db, app_id, assigned_company="", assigned_role="Support",
            )
        with pytest.raises(ValueError, match="assignedRole"):
            VirtualAssistantAdminService.create_assignment(
                db, app_id, assigned_company="Acme", assigned_role="",
            )

    def test_create_assignment_returns_none_when_application_missing(self):
        db = MagicMock()
        app_id = uuid.uuid4()
        db.query.return_value.filter.return_value.first.return_value = None
        result = VirtualAssistantAdminService.create_assignment(
            db, app_id, assigned_company="Acme", assigned_role="Support",
        )
        assert result is None

