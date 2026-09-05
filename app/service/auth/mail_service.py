from pathlib import Path

from fastapi_mail import ConnectionConfig
from fastapi_mail import FastMail
from fastapi_mail import MessageSchema
from fastapi_mail import MessageType
from fastapi_mail.schemas import MultipartSubtypeEnum

from app.core.config import settings

from app.service.auth.email_templates import (
    becobrother_application_email_template,
    cobrother_assignment_email_template,
    cobrother_fee_request_email_template,
    HUBREGISTRAR_EMAIL_LOGO_URL,
    domain_registration_active_email_template,
    domain_registration_failed_email_template,
    domain_transfer_auth_available_email_template,
    domain_transfer_buyer_purchase_email_template,
    domain_transfer_seller_reminder_email_template,
    domain_transfer_seller_sold_email_template,
    domain_registration_raa_pending_email_template,
    domain_registration_receipt_email_template,
    domain_registration_submitted_email_template,
    domain_verification_email_template,
    feedback_email_template,
    meeting_cancelled_email_template,
    meeting_confirmed_email_template,
    meeting_request_email_template,
    otp_login_email_template,
    otp_registration_email_template,
    password_reset_email_template,
    premium_marketplace_admin_alert_email_template,
    premium_marketplace_buyer_confirmation_email_template,
    premium_marketplace_buyer_update_email_template,
    software_purchase_confirmed_email_template,
    software_purchase_receipt_email_template,
    software_sold_seller_notification_email_template,
    seller_payout_details_reminder_email_template,
    technology_purchase_confirmation_email_template,
    technology_purchase_failed_email_template,
    technology_purchase_pending_email_template,
    verification_email_template,
    virtual_assistant_application_email_template,
    virtual_assistant_application_confirmation_email_template,
    virtual_assistant_role_decision_email_template,
    virtual_assistant_workspace_unlocked_email_template,
    virtual_assistant_new_assignment_email_template,
    virtual_assistant_assignment_cancelled_email_template,
)


class MailService:

    @staticmethod
    def _html_message(
        *,
        subject: str,
        recipients: list[str],
        body: str,
        reply_to: list[str] | None = None,
        attachments: list | None = None,
        multipart_subtype: MultipartSubtypeEnum | None = None,
    ) -> MessageSchema:
        """Build HTML outbound mail with default Reply-To (support@deltapreneur.com)."""
        merged_reply: list[str] = list(reply_to or [])
        default_reply = settings.resolved_mail_reply_to()
        if default_reply and default_reply not in merged_reply:
            merged_reply.insert(0, default_reply)
        kwargs: dict = {
            "subject": subject,
            "recipients": recipients,
            "body": body,
            "subtype": MessageType.html,
        }
        if merged_reply:
            kwargs["reply_to"] = merged_reply
        if attachments:
            kwargs["attachments"] = attachments
        if multipart_subtype is not None:
            kwargs["multipart_subtype"] = multipart_subtype
        return MessageSchema(**kwargs)

    @staticmethod
    def _conf() -> ConnectionConfig:
        return ConnectionConfig(
            MAIL_USERNAME=settings.MAIL_USERNAME,
            MAIL_PASSWORD=settings.MAIL_PASSWORD,
            MAIL_FROM=settings.MAIL_FROM,
            MAIL_PORT=settings.MAIL_PORT,
            MAIL_SERVER=settings.MAIL_SERVER,
            MAIL_STARTTLS=settings.MAIL_STARTTLS,
            MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
            MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
            USE_CREDENTIALS=True,
            VALIDATE_CERTS=settings.MAIL_VALIDATE_CERTS,
        )

    @staticmethod
    def _conf_for_domains() -> ConnectionConfig:
        """SMTP config for domain lifecycle mail (domains@ mailbox when configured)."""
        return ConnectionConfig(
            MAIL_USERNAME=settings.resolved_mail_domains_username(),
            MAIL_PASSWORD=settings.resolved_mail_domains_password(),
            MAIL_FROM=settings.resolved_mail_domains_from(),
            MAIL_PORT=settings.MAIL_PORT,
            MAIL_SERVER=settings.MAIL_SERVER,
            MAIL_STARTTLS=settings.MAIL_STARTTLS,
            MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
            MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
            USE_CREDENTIALS=True,
            VALIDATE_CERTS=True,
        )

    @staticmethod
    async def send_verification_email(email: str, verification_token: str) -> None:
        verification_url = (
            f"{settings.BACKEND_BASE_URL}"
            f"/api/auth/verify-email"
            f"?token={verification_token}"
        )
        html = verification_email_template(verification_url)
        message = MailService._html_message(
            subject="Verify Your Email",
            recipients=[email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_otp_login_email(email: str, code: str) -> None:
        html = otp_login_email_template(code=code)
        message = MailService._html_message(
            subject="Your Deltapreneur sign-in code",
            recipients=[email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_registration_otp_email(email: str, code: str) -> None:
        html = otp_registration_email_template(code=code)
        message = MailService._html_message(
            subject="Verify your email — Deltapreneur",
            recipients=[email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_password_reset_email(email: str, raw_token: str) -> None:
        reset_url = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
        html = password_reset_email_template(reset_url)
        message = MailService._html_message(
            subject="Reset Your Password",
            recipients=[email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_domain_verification_email(
        *,
        to_email: str,
        fqdn: str,
        listing_id: str,
        verification_token: str,
    ) -> None:
        verify_url = (
            f"{settings.BACKEND_BASE_URL.rstrip('/')}"
            f"/api/v1/domain/listings/{listing_id}/verification/confirm"
            f"?token={verification_token}"
        )
        html = domain_verification_email_template(
            fqdn=fqdn,
            verification_url=verify_url,
        )
        message = MailService._html_message(
            subject=f"Verify ownership of {fqdn}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_software_purchase_receipt_email(
        *,
        to_email: str,
        software_name: str,
        dashboard_url: str,
    ) -> None:
        html = software_purchase_receipt_email_template(
            software_name=software_name,
            dashboard_url=dashboard_url,
        )
        message = MailService._html_message(
            subject=f"Deltapreneur purchase received — {software_name}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_software_purchase_confirmed_email(
        *,
        to_email: str,
        software_name: str,
        github_link: str,
        dashboard_url: str,
    ) -> None:
        html = software_purchase_confirmed_email_template(
            software_name=software_name,
            github_link=github_link,
            dashboard_url=dashboard_url,
        )
        message = MailService._html_message(
            subject=f"GitHub access — {software_name}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_technology_purchase_confirmation_email(
        *,
        to_email: str,
        customer_name: str,
        service_name: str,
        plan_name: str,
        billing_cycle: str,
        cobrother_order_id: str,
        razorpay_payment_id: str | None,
        amount_inr: float,
        purchase_date: str,
        service_status: str,
        provider_info: str | None = None,
        purchases_url: str,
    ) -> None:
        html = technology_purchase_confirmation_email_template(
            customer_name=customer_name,
            service_name=service_name,
            plan_name=plan_name,
            billing_cycle=billing_cycle,
            cobrother_order_id=cobrother_order_id,
            razorpay_payment_id=razorpay_payment_id,
            amount_inr=amount_inr,
            purchase_date=purchase_date,
            service_status=service_status,
            provider_info=provider_info,
            purchases_url=purchases_url,
        )
        message = MailService._html_message(
            subject=f"Your Deltapreneur purchase is confirmed – {service_name}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_technology_purchase_pending_email(
        *,
        to_email: str,
        customer_name: str,
        service_name: str,
        plan_name: str,
        billing_cycle: str,
        cobrother_order_id: str,
        razorpay_payment_id: str | None,
        amount_inr: float,
        purchase_date: str,
        reason: str,
        purchases_url: str,
    ) -> None:
        html = technology_purchase_pending_email_template(
            customer_name=customer_name,
            service_name=service_name,
            plan_name=plan_name,
            billing_cycle=billing_cycle,
            cobrother_order_id=cobrother_order_id,
            razorpay_payment_id=razorpay_payment_id,
            amount_inr=amount_inr,
            purchase_date=purchase_date,
            reason=reason,
            purchases_url=purchases_url,
        )
        message = MailService._html_message(
            subject=f"Payment received – {service_name} activation pending",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_technology_purchase_failed_email(
        *,
        to_email: str,
        customer_name: str,
        service_name: str,
        plan_name: str,
        billing_cycle: str,
        cobrother_order_id: str,
        razorpay_payment_id: str | None,
        amount_inr: float,
        purchase_date: str,
        reason: str,
        purchases_url: str,
    ) -> None:
        html = technology_purchase_failed_email_template(
            customer_name=customer_name,
            service_name=service_name,
            plan_name=plan_name,
            billing_cycle=billing_cycle,
            cobrother_order_id=cobrother_order_id,
            razorpay_payment_id=razorpay_payment_id,
            amount_inr=amount_inr,
            purchase_date=purchase_date,
            reason=reason,
            purchases_url=purchases_url,
        )
        message = MailService._html_message(
            subject=f"Action needed – {service_name} activation failed",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_software_sold_seller_notification_email(
        *,
        to_email: str,
        seller_name: str,
        software_name: str,
        buyer_name: str,
        price: float,
        dashboard_url: str,
    ) -> None:
        html = software_sold_seller_notification_email_template(
            seller_name=seller_name,
            software_name=software_name,
            buyer_name=buyer_name,
            price=price,
            dashboard_url=dashboard_url,
        )
        message = MailService._html_message(
            subject=f"Technology sold! — {software_name}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_feedback_email(
        *,
        from_email: str | None,
        subject: str | None,
        feedback_type: str | None,
        page_url: str | None,
        message_text: str,
    ) -> None:
        html = feedback_email_template(
            from_email=from_email,
            subject=subject,
            feedback_type=feedback_type,
            page_url=page_url,
            message=message_text,
        )
        message = MailService._html_message(
            subject=f"[Feedback] {(subject or 'Website feedback').strip() or 'Website feedback'}",
            recipients=[settings.resolved_mail_support_inbox()],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_becobrother_application_email(
        *,
        to_email: str,
        full_name: str,
        email: str,
        phone_number: str | None,
        pin_code: str | None,
        skill: str | None,
        equipment: bool,
        submitted_at: str,
    ) -> None:
        html = becobrother_application_email_template(
            full_name=full_name,
            email=email,
            phone_number=phone_number,
            pin_code=pin_code,
            skill=skill,
            equipment=equipment,
            submitted_at=submitted_at,
        )
        message = MailService._html_message(
            subject=f"New Deltapreneur Application — {full_name}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_cobrother_fee_request_email(
        *,
        to_email: str,
        lister_name: str,
        entity_title: str,
        payment_url: str,
    ) -> None:
        html = cobrother_fee_request_email_template(
            lister_name=lister_name,
            entity_title=entity_title,
            payment_url=payment_url,
        )
        message = MailService._html_message(
            subject=f"Action Required: Deltapreneur Service Fee — {entity_title}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_cobrother_assignment_email(
        *,
        to_email: str,
        cobrother_name: str,
        request_type: str,
        entity_title: str,
        lister_name: str | None,
        lister_email: str | None,
        lister_phone: str | None,
        applicant_name: str | None,
        applicant_email: str | None,
        applicant_phone: str | None,
        dashboard_url: str,
    ) -> None:
        html = cobrother_assignment_email_template(
            cobrother_name=cobrother_name,
            request_type=request_type,
            entity_title=entity_title,
            lister_name=lister_name,
            lister_email=lister_email,
            lister_phone=lister_phone,
            applicant_name=applicant_name,
            applicant_email=applicant_email,
            applicant_phone=applicant_phone,
            dashboard_url=dashboard_url,
        )
        message = MailService._html_message(
            subject=f"New Request Assigned — {entity_title}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_meeting_request_email(
        *,
        to_email: str,
        lister_name: str,
        requester_name: str,
        auction_title: str,
        scheduled_date: str,
        scheduled_time: str,
        duration_minutes: int,
        topic: str | None,
        meeting_message: str | None,
        meetings_url: str,
    ) -> None:
        html = meeting_request_email_template(
            lister_name=lister_name,
            requester_name=requester_name,
            auction_title=auction_title,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            duration_minutes=duration_minutes,
            topic=topic,
            meeting_message=meeting_message,
            meetings_url=meetings_url,
        )
        message = MailService._html_message(
            subject=f"New Meeting Request — {requester_name}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_meeting_confirmed_email(
        *,
        to_email: str,
        recipient_name: str,
        other_party_name: str,
        auction_title: str,
        scheduled_date: str,
        scheduled_time: str,
        duration_minutes: int,
        meeting_link: str,
        calendar_link: str | None = None,
    ) -> None:
        html = meeting_confirmed_email_template(
            recipient_name=recipient_name,
            other_party_name=other_party_name,
            auction_title=auction_title,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            duration_minutes=duration_minutes,
            meeting_link=meeting_link,
            calendar_link=calendar_link,
        )
        message = MailService._html_message(
            subject=f"Meeting Confirmed — {scheduled_date}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_meeting_cancelled_email(
        *,
        to_email: str,
        recipient_name: str,
        canceller_name: str,
        auction_title: str,
        scheduled_date: str,
        scheduled_time: str,
        reason: str | None,
    ) -> None:
        html = meeting_cancelled_email_template(
            recipient_name=recipient_name,
            canceller_name=canceller_name,
            auction_title=auction_title,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            reason=reason,
        )
        message = MailService._html_message(
            subject=f"Meeting Cancelled — {scheduled_date}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_domain_registration_receipt_email(
        *,
        to_email: str,
        fqdn: str,
        amount_inr: float,
        razorpay_payment_id: str | None,
        order_detail_url: str,
    ) -> None:
        html = domain_registration_receipt_email_template(
            fqdn=fqdn,
            amount_inr=amount_inr,
            razorpay_payment_id=razorpay_payment_id,
            order_detail_url=order_detail_url,
        )
        message = MailService._html_message(
            subject=f"Payment received — {fqdn}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf_for_domains())
        await fm.send_message(message)

    @staticmethod
    async def send_domain_registration_submitted_email(
        *,
        to_email: str,
        fqdn: str,
        order_detail_url: str,
        is_transfer: bool = False,
    ) -> None:
        html = domain_registration_submitted_email_template(
            fqdn=fqdn,
            order_detail_url=order_detail_url,
            is_transfer=is_transfer,
        )
        subject_prefix = "Domain transfer submitted" if is_transfer else "Domain registration submitted"
        message = MailService._html_message(
            subject=f"{subject_prefix} — {fqdn}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf_for_domains())
        await fm.send_message(message)

    @staticmethod
    async def send_domain_registration_active_email(
        *,
        to_email: str,
        fqdn: str,
        order_detail_url: str,
        expires_at: str | None,
        nameservers: list[str] | None = None,
        manage_dns_url: str | None = None,
        customer_panel_url: str | None = None,
        registered_at: str | None = None,
    ) -> None:
        dns_url = (manage_dns_url or "").strip() or None
        if not dns_url and order_detail_url:
            dns_url = f"{order_detail_url.rstrip('/')}#dns"
        logo_path = (
            Path(__file__).resolve().parents[2]
            / "assets"
            / "email"
            / "deltapreneur-logo.png"
        )
        use_cid = logo_path.is_file()
        html = domain_registration_active_email_template(
            fqdn=fqdn,
            order_detail_url=order_detail_url,
            expires_at=expires_at,
            nameservers=nameservers,
            manage_dns_url=dns_url,
            customer_panel_url=customer_panel_url,
            logo_url="cid:deltapreneur-logo" if use_cid else HUBREGISTRAR_EMAIL_LOGO_URL,
            registered_at=registered_at,
        )
        attachments = None
        multipart_subtype = None
        if use_cid:
            attachments = [
                {
                    "file": str(logo_path),
                    "mime_type": "image",
                    "mime_subtype": "png",
                    "headers": {
                        "Content-ID": "<deltapreneur-logo>",
                        "Content-Disposition": 'inline; filename="deltapreneur-logo.png"',
                    },
                }
            ]
            multipart_subtype = MultipartSubtypeEnum.related
        message = MailService._html_message(
            subject=f"Domain active — {fqdn}",
            recipients=[to_email],
            body=html,
            attachments=attachments,
            multipart_subtype=multipart_subtype,
        )
        fm = FastMail(MailService._conf_for_domains())
        await fm.send_message(message)

    @staticmethod
    async def send_domain_registration_raa_pending_email(
        *,
        to_email: str,
        fqdn: str,
        registrant_email: str,
        order_detail_url: str,
    ) -> None:
        html = domain_registration_raa_pending_email_template(
            fqdn=fqdn,
            registrant_email=registrant_email,
            order_detail_url=order_detail_url,
        )
        message = MailService._html_message(
            subject=f"Verify registrant email — {fqdn}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf_for_domains())
        await fm.send_message(message)

    @staticmethod
    async def send_domain_registration_failed_email(
        *,
        to_email: str,
        fqdn: str,
        message: str,
        order_detail_url: str,
        is_transfer: bool = False,
    ) -> None:
        html = domain_registration_failed_email_template(
            fqdn=fqdn,
            message=message,
            order_detail_url=order_detail_url,
            is_transfer=is_transfer,
        )
        subject = (
            f"Domain transfer issue — {fqdn}"
            if is_transfer
            else f"Domain registration issue — {fqdn}"
        )
        msg = MailService._html_message(
            subject=subject,
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf_for_domains())
        await fm.send_message(msg)

    @staticmethod
    async def send_domain_transfer_seller_sold_email(
        to_email: str, user_name: str, fqdn: str,
    ) -> None:
        html = domain_transfer_seller_sold_email_template(user_name=user_name, fqdn=fqdn)
        message = MailService._html_message(
            subject=f"Domain sold — submit auth code for {fqdn}",
            recipients=[to_email],
            body=html,
        )
        await FastMail(MailService._conf()).send_message(message)

    @staticmethod
    async def send_domain_transfer_buyer_purchase_email(
        to_email: str, user_name: str, fqdn: str, transfer_url: str,
    ) -> None:
        html = domain_transfer_buyer_purchase_email_template(
            user_name=user_name, fqdn=fqdn, transfer_url=transfer_url,
        )
        message = MailService._html_message(
            subject=f"Purchase confirmed — {fqdn}",
            recipients=[to_email],
            body=html,
        )
        await FastMail(MailService._conf()).send_message(message)

    @staticmethod
    async def send_domain_transfer_auth_available_email(
        to_email: str, user_name: str, fqdn: str, transfer_url: str,
    ) -> None:
        html = domain_transfer_auth_available_email_template(
            user_name=user_name, fqdn=fqdn, transfer_url=transfer_url,
        )
        message = MailService._html_message(
            subject=f"Auth code ready — {fqdn}",
            recipients=[to_email],
            body=html,
        )
        await FastMail(MailService._conf()).send_message(message)

    @staticmethod
    async def send_domain_transfer_seller_reminder_email(
        to_email: str, user_name: str, fqdn: str, *, hours_remaining: int,
    ) -> None:
        html = domain_transfer_seller_reminder_email_template(
            user_name=user_name, fqdn=fqdn, hours_remaining=hours_remaining,
        )
        message = MailService._html_message(
            subject=f"Reminder: auth code due soon — {fqdn}",
            recipients=[to_email],
            body=html,
        )
        await FastMail(MailService._conf()).send_message(message)

    @staticmethod
    async def send_seller_payout_details_reminder_email(
        *, to_email: str, payout_settings_url: str,
    ) -> None:
        html = seller_payout_details_reminder_email_template(
            payout_settings_url=payout_settings_url,
        )
        message = MailService._html_message(
            subject="Action Required: Add Your Deltapreneur Payout Details",
            recipients=[to_email],
            body=html,
        )
        await FastMail(MailService._conf()).send_message(message)

    @staticmethod
    async def send_virtual_assistant_application_email(
        *,
        to_email: str,
        full_name: str,
        email: str,
        phone_number: str | None,
        location: str | None,
        profile_photo_url: str | None,
        is_adult: bool,
        bio: str | None,
        roles: str | None,
        skills: str | None,
        years_of_experience: str | None,
        languages: str | None,
        linkedin_url: str | None,
        portfolio_url: str | None,
        resume_url: str | None,
        availability: str | None,
        hours_per_week: str | None,
        expected_compensation: str | None,
        info_accurate: bool,
        agree_terms: bool,
        reference_number: str,
        submitted_at: str,
    ) -> None:
        html = virtual_assistant_application_email_template(
            full_name=full_name,
            email=email,
            phone_number=phone_number,
            location=location,
            profile_photo_url=profile_photo_url,
            is_adult=is_adult,
            bio=bio,
            roles=roles,
            skills=skills,
            years_of_experience=years_of_experience,
            languages=languages,
            linkedin_url=linkedin_url,
            portfolio_url=portfolio_url,
            resume_url=resume_url,
            availability=availability,
            hours_per_week=hours_per_week,
            expected_compensation=expected_compensation,
            info_accurate=info_accurate,
            agree_terms=agree_terms,
            reference_number=reference_number,
            submitted_at=submitted_at,
        )
        message = MailService._html_message(
            subject=f"New Virtual Assistant Application — {full_name} ({reference_number})",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_virtual_assistant_application_confirmation_email(
        *,
        to_email: str,
        full_name: str,
        reference_number: str,
        submitted_at: str,
    ) -> None:
        html = virtual_assistant_application_confirmation_email_template(
            full_name=full_name,
            reference_number=reference_number,
            submitted_at=submitted_at,
        )
        message = MailService._html_message(
            subject=f"Virtual Assistant Application Received — {reference_number}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_virtual_assistant_role_decision_email(
        *,
        to_email: str,
        full_name: str,
        reference_number: str,
        roles: list[dict],
        overall_status: str | None,
        reviewer_name: str | None,
        workspace_unlocked: bool,
    ) -> None:
        html = virtual_assistant_role_decision_email_template(
            full_name=full_name,
            reference_number=reference_number,
            roles=roles,
            overall_status=overall_status,
            reviewer_name=reviewer_name,
            workspace_unlocked=workspace_unlocked,
        )
        message = MailService._html_message(
            subject=f"Virtual Assistant Application Update — {reference_number}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_virtual_assistant_workspace_unlocked_email(
        *,
        to_email: str,
        full_name: str,
        reference_number: str,
        login_url: str,
    ) -> None:
        html = virtual_assistant_workspace_unlocked_email_template(
            full_name=full_name,
            reference_number=reference_number,
            login_url=login_url,
        )
        message = MailService._html_message(
            subject="Your Virtual Assistant Workspace is Ready",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_virtual_assistant_new_assignment_email(
        *,
        to_email: str,
        full_name: str,
        reference_number: str,
        assigned_company: str | None,
        assigned_role: str | None,
        start_date: str | None,
        end_date: str | None,
        notes: str | None,
    ) -> None:
        html = virtual_assistant_new_assignment_email_template(
            full_name=full_name,
            reference_number=reference_number,
            assigned_company=assigned_company,
            assigned_role=assigned_role,
            start_date=start_date,
            end_date=end_date,
            notes=notes,
        )
        message = MailService._html_message(
            subject="New Virtual Assistant Assignment",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_virtual_assistant_assignment_cancelled_email(
        *,
        to_email: str,
        full_name: str,
        reference_number: str,
        assigned_company: str | None,
        assigned_role: str | None,
        reason: str | None,
    ) -> None:
        html = virtual_assistant_assignment_cancelled_email_template(
            full_name=full_name,
            reference_number=reference_number,
            assigned_company=assigned_company,
            assigned_role=assigned_role,
            reason=reason,
        )
        message = MailService._html_message(
            subject="Virtual Assistant Assignment Cancelled",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_premium_marketplace_buyer_confirmation_email(
        *,
        to_email: str,
        buyer_name: str,
        domain_fqdn: str,
        asking_price: float,
        enquiry_id: str,
    ) -> None:
        html = premium_marketplace_buyer_confirmation_email_template(
            buyer_name=buyer_name,
            domain_fqdn=domain_fqdn,
            asking_price=asking_price,
            enquiry_id=enquiry_id,
        )
        message = MailService._html_message(
            subject=f"Priority Escalation: Managed Acquisition for {domain_fqdn}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)
        logger = __import__("logging").getLogger(__name__)
        logger.info(
            "premium_marketplace.buyer_email.sent to=%s domain=%s enquiry=%s",
            to_email,
            domain_fqdn,
            enquiry_id,
        )

    @staticmethod
    async def send_premium_marketplace_buyer_update_email(
        *,
        to_email: str,
        buyer_name: str,
        domain_fqdn: str,
        status_label: str,
        admin_message: str | None,
        enquiry_id: str,
    ) -> None:
        html = premium_marketplace_buyer_update_email_template(
            buyer_name=buyer_name,
            domain_fqdn=domain_fqdn,
            status_label=status_label,
            admin_message=admin_message,
            enquiry_id=enquiry_id,
        )
        message = MailService._html_message(
            subject=f"Update on your premium acquisition — {domain_fqdn}",
            recipients=[to_email],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(message)

    @staticmethod
    async def send_premium_marketplace_admin_alert_email(
        *,
        domain_fqdn: str,
        asking_price: float,
        buyer_name: str,
        buyer_email: str,
        buyer_phone: str,
        message: str,
        enquiry_id: str,
    ) -> None:
        html = premium_marketplace_admin_alert_email_template(
            domain_fqdn=domain_fqdn,
            asking_price=asking_price,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            message=message,
            enquiry_id=enquiry_id,
        )
        outbound = MailService._html_message(
            subject=f"[Premium Acquisition] {domain_fqdn}",
            recipients=[settings.resolved_mail_support_inbox()],
            body=html,
        )
        fm = FastMail(MailService._conf())
        await fm.send_message(outbound)
