import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.service.domain.domain_registration_service import DomainRegistrationService
from app.utils.registration_enums import RegistrationOrderStatus
from app.entity.domain.domain_registration_order_entity import DomainRegistrationOrder
import uuid

@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    return session

@pytest.fixture
def mock_order():
    order = DomainRegistrationOrder(
        id=uuid.uuid4(),
        domain_name="testdomain",
        domain_extension=".com",
        buyer_id=uuid.uuid4(),
        status=RegistrationOrderStatus.CREATED,
        razorpay_order_id="order_123",
        transfer_auth_code="auth123"
    )
    return order

@pytest.fixture
def service(mock_session):
    srv = DomainRegistrationService(mock_session)
    # mock repositories
    srv._orders = AsyncMock()
    srv._followup = AsyncMock()
    return srv

@pytest.mark.asyncio
async def test_normal_registration_unaffected(service, mock_order):
    mock_order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
    service._orders.list_by_razorpay_order_id.return_value = [mock_order]
    
    with patch("app.integrations.razorpay.client.fetch_order") as mock_fetch:
        with patch("app.service.platform.track_record_service.TrackRecordService.record_from_registration_order", new_callable=AsyncMock) as mock_track:
            # Mock notes to not be domain_transfer
            mock_fetch.return_value = {"notes": {"type": "registration"}}
            
            # mock provision_order
            service.provision_order = AsyncMock(return_value={"registerDomainCalled": True})
            
            res = await service.complete_payment_from_webhook(
                razorpay_order_id="order_123",
                payment_id="pay_123"
            )
        
        # Verify get_by_id_for_update is NOT called for normal registration
        service._orders.get_by_id_for_update.assert_not_called()
        service.provision_order.assert_called_once()
        assert res["ordersFound"] == 1

@pytest.mark.asyncio
async def test_transfer_webhook_wins(service, mock_order):
    mock_order.status = RegistrationOrderStatus.CREATED
    service._orders.list_by_razorpay_order_id.return_value = [mock_order]
    service._orders.get_by_id_for_update.return_value = mock_order
    
    with patch("app.integrations.razorpay.client.fetch_order") as mock_fetch:
        mock_fetch.return_value = {"notes": {"type": "domain_transfer"}}
        
        service._provision_transfer = AsyncMock()
        mock_buyer = MagicMock()
        service._session.get.return_value = mock_buyer
        
        with patch("app.service.platform.track_record_service.TrackRecordService.record_from_registration_order", new_callable=AsyncMock) as mock_track:
            res = await service.complete_payment_from_webhook(
                razorpay_order_id="order_123",
                payment_id="pay_123"
            )
        
        service._orders.get_by_id_for_update.assert_called_once_with(mock_order.id)
        service._provision_transfer.assert_called_once_with(mock_order, buyer=mock_buyer)
        assert mock_order.status == RegistrationOrderStatus.PAYMENT_COMPLETED
        assert res["ordersFound"] == 1

@pytest.mark.asyncio
async def test_transfer_identity_map_race(service, mock_order):
    # Simulate Thread B reading the old state into the Identity Map
    mock_order.status = RegistrationOrderStatus.CREATED
    mock_order.transfer_status = None
    service._orders.list_by_razorpay_order_id.return_value = [mock_order]
    
    # Simulate Thread A having committed the transaction, modifying the DB row.
    # When Thread B unblocks and executes get_by_id_for_update(populate_existing=True), 
    # SQLAlchemy updates the existing python object with the fresh DB state.
    async def mock_get_for_update(order_id):
        # The populate_existing=True refreshes the object in memory.
        mock_order.status = RegistrationOrderStatus.REGISTRATION_PENDING
        mock_order.transfer_status = "PENDING"
        return mock_order

    service._orders.get_by_id_for_update.side_effect = mock_get_for_update
    
    with patch("app.integrations.razorpay.client.fetch_order") as mock_fetch:
        mock_fetch.return_value = {"notes": {"type": "domain_transfer"}}
        service._provision_transfer = AsyncMock()
        service._reconcile_registrar_order = AsyncMock()
        
        with patch("app.service.platform.track_record_service.TrackRecordService.record_from_registration_order", new_callable=AsyncMock) as mock_track:
            res = await service.complete_payment_from_webhook(
                razorpay_order_id="order_123",
                payment_id="pay_123"
            )
        
        service._orders.get_by_id_for_update.assert_called_once_with(mock_order.id)
        # Webhook should skip because the refreshed state is REGISTRATION_PENDING/PENDING
        service._provision_transfer.assert_not_called()
        assert res["ordersFound"] == 1
        assert res['results'][0]["action"] == "reconcile_only"

@pytest.mark.asyncio
async def test_registrar_side_recovery(service, mock_order):
    # Test _provision_transfer with existing OpenProvider ID
    mock_order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
    mock_buyer = MagicMock()
    service._orders.get_by_id_for_update.return_value = mock_order
    
    with patch("app.service.domain.domain_registration_service.active_registrar") as mock_reg_func:
        mock_reg = MagicMock()
        mock_reg.is_configured.return_value = True
        mock_reg.lookup_order_id_by_domain = AsyncMock(return_value="op_123")
        mock_reg_func.return_value = mock_reg
        
        with patch("app.service.domain.domain_registration_followup.stamp_registration_pending_since") as mock_stamp:
            with patch("app.integrations.openprovider.client.transfer_domain") as mock_op_transfer:
                res = await service._provision_transfer(mock_order, buyer=mock_buyer)
                
                mock_op_transfer.assert_not_called()
                assert mock_order.open_provider_domain_id == "op_123"
                assert mock_order.transfer_status == "PENDING"
                assert mock_order.status == RegistrationOrderStatus.REGISTRATION_PENDING


@pytest.mark.asyncio
async def test_provision_transfer_builds_customer_from_app_user(service, mock_order):
    from app.entity.user.app_user import AppUser
    mock_order.status = RegistrationOrderStatus.PAYMENT_COMPLETED
    mock_order.transfer_status = "PAYMENT_PENDING"
    mock_order.transfer_auth_code = "secret123"

    buyer = AppUser(
        email="test@example.com",
        firstname="Test",
        lastname="User",
        phone_number="9876543210"
    )

    with patch("app.service.domain.domain_registration_service.active_registrar") as mock_reg_func:
        mock_reg = MagicMock()
        mock_reg.is_configured.return_value = True
        mock_reg.lookup_order_id_by_domain = AsyncMock(return_value=None)
        mock_reg.create_customer = AsyncMock(return_value="OP-1234")
        mock_reg_func.return_value = mock_reg
        
        with patch("app.integrations.openprovider.client.transfer_domain", new_callable=AsyncMock) as mock_op_transfer:
            mock_op_transfer.return_value = {"id": "op_new_123", "status": "Success"}
            
            await service._provision_transfer(mock_order, buyer=buyer)
            
            mock_reg.create_customer.assert_called_once()
            called_customer = mock_reg.create_customer.call_args[0][0]
            assert called_customer["name"]["first_name"] == "Test"
            assert called_customer["name"]["last_name"] == "User"
            
            mock_op_transfer.assert_called_once()
            called_args = mock_op_transfer.call_args[1]
            assert called_args["name"] == mock_order.domain_name
            assert called_args["auth_code"] == "secret123"

