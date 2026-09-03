"""Map Software ORM rows to API responses."""

from __future__ import annotations

from typing import Optional

from app.entity.cocreation.software_entity import Software
from app.entity.cocreation.software_purchase_entity import SoftwarePurchase
from app.integrations.s3.supabase_storage import resolve_media_url
from app.model.cocreation.cocreation_response import SoftwareResponse, TechnologyPricingPlanResponse
from app.model.user.public_user import to_public_user
from app.model.venture.venture_response import AgreementResponse
from app.utils.cocreation_enums import SoftwarePurchaseCompletionStatus


def build_software_response(
    software: Software,
    *,
    viewer_purchase: Optional[SoftwarePurchase] = None,
    is_owner: bool = False,
    hide_github_from_public: bool = False,
    purchase_count: int = 0,
) -> SoftwareResponse:
    agreement = None
    if software.agreement is not None:
        agreement = AgreementResponse(
            id=software.agreement.id,
            terms=bool(software.agreement.terms),
        )
    listed_by = (
        to_public_user(software.listed_by) if software.listed_by is not None else None
    )

    show_github = not hide_github_from_public
    if hide_github_from_public:
        show_github = is_owner or (
            viewer_purchase is not None
            and viewer_purchase.completion_status
            == SoftwarePurchaseCompletionStatus.CONFIRMED
        )

    seller_price = software.seller_price
    commission_amount = None
    commission_percent = None
    if seller_price is not None and seller_price >= 0:
        commission_amount = round(float(software.price) - float(seller_price), 2)
        if seller_price > 0:
            commission_percent = round(commission_amount / float(seller_price) * 100, 2)

    pricing_plans_list = None
    if software.pricing_plans:
        pricing_plans_list = [
            TechnologyPricingPlanResponse(
                id=plan.id,
                plan_duration=plan.plan_duration,
                price=plan.price,
                is_active=plan.is_active,
            )
            for plan in software.pricing_plans
        ]

    return SoftwareResponse(
        id=software.id,
        name=software.name,
        description=software.description,
        video_link=software.video_link,
        what_it_does=software.what_it_does,
        how_it_helps=software.how_it_helps,
        github_link=software.github_link if show_github else None,
        documentation_urls=software.documentation_urls if show_github else None,
        download_urls=software.download_urls if show_github else None,
        image_url=resolve_media_url(software.image_url),
        logo_url=resolve_media_url(software.image_url),
        logo=resolve_media_url(software.image_url),
        live_demo_link=software.live_demo_link,
        tech_stack=software.tech_stack,
        technology_type=software.technology_type,
        category=software.category,
        pricing_demand=software.pricing_demand,
        price=software.price,
        seller_price=seller_price,
        currency=(software.currency or "INR").upper(),
        pricing_plans=pricing_plans_list,
        platform_commission_percent=commission_percent,
        platform_commission_amount=commission_amount,
        final_listing_price=software.price,
        software_status=software.software_status,
        purchase_type=software.purchase_type,
        status=software.status,
        views=software.views,
        official=software.official,
        featured=software.featured,
        verified=bool(software.verified),
        verified_at=software.verified_at,
        created_at=software.created_at,
        updated_at=software.updated_at,
        agreement=agreement,
        listed_by=listed_by,
        buyer_has_purchased=viewer_purchase is not None,
        buyer_completion_status=(
            viewer_purchase.completion_status.value
            if viewer_purchase is not None
            else None
        ),
        purchase_count=purchase_count,
    )
