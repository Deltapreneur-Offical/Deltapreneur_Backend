from app.service.domain.domain_enquiry_pipeline import is_listing_pipeline_placeholder


def test_placeholder_from_virtual_flag():
    assert is_listing_pipeline_placeholder({"isVirtual": True, "fullName": "Buyer"}) is True


def test_placeholder_from_pipeline_copy():
    assert is_listing_pipeline_placeholder({
        "fullName": "No buyer enquiry yet",
        "message": "Listed premium domain (Pending buyer enquiry)",
    }) is True


def test_real_buyer_enquiry_is_not_placeholder():
    assert is_listing_pipeline_placeholder({
        "fullName": "Neminath Akkole",
        "message": "Managed domain acquisition request",
        "status": "PENDING",
    }) is False
