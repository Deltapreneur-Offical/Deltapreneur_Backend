def otp_login_email_template(*, code: str) -> str:
    return f"""
    <html>
        <body>
            <h2>Your Deltapreneur sign-in code</h2>
            <p>Use this one-time code to sign in. It expires in 10 minutes.</p>
            <p style="font-size: 1.75rem; font-weight: 700; letter-spacing: 0.25rem;
               font-family: ui-monospace, monospace;">{_esc(code)}</p>
            <p>If you did not request this code, you can ignore this email.</p>
        </body>
    </html>
    """


def otp_registration_email_template(*, code: str) -> str:
    return f"""
    <html>
        <body>
            <h2>Verify your email to join Deltapreneur</h2>
            <p>Enter this one-time code to complete your registration. It expires in 10 minutes.</p>
            <p style="font-size: 1.75rem; font-weight: 700; letter-spacing: 0.25rem;
               font-family: ui-monospace, monospace;">{_esc(code)}</p>
            <p>If you did not request this code, you can ignore this email.</p>
        </body>
    </html>
    """


def feedback_email_template(
    *,
    from_email: str | None,
    subject: str | None,
    feedback_type: str | None,
    page_url: str | None,
    message: str,
) -> str:
    safe_subject = _esc((subject or "Website feedback").strip() or "Website feedback")
    safe_type = _esc((feedback_type or "unspecified").strip() or "unspecified")
    safe_page = _esc((page_url or "unknown").strip() or "unknown")
    safe_from = _esc((from_email or "anonymous").strip() or "anonymous")

    return f"""
    <html>
        <body>
            <h2>New Deltapreneur feedback</h2>
            <p><strong>Subject:</strong> {safe_subject}</p>
            <p><strong>From:</strong> {safe_from}</p>
            <p><strong>Type:</strong> {safe_type}</p>
            <p><strong>Page URL:</strong> {safe_page}</p>
            <hr />
            <p><strong>Message:</strong></p>
            <pre style="white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;">{_esc(message)}</pre>
        </body>
    </html>
    """


def verification_email_template(
    verification_url: str
):

    return f"""
    <html>
        <body>

            <h2>Verify Your Email</h2>

            <p>
                Thank you for registering with Deltapreneur.
            </p>

            <p>
                Click the button below to verify your email:
            </p>

            <a
                href="{verification_url}"
                style="
                    display:inline-block;
                    padding:12px 20px;
                    background:#2563eb;
                    color:white;
                    text-decoration:none;
                    border-radius:6px;
                "
            >
                Verify Email
            </a>

            <p>
                This link will expire in 24 hours.
            </p>

        </body>
    </html>
    """


def domain_verification_email_template(
    *,
    fqdn: str,
    verification_url: str,
) -> str:
    return f"""
    <html>
        <body>
            <h2>Verify domain ownership</h2>
            <p>
                You started ownership verification for <strong>{fqdn}</strong>
                on Deltapreneur.
            </p>
            <p>
                Click the button below to confirm you control this domain:
            </p>
            <a
                href="{verification_url}"
                style="
                    display:inline-block;
                    padding:12px 20px;
                    background:#2563eb;
                    color:white;
                    text-decoration:none;
                    border-radius:6px;
                "
            >
                Verify domain
            </a>
            <p>
                If the button does not work, open this link in your browser:
            </p>
            <p><a href="{verification_url}">{verification_url}</a></p>
            <p>
                You can also confirm in the app using verification check with your token.
            </p>
        </body>
    </html>
    """


def software_purchase_receipt_email_template(
    *,
    software_name: str,
    dashboard_url: str,
) -> str:
    return f"""
    <html>
        <body>
            <h2>Payment received — {software_name}</h2>
            <p>Thank you for your purchase on Deltapreneur.</p>
            <p>
                Open your dashboard and confirm that everything works as expected.
                After confirmation, your GitHub repository link will be available there.
            </p>
            <a
                href="{dashboard_url}"
                style="
                    display:inline-block;
                    padding:12px 20px;
                    background:#7c3aed;
                    color:white;
                    text-decoration:none;
                    border-radius:6px;
                "
            >
                Open Technology Dashboard
            </a>
            <p>If the button does not work: <a href="{dashboard_url}">{dashboard_url}</a></p>
        </body>
    </html>
    """


def software_purchase_confirmed_email_template(
    *,
    software_name: str,
    github_link: str,
    dashboard_url: str,
) -> str:
    return f"""
    <html>
        <body>
            <h2>Purchase confirmed — {software_name}</h2>
            <p>Thanks for confirming your purchase.</p>
            <p><strong>GitHub repository:</strong></p>
            <p><a href="{github_link}">{github_link}</a></p>
            <p>You can also access this link anytime from your dashboard:</p>
            <p><a href="{dashboard_url}">{dashboard_url}</a></p>
        </body>
    </html>
    """


def software_sold_seller_notification_email_template(
    *,
    software_name: str,
    seller_name: str,
    buyer_name: str,
    price: float,
    dashboard_url: str,
) -> str:
    return f"""
    <html>
        <body>
            <h2>Your technology listing has been sold! — {_esc(software_name)}</h2>
            <p>Hi {_esc(seller_name)},</p>
            <p>Great news! Your listing <strong>{_esc(software_name)}</strong> has been purchased by <strong>{_esc(buyer_name)}</strong> for <strong>₹{price:,.2f}</strong>.</p>
            <p>Please log in to your dashboard to view the transaction details and manage the transfer.</p>
            <a
                href="{dashboard_url}"
                style="
                    display:inline-block;
                    padding:12px 20px;
                    background:#7c3aed;
                    color:white;
                    text-decoration:none;
                    border-radius:6px;
                "
            >
                Open Dashboard
            </a>
            <p>If the button does not work: <a href="{dashboard_url}">{dashboard_url}</a></p>
        </body>
    </html>
    """


def password_reset_email_template(reset_url: str) -> str:

    return f"""
    <html>
        <body>

            <h2>Reset Your Password</h2>

            <p>
                We received a request to reset your Deltapreneur password.
            </p>

            <p>
                Click the button below to choose a new password:
            </p>

            <a
                href="{reset_url}"
                style="
                    display:inline-block;
                    padding:12px 20px;
                    background:#2563eb;
                    color:white;
                    text-decoration:none;
                    border-radius:6px;
                "
            >
                Reset Password
            </a>

            <p>
                This link will expire in 30 minutes.
            </p>

            <p>
                If you did not request this, you can safely ignore this email.
            </p>

        </body>
    </html>
    """


def _esc(value: str | None) -> str:
    if not value:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_skill_label(skill: str | None) -> str:
    if not skill:
        return "Not specified"
    return skill.replace("_", " ").title()


def becobrother_application_email_template(
    *,
    full_name: str,
    email: str,
    phone_number: str | None,
    pin_code: str | None,
    skill: str | None,
    equipment: bool,
    submitted_at: str,
) -> str:
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">New Deltapreneur Elite Application</h2>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Full Name:</strong> {_esc(full_name)}</p>
                    <p><strong>Email:</strong> {_esc(email)}</p>
                    <p><strong>WhatsApp:</strong> +91 {_esc(phone_number or "—")}</p>
                    <p><strong>City / Pincode:</strong> {_esc(pin_code or "—")}</p>
                    <p><strong>Top Skill:</strong> {_esc(_format_skill_label(skill))}</p>
                    <p><strong>Has Equipment:</strong> {"Yes" if equipment else "No"}</p>
                </div>
                <p style="color:#666; font-size:12px;">Submitted at: {_esc(submitted_at)}</p>
            </div>
        </body>
    </html>
    """


def cobrother_fee_request_email_template(
    *,
    lister_name: str,
    entity_title: str,
    payment_url: str,
) -> str:
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">Deltapreneur Service Request</h2>
                <p>Hi {_esc(lister_name)},</p>
                <p>
                    A Deltapreneur has been assigned to assist with your listing:
                    <strong>{_esc(entity_title)}</strong>
                </p>
                <p>To proceed, a one-time service fee of <strong>₹1,000</strong> is required.</p>
                <div style="text-align:center; margin: 30px 0;">
                    <a href="{_esc(payment_url)}"
                       style="background:#c8a96e; color:#1a1a2e; padding:14px 28px;
                              text-decoration:none; border-radius:6px; font-weight:bold;
                              display:inline-block;">
                        Pay ₹1,000 Now
                    </a>
                </div>
                <p style="color:#666;">You can also cancel this request from your fee requests page.</p>
                <p>If the button does not work: <a href="{_esc(payment_url)}">{_esc(payment_url)}</a></p>
            </div>
        </body>
    </html>
    """


def cobrother_assignment_email_template(
    *,
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
) -> str:
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">New Deltapreneur Request</h2>
                <p>Hi {_esc(cobrother_name)},</p>
                <p>You have been assigned a new request. Details below:</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Type:</strong> {_esc(request_type)}</p>
                    <p><strong>Entity:</strong> {_esc(entity_title)}</p>
                    <p><strong>Lister Name:</strong> {_esc(lister_name or "—")}</p>
                    <p><strong>Lister Email:</strong> {_esc(lister_email or "—")}</p>
                    <p><strong>Lister Phone:</strong> {_esc(lister_phone or "—")}</p>
                    <p><strong>Applicant/Buyer:</strong> {_esc(applicant_name or "—")}</p>
                    <p><strong>Applicant Email:</strong> {_esc(applicant_email or "—")}</p>
                    <p><strong>Applicant Phone:</strong> {_esc(applicant_phone or "—")}</p>
                </div>
                <p>Please log in to your Deltapreneur dashboard to accept or reject this request.</p>
                <p><a href="{_esc(dashboard_url)}">{_esc(dashboard_url)}</a></p>
            </div>
        </body>
    </html>
    """


def _format_meeting_datetime(scheduled_at) -> tuple[str, str]:
    if scheduled_at is None:
        return "—", "—"
    date_str = scheduled_at.strftime("%Y-%m-%d")
    time_str = scheduled_at.strftime("%H:%M UTC")
    return date_str, time_str


def meeting_request_email_template(
    *,
    lister_name: str,
    requester_name: str,
    auction_title: str,
    scheduled_date: str,
    scheduled_time: str,
    duration_minutes: int,
    topic: str | None,
    meeting_message: str | None,
    meetings_url: str,
) -> str:
    topic_block = (
        f"<p><strong>Topic:</strong> {_esc(topic)}</p>"
        if topic and topic.strip()
        else ""
    )
    message_block = (
        f"<p><strong>Message:</strong> {_esc(meeting_message)}</p>"
        if meeting_message and meeting_message.strip()
        else ""
    )
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">New Meeting Request</h2>
                <p>Hi {_esc(lister_name)},</p>
                <p>
                    <strong>{_esc(requester_name)}</strong> wants to meet about your profile auction:
                    <em>{_esc(auction_title)}</em>
                </p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Requested Time:</strong> {_esc(scheduled_date)} at {_esc(scheduled_time)}</p>
                    <p><strong>Duration:</strong> {duration_minutes} minutes</p>
                    {topic_block}
                    {message_block}
                </div>
                <div style="text-align:center; margin: 30px 0;">
                    <a href="{_esc(meetings_url)}"
                       style="background:#c8a96e; color:#1a1a2e; padding:14px 28px;
                              text-decoration:none; border-radius:6px; font-weight:bold;
                              display:inline-block;">
                        Confirm or Decline
                    </a>
                </div>
                <p style="color:#666; font-size:0.9em;">
                    Log in to your dashboard to confirm or decline this request.
                </p>
            </div>
        </body>
    </html>
    """


def meeting_confirmed_email_template(
    *,
    recipient_name: str,
    other_party_name: str,
    auction_title: str,
    scheduled_date: str,
    scheduled_time: str,
    duration_minutes: int,
    meeting_link: str,
    calendar_link: str | None = None,
) -> str:
    calendar_block = ""
    if calendar_link and calendar_link.strip():
        calendar_block = (
            f'<p style="margin-top:12px;">'
            f'<a href="{_esc(calendar_link)}">Open in Google Calendar</a></p>'
        )
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">Meeting Confirmed ✓</h2>
                <p>Hi {_esc(recipient_name)},</p>
                <p>
                    Your meeting with <strong>{_esc(other_party_name)}</strong> regarding
                    <em>{_esc(auction_title)}</em> has been confirmed.
                </p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Date:</strong> {_esc(scheduled_date)}</p>
                    <p><strong>Time:</strong> {_esc(scheduled_time)}</p>
                    <p><strong>Duration:</strong> {duration_minutes} minutes</p>
                </div>
                <p><strong>Join Meeting:</strong></p>
                <div style="background:#e8f5e9; padding:15px; border-radius:8px; margin:10px 0; text-align:center;">
                    <a href="{_esc(meeting_link)}"
                       style="color:#1a73e8; font-weight:bold; font-size:1.1rem; word-break:break-all;">
                        {_esc(meeting_link)}
                    </a>
                </div>
                {calendar_block}
                <p style="color:#666; font-size:0.9em;">
                    Click the link above at the scheduled time to join via Google Meet.
                </p>
            </div>
        </body>
    </html>
    """


def meeting_cancelled_email_template(
    *,
    recipient_name: str,
    canceller_name: str,
    auction_title: str,
    scheduled_date: str,
    scheduled_time: str,
    reason: str | None,
) -> str:
    reason_block = ""
    if reason and reason.strip():
        reason_block = (
            f'<div style="background:#fdf3f2; padding:12px; border-radius:8px; margin:15px 0;">'
            f"<p><strong>Reason:</strong> {_esc(reason)}</p></div>"
        )
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #c0392b;">Meeting Cancelled</h2>
                <p>Hi {_esc(recipient_name)},</p>
                <p>
                    <strong>{_esc(canceller_name)}</strong> has cancelled the meeting scheduled for
                    <strong>{_esc(scheduled_date)}</strong> at <strong>{_esc(scheduled_time)}</strong>
                    regarding <em>{_esc(auction_title)}</em>.
                </p>
                {reason_block}
                <p style="color:#666;">You can schedule a new meeting from the Deltapreneur platform.</p>
            </div>
        </body>
    </html>
    """


def domain_registration_receipt_email_template(
    *,
    fqdn: str,
    amount_inr: float,
    razorpay_payment_id: str | None,
    order_detail_url: str,
) -> str:
    payment_line = (
        f"<p><strong>Payment ID:</strong> {_esc(razorpay_payment_id)}</p>"
        if razorpay_payment_id
        else ""
    )
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #7c3aed;">Payment received — {_esc(fqdn)}</h2>
                <p>Thank you for your domain registration payment on Deltapreneur.</p>
                <p><strong>Amount:</strong> ₹{amount_inr:,.2f}</p>
                {payment_line}
                <p>We are registering your domain with the registrar. You will receive another email when it is active.</p>
                <a href="{_esc(order_detail_url)}" style="display:inline-block;padding:12px 20px;background:#7c3aed;color:white;text-decoration:none;border-radius:6px;">View order status</a>
            </div>
        </body>
    </html>
    """


def _format_email_datetime(value: str | None) -> str:
    """Turn ISO timestamps into a short customer-facing date when possible."""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        from datetime import datetime

        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%d %b %Y")
    except Exception:
        return raw


def domain_registration_submitted_email_template(
    *,
    fqdn: str,
    order_detail_url: str,
    is_transfer: bool = False,
) -> str:
    title = "Domain transfer submitted" if is_transfer else "Registration submitted"
    action = "Track transfer" if is_transfer else "Track registration"
    body_text = (
        f"Your domain transfer for {_esc(fqdn)} has been submitted and is currently being processed. The transfer may take 5–7 days to complete. We’ll notify you once the transfer is completed."
        if is_transfer
        else "Your domain registration has been submitted and is being processed. This usually completes within a few minutes — we will email you when the domain is active."
    )
    
    return f"""
    <html>
      <body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#111827;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 12px;">
          <tr>
            <td align="center">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb;">
                <tr>
                  <td style="background:linear-gradient(135deg,#7c3aed,#4f46e5);padding:28px 28px 24px;">
                    <p style="margin:0 0 8px;font-size:12px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(255,255,255,0.85);font-weight:700;">Deltapreneur Domains</p>
                    <h1 style="margin:0;font-size:22px;line-height:1.3;color:#ffffff;">{title}</h1>
                    <p style="margin:10px 0 0;font-size:15px;"><a href="https://{_esc(fqdn)}" style="color:#ffffff;text-decoration:none;font-weight:500;">{_esc(fqdn)}</a></p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:28px;">
                    <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#374151;">
                      {body_text}
                    </p>
                    <a href="{_esc(order_detail_url)}" style="display:inline-block;padding:12px 22px;background:#7c3aed;color:#ffffff;text-decoration:none;border-radius:10px;font-size:14px;font-weight:700;">{action}</a>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0 28px 24px;">
                    <p style="margin:0;font-size:12px;line-height:1.5;color:#9ca3af;">Need help? Reply to this email or contact support@deltapreneur.com</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """


HUBREGISTRAR_EMAIL_LOGO_URL = "https://www.deltapreneur.com/email/deltapreneur-logo.png"
HUBREGISTRAR_SITE_URL = "https://www.deltapreneur.com"
HUBREGISTRAR_SOCIAL_FACEBOOK = "https://www.facebook.com/share/16vjEWTjHi/"
HUBREGISTRAR_SOCIAL_X = "https://x.com/CoBrother141506"
HUBREGISTRAR_SOCIAL_LINKEDIN = "https://www.linkedin.com/company/hubregistrar/"


def _styled_fqdn_anchor(
    fqdn: str,
    *,
    href: str,
    color: str,
    font_size: str,
) -> str:
    """Explicit anchor so Gmail cannot autolink the FQDN as unreadably-blue text."""
    return (
        f'<a href="{_esc(href)}" '
        f'style="color:{color} !important;text-decoration:none !important;'
        f'font-size:{font_size};font-weight:800;letter-spacing:-0.02em;line-height:1.2;">'
        f"{_esc(fqdn)}</a>"
    )


def _email_safe_host(host: str) -> str:
    """Break Gmail autolinks on hostnames without changing the visible text."""
    return "&#8203;.".join(_esc(part) for part in str(host).split("."))


def _normalize_email_nameservers(nameservers: object | None) -> list[str]:
    """Return hostname strings only — never dump JSON blobs into the email."""
    if nameservers is None:
        return []
    if isinstance(nameservers, dict):
        hosts = nameservers.get("hosts")
        if isinstance(hosts, list):
            return _normalize_email_nameservers(hosts)
        return []
    if isinstance(nameservers, str):
        raw = nameservers.strip()
        if not raw:
            return []
        if raw.startswith("{") or raw.startswith("["):
            try:
                import json

                return _normalize_email_nameservers(json.loads(raw))
            except Exception:
                return []
        host = raw.rstrip(".").strip()
        return [host] if host and " " not in host else []
    if isinstance(nameservers, (list, tuple)):
        out: list[str] = []
        seen: set[str] = set()
        for item in nameservers:
            for host in _normalize_email_nameservers(item):
                key = host.lower()
                if key not in seen:
                    seen.add(key)
                    out.append(host)
        return out
    host = str(nameservers).strip()
    return [host] if host and not host.startswith("{") else []


def _success_tick_html() -> str:
    """Mint circle + tick with confetti. No square/stroke frame around the circle."""
    return """
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 16px;border-collapse:collapse;">
                      <tr>
                        <td align="center" width="22" style="font-size:9px;line-height:14px;color:#60A5FA;">&#9671;</td>
                        <td align="center" width="64" style="font-size:7px;line-height:14px;color:#F97316;">&#9679;</td>
                        <td align="center" width="22" style="font-size:8px;line-height:14px;color:#34D399;">&#9830;</td>
                      </tr>
                      <tr>
                        <td align="right" valign="middle" style="padding-right:6px;font-size:8px;color:#94A3B8;">&#43;</td>
                        <td align="center" valign="middle" width="64" height="64" style="width:64px;height:64px;background-color:#D1FAE5;border:0;border-radius:32px;color:#047857;font-size:30px;font-weight:700;line-height:64px;font-family:'Segoe UI',Tahoma,Arial,Helvetica,sans-serif;">&#10003;</td>
                        <td align="left" valign="middle" style="padding-left:6px;font-size:9px;color:#3B82F6;">&#9671;</td>
                      </tr>
                      <tr>
                        <td align="center" style="font-size:7px;line-height:14px;color:#F97316;">&#9679;</td>
                        <td align="center" style="font-size:8px;line-height:14px;color:#94A3B8;">&#183;&#183;&#183;</td>
                        <td align="center" style="font-size:8px;line-height:14px;color:#10B981;">&#9830;</td>
                      </tr>
                    </table>
    """


def _email_social_icon(*, href: str, bg: str, label: str, glyph: str) -> str:
    return (
        f'<a href="{_esc(href)}" aria-label="{_esc(label)}" '
        f'style="display:inline-block;width:28px;height:28px;line-height:28px;text-align:center;'
        f'border-radius:14px;background:{bg};color:#ffffff;text-decoration:none;'
        f'font-size:11px;font-weight:700;font-family:\'Segoe UI\',Tahoma,Arial,Helvetica,sans-serif;">{glyph}</a>'
    )


def domain_registration_active_email_template(
    *,
    fqdn: str,
    order_detail_url: str,
    expires_at: str | None,
    nameservers: list[str] | None = None,
    manage_dns_url: str | None = None,
    customer_panel_url: str | None = None,
    logo_url: str | None = None,
    registered_at: str | None = None,
) -> str:
    expiry_display = _format_email_datetime(expires_at) or "—"
    registered_display = _format_email_datetime(registered_at) or "—"
    clean_ns = _normalize_email_nameservers(nameservers)
    ns_rows = "".join(
        f"""
                            <tr>
                              <td style="padding:5px 0;font-family:Consolas,Menlo,ui-monospace,monospace;font-size:13px;line-height:1.4;color:#111827;font-weight:600;word-break:break-word;">
                                <span style="color:#00A86B;">&#9679;</span>&nbsp;{_email_safe_host(ns)}
                              </td>
                            </tr>
        """
        for ns in clean_ns
    ) or """
                            <tr>
                              <td style="padding:4px 0;font-size:13px;color:#6b7280;">Deltapreneur managed DNS</td>
                            </tr>
    """

    dns_href = (manage_dns_url or "").strip()
    if not dns_href:
        dns_href = f"{order_detail_url.rstrip('/')}#dns" if order_detail_url else ""
    legacy = (customer_panel_url or "").strip().lower()
    if not dns_href and customer_panel_url and "openprovider" not in legacy and "resellerclub" not in legacy:
        dns_href = customer_panel_url.strip()

    manage_btn_row = ""
    if dns_href:
        manage_btn_row = (
            "<tr><td align=\"center\" style=\"padding:0 0 10px;\">"
            f'<a href="{_esc(dns_href)}" '
            'style="display:block;width:100%;box-sizing:border-box;padding:12px 16px;background:#00A86B;color:#ffffff;'
            'text-decoration:none;border-radius:8px;font-size:14px;font-weight:700;text-align:center;">Manage DNS</a>'
            "</td></tr>"
        )

    logo_src = (logo_url or "").strip() or HUBREGISTRAR_EMAIL_LOGO_URL
    domain_link = _styled_fqdn_anchor(
        fqdn, href=order_detail_url, color="#111827", font_size="20px"
    )
    fb_icon = _email_social_icon(
        href=HUBREGISTRAR_SOCIAL_FACEBOOK, bg="#1877F2", label="Facebook", glyph="f"
    )
    x_icon = _email_social_icon(
        href=HUBREGISTRAR_SOCIAL_X, bg="#111827", label="X", glyph="X"
    )
    li_icon = _email_social_icon(
        href=HUBREGISTRAR_SOCIAL_LINKEDIN, bg="#0A66C2", label="LinkedIn", glyph="in"
    )

    return f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <meta http-equiv="X-UA-Compatible" content="IE=edge" />
        <style type="text/css">
          html, body {{ margin:0 !important; padding:0 !important; width:100% !important; }}
          img {{ border:0; outline:none; text-decoration:none; max-width:100% !important; height:auto !important; }}
          table {{ border-collapse:collapse; }}
          @media only screen and (max-width:620px) {{
            .email-shell {{ width:100% !important; max-width:100% !important; }}
            .email-px {{ padding-left:16px !important; padding-right:16px !important; }}
          }}
        </style>
      </head>
      <body style="margin:0;padding:0;width:100%;background:#e8edf3;font-family:'Segoe UI',Tahoma,Arial,Helvetica,sans-serif;color:#111827;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0;padding:0;width:100%;background:#e8edf3;">
          <tr>
            <td align="center" style="padding:16px 8px;">
              <!--[if mso]>
              <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td width="600">
              <![endif]-->
              <table role="presentation" class="email-shell" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb;">
                <tr>
                  <td class="email-px" style="background:#0B1F4A;padding:14px 16px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;table-layout:fixed;">
                      <tr>
                        <td align="left" valign="middle" style="font-size:11px;line-height:1.4;color:#ffffff;padding-right:8px;">
                          Trusted &#8226; Secure &#8226; Reliable
                        </td>
                        <td align="right" valign="middle" width="150" style="width:150px;">
                          <img src="{_esc(logo_src)}" alt="Deltapreneur" width="150" height="38" style="display:block;border:0;outline:none;background:transparent;width:150px;max-width:100%;height:auto;margin-left:auto;" />
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td class="email-px" align="center" style="padding:28px 20px 10px;">
                    {_success_tick_html()}
                    <h1 style="margin:0 0 10px;font-size:22px;line-height:1.35;color:#111827;font-weight:700;">
                      Your domain is <span style="color:#00A86B;">successfully active!</span>
                    </h1>
                    <p style="margin:0;font-size:14px;line-height:1.5;color:#6b7280;">
                      Congratulations! Your domain has been registered and is now ready to use.
                    </p>
                  </td>
                </tr>
                <tr>
                  <td class="email-px" style="padding:16px 20px 8px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border:1px solid #e5e7eb;border-radius:12px;">
                      <tr>
                        <td style="padding:16px 16px 12px;">
                          <p style="margin:0 0 4px;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#6b7280;font-weight:700;">DOMAIN</p>
                          <p style="margin:0;word-break:break-word;">{domain_link}</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:0 16px 14px;">
                          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;table-layout:fixed;border-top:1px solid #eef2f6;">
                            <tr>
                              <td valign="top" style="padding:14px 6px 0 0;width:33%;">
                                <p style="margin:0 0 4px;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#6b7280;font-weight:700;line-height:1.3;">REGISTRATION DATE</p>
                                <p style="margin:0;font-size:13px;color:#111827;font-weight:700;line-height:1.35;">{_esc(registered_display)}</p>
                              </td>
                              <td valign="top" style="padding:14px 6px 0;width:33%;">
                                <p style="margin:0 0 4px;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#6b7280;font-weight:700;line-height:1.3;">EXPIRES ON</p>
                                <p style="margin:0;font-size:13px;color:#111827;font-weight:700;line-height:1.35;">{_esc(expiry_display)}</p>
                              </td>
                              <td valign="top" style="padding:14px 0 0 6px;width:33%;">
                                <p style="margin:0 0 4px;font-size:10px;letter-spacing:0.06em;text-transform:uppercase;color:#6b7280;font-weight:700;line-height:1.3;">STATUS</p>
                                <p style="margin:0;display:inline-block;background:#00A86B;color:#ffffff;font-size:11px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;padding:4px 10px;border-radius:999px;">ACTIVE</p>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td class="email-px" style="padding:8px 20px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border:1px solid #e5e7eb;border-radius:12px;">
                      <tr>
                        <td style="padding:14px 16px 16px;">
                          <p style="margin:0 0 8px;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#6b7280;font-weight:700;">YOUR NAMESERVERS</p>
                          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;">
                            {ns_rows}
                          </table>
                          <p style="margin:10px 0 0;font-size:12px;line-height:1.45;color:#6b7280;font-style:italic;">These are Deltapreneur managed nameservers for your domain DNS.</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td class="email-px" style="padding:16px 20px 8px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;">
                      {manage_btn_row}
                      <tr>
                        <td align="center">
                          <a href="{_esc(order_detail_url)}" style="display:block;width:100%;box-sizing:border-box;padding:12px 16px;background:#ffffff;color:#00A86B;text-decoration:none;border-radius:8px;font-size:14px;font-weight:700;border:2px solid #00A86B;text-align:center;">View Order</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding:16px 0 0;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;table-layout:fixed;background:#F4F7FA;">
                      <tr>
                        <td class="email-px" valign="top" width="50%" style="width:50%;padding:16px 12px 16px 18px;">
                          <p style="margin:0 0 3px;font-size:12px;line-height:1.35;font-weight:700;color:#111827;">Need help?</p>
                          <p style="margin:0 0 5px;font-size:11px;line-height:1.4;color:#6b7280;">Our support team is here for you.</p>
                          <a href="mailto:support@deltapreneur.com" style="color:#0B1F4A;font-size:11px;line-height:1.4;font-weight:700;text-decoration:none;word-break:break-word;">support@deltapreneur.com</a>
                        </td>
                        <td valign="top" width="1" style="width:1px;background:#e5e7eb;font-size:1px;line-height:1px;">&nbsp;</td>
                        <td class="email-px" valign="top" width="50%" style="width:50%;padding:16px 18px 16px 12px;">
                          <p style="margin:0 0 3px;font-size:12px;line-height:1.35;font-weight:700;color:#111827;">Thank you for choosing Deltapreneur.</p>
                          <p style="margin:0 0 5px;font-size:11px;line-height:1.4;color:#6b7280;">We're honored to be part of your online journey.</p>
                          <p style="margin:0;font-size:11px;line-height:1.4;color:#0B1F4A;font-weight:700;">- The Deltapreneur team</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td class="email-px" align="center" style="padding:18px 20px 8px;border-top:1px solid #eef2f6;">
                    <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#0B1F4A;">Deltapreneur</p>
                    <p style="margin:0 0 8px;font-size:11px;color:#6b7280;">Follow us</p>
                    <p style="margin:0 0 12px;">{fb_icon}&nbsp;{x_icon}&nbsp;{li_icon}</p>
                    <p style="margin:0;font-size:12px;line-height:1.4;color:#6b7280;">
                      Visit us at <a href="{HUBREGISTRAR_SITE_URL}" style="color:#0B1F4A;font-weight:700;text-decoration:none;">www.deltapreneur.com</a>
                    </p>
                  </td>
                </tr>
                <tr>
                  <td class="email-px" align="center" style="padding:0 20px 18px;">
                    <p style="margin:0;font-size:11px;color:#9ca3af;">&copy; 2026 Deltapreneur. All rights reserved.</p>
                  </td>
                </tr>
              </table>
              <!--[if mso]>
              </td></tr></table>
              <![endif]-->
            </td>
          </tr>
        </table>
      </body>
    </html>
    """



def domain_registration_raa_pending_email_template(
    *,
    fqdn: str,
    registrant_email: str,
    order_detail_url: str,
) -> str:
    return f"""
    <html>
      <body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;color:#111827;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 12px;">
          <tr>
            <td align="center">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e5e7eb;">
                <tr>
                  <td style="background:linear-gradient(135deg,#d97706,#ea580c);padding:28px 28px 24px;">
                    <p style="margin:0 0 8px;font-size:12px;letter-spacing:0.12em;text-transform:uppercase;color:rgba(255,255,255,0.85);font-weight:700;">Deltapreneur Domains</p>
                    <h1 style="margin:0;font-size:22px;line-height:1.3;color:#ffffff;">Verify your email</h1>
                    <p style="margin:10px 0 0;font-size:15px;color:rgba(255,255,255,0.92);">{_esc(fqdn)}</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:28px;">
                    <p style="margin:0 0 14px;font-size:15px;line-height:1.65;color:#374151;">
                      Your domain <strong>{_esc(fqdn)}</strong> is registered. To finish setup, please verify the registrant email
                      <strong>{_esc(registrant_email)}</strong> using the verification message sent to that inbox.
                    </p>
                    <p style="margin:0 0 20px;font-size:13px;line-height:1.55;color:#6b7280;">
                      Whois lookup alone does not complete this step.
                    </p>
                    <a href="{_esc(order_detail_url)}" style="display:inline-block;padding:12px 22px;background:#d97706;color:#ffffff;text-decoration:none;border-radius:10px;font-size:14px;font-weight:700;">Order details</a>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0 28px 24px;">
                    <p style="margin:0;font-size:12px;line-height:1.5;color:#9ca3af;">Need help? Contact support@deltapreneur.com</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """


def domain_registration_failed_email_template(
    *,
    fqdn: str,
    message: str,
    order_detail_url: str,
    is_transfer: bool = False,
) -> str:
    if is_transfer:
        heading = f"Transfer issue — {_esc(fqdn)}"
        intro = (
            "We could not complete the domain transfer after your payment. "
            "If your authorization code was rejected, verify it with your "
            "current registrar — your payment will be refunded and you can "
            "start a new transfer once the refund is complete."
        )
    else:
        heading = f"Registration issue — {_esc(fqdn)}"
        intro = "We could not complete domain registration after your payment."
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #c0392b;">{heading}</h2>
                <p>{intro}</p>
                <p><strong>Details:</strong> {_esc(message)}</p>
                <p>You can retry from the storefront or contact Deltapreneur support.</p>
                <a href="{_esc(order_detail_url)}" style="display:inline-block;padding:12px 20px;background:#7c3aed;color:white;text-decoration:none;border-radius:6px;">View order</a>
            </div>
        </body>
    </html>
    """


def domain_transfer_seller_sold_email_template(
    *,
    user_name: str,
    fqdn: str,
) -> str:
    return f"""
    <html><body style="font-family: Arial, sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:20px;">
            <h2 style="color:#059669;">Your domain was sold — {_esc(fqdn)}</h2>
            <p>Hi {_esc(user_name)},</p>
            <p>Please submit the transfer auth code in your Deltapreneur seller dashboard within the deadline.</p>
        </div>
    </body></html>
    """


def domain_transfer_buyer_purchase_email_template(
    *,
    user_name: str,
    fqdn: str,
    transfer_url: str,
) -> str:
    return f"""
    <html><body style="font-family: Arial, sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:20px;">
            <h2 style="color:#0369a1;">Purchase confirmed — {_esc(fqdn)}</h2>
            <p>Hi {_esc(user_name)},</p>
            <p>We will notify you when the seller submits the transfer code.</p>
            <a href="{_esc(transfer_url)}" style="display:inline-block;padding:12px 20px;background:#0369a1;color:white;text-decoration:none;border-radius:6px;">View transfer</a>
        </div>
    </body></html>
    """


def domain_transfer_auth_available_email_template(
    *,
    user_name: str,
    fqdn: str,
    transfer_url: str,
) -> str:
    return f"""
    <html><body style="font-family: Arial, sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:20px;">
            <h2 style="color:#7c3aed;">Auth code ready — {_esc(fqdn)}</h2>
            <p>Hi {_esc(user_name)},</p>
            <p>The seller submitted the transfer code. Open your purchase to reveal it securely (OTP required).</p>
            <a href="{_esc(transfer_url)}" style="display:inline-block;padding:12px 20px;background:#7c3aed;color:white;text-decoration:none;border-radius:6px;">Reveal auth code</a>
        </div>
    </body></html>
    """


def domain_transfer_seller_reminder_email_template(
    *,
    user_name: str,
    fqdn: str,
    hours_remaining: int,
) -> str:
    return f"""
    <html><body style="font-family: Arial, sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:20px;">
            <h2 style="color:#d97706;">Reminder: submit auth code — {_esc(fqdn)}</h2>
            <p>Hi {_esc(user_name)},</p>
            <p>About <strong>{hours_remaining} hours</strong> remain to submit the transfer auth code.</p>
        </div>
    </body></html>
    """


def seller_payout_details_reminder_email_template(*, payout_settings_url: str) -> str:
    return f"""
    <html><body style="font-family: Arial, sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:20px;">
            <h2 style="color:#d97706;">Action Required: Add Your Deltapreneur Payout Details</h2>
            <p>Hello,</p>
            <p>Your domain sale has been completed.</p>
            <p>Before we can release your payment, please configure your payout details.</p>
            <p>You can add:</p>
            <ul>
                <li>UPI ID</li>
                <li>or Bank Account Details</li>
            </ul>
            <p>Please log in to Deltapreneur and visit:</p>
            <p><strong>Settings -&gt; Payout Settings</strong></p>
            <p>
                <a href="{_esc(payout_settings_url)}"
                   style="display:inline-block;padding:12px 20px;background:#0f766e;color:white;text-decoration:none;border-radius:6px;">
                    Payout Settings
                </a>
            </p>
            <p>If the button does not work: <a href="{_esc(payout_settings_url)}">{_esc(payout_settings_url)}</a></p>
            <p>Once your payout profile is complete, our team can release your payment.</p>
            <p>Thank you,<br />Deltapreneur Team</p>
        </div>
    </body></html>
    """


def virtual_assistant_application_email_template(
    *,
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
) -> str:
    roles_list = ", ".join([r.strip() for r in (roles or "").split(",") if r.strip()]) or "Not specified"
    compensation_block = (
        f"<p><strong>Expected Compensation:</strong> {_esc(expected_compensation)}</p>"
        if expected_compensation
        else ""
    )
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">New Virtual Assistant Application</h2>
                <p><strong>Reference Number:</strong> {_esc(reference_number)}</p>
                <p style="color:#666; font-size:12px;">Submitted at: {_esc(submitted_at)}</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Full Name:</strong> {_esc(full_name)}</p>
                    <p><strong>Email:</strong> {_esc(email)}</p>
                    <p><strong>Phone:</strong> {_esc(phone_number or "—")}</p>
                    <p><strong>Location:</strong> {_esc(location or "—")}</p>
                    <p><strong>18+ Confirmed:</strong> {"Yes" if is_adult else "No"}</p>
                    <p><strong>Profile Photo:</strong> {_esc(profile_photo_url or "Not uploaded")}</p>
                </div>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Bio:</strong> {_esc(bio or "—")}</p>
                    <p><strong>Roles:</strong> {_esc(roles_list)}</p>
                    <p><strong>Skills:</strong> {_esc(skills or "—")}</p>
                    <p><strong>Years of Experience:</strong> {_esc(years_of_experience or "—")}</p>
                    <p><strong>Languages:</strong> {_esc(languages or "—")}</p>
                    <p><strong>LinkedIn:</strong> {_esc(linkedin_url or "—")}</p>
                    <p><strong>Portfolio:</strong> {_esc(portfolio_url or "—")}</p>
                    <p><strong>Resume:</strong> {_esc(resume_url or "Not uploaded")}</p>
                </div>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Availability:</strong> {_esc((availability or "—").replace("_", " ").title())}</p>
                    <p><strong>Hours per Week:</strong> {_esc(hours_per_week or "—")}</p>
                    {compensation_block}
                </div>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                     <p><strong>Info Accurate:</strong> {"Yes" if info_accurate else "No"}</p>
                     <p><strong>Agree to Terms:</strong> {"Yes" if agree_terms else "No"}</p>
                 </div>
             </div>
         </body>
     </html>
     """


def virtual_assistant_application_confirmation_email_template(
    *,
    full_name: str,
    reference_number: str,
    submitted_at: str,
) -> str:
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">Application Received</h2>
                <p>Dear {_esc(full_name)},</p>
                <p>Thank you for applying to become a Virtual Assistant at Deltapreneur. We have received your application and it is currently <strong>under review</strong>.</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Reference Number:</strong> {_esc(reference_number)}</p>
                    <p style="color:#666; font-size:12px;">Submitted at: {_esc(submitted_at)}</p>
                </div>
                <p>Our team will carefully review your application and contact you via email once a decision has been made.</p>
                <p>If you have any questions, please reply to this email or contact us at <a href="mailto:support@deltapreneur.com">support@deltapreneur.com</a>.</p>
                <p>Thank you,<br />Deltapreneur Team</p>
            </div>
        </body>
    </html>
    """


def _role_status_label(status: str | None) -> str:
    mapping = {
        "pending": "Pending",
        "approved": "Approved",
        "rejected": "Rejected",
    }
    return mapping.get((status or "").lower(), (status or "Pending"))


def virtual_assistant_role_decision_email_template(
    *,
    full_name: str,
    reference_number: str,
    roles: list[dict],
    overall_status: str | None,
    reviewer_name: str | None,
    workspace_unlocked: bool,
) -> str:
    rows = ""
    for r in roles:
        status = (r.get("status") or "pending").lower()
        status_color = {
            "approved": "#15803d",
            "rejected": "#b91c1c",
            "pending": "#a16207",
        }.get(status, "#a16207")
        note = r.get("rejectionNote")
        note_html = ""
        if status == "rejected" and note:
            note_html = (
                f'<p style="margin:4px 0 0; color:#b91c1c; font-size:13px;">'
                f"Reason: {_esc(note)}</p>"
            )
        rows += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #eee;">{_esc(r.get('roleName'))}</td>
            <td style="padding:10px; border-bottom:1px solid #eee;">
                <span style="display:inline-block; padding:2px 10px; border-radius:9999px;
                      background:{status_color}; color:#fff; font-size:12px; font-weight:600;">
                    {_role_status_label(status)}
                </span>
            </td>
        </tr>
        {note_html}
        """
    overall = _role_status_label(overall_status)
    unlock_html = ""
    if workspace_unlocked:
        unlock_html = """
        <div style="background:#ecfdf5; border:1px solid #6ee7b7; color:#065f46;
                    padding:14px; border-radius:8px; margin:18px 0;">
            <strong>🎉 Your Virtual Assistant Workspace has been unlocked!</strong><br />
            You can now access your Deltapreneur Virtual Assistant Workspace to start receiving assignments.
        </div>
        """
    reviewer_html = ""
    if reviewer_name:
        reviewer_html = f"<p style=\"color:#666; font-size:12px;\">Reviewed by: {_esc(reviewer_name)}</p>"

    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">Virtual Assistant Application Update</h2>
                <p>Dear {_esc(full_name)},</p>
                <p>We have reviewed your Virtual Assistant application and updated the status of the roles you applied for.</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Reference Number:</strong> {_esc(reference_number)}</p>
                    <p><strong>Overall Application Status:</strong> {_esc(overall)}</p>
                    {reviewer_html}
                </div>
                <table style="width:100%; border-collapse:collapse; margin:16px 0;">
                    <thead>
                        <tr style="text-align:left; color:#374151;">
                            <th style="padding:10px; border-bottom:2px solid #ddd;">Role</th>
                            <th style="padding:10px; border-bottom:2px solid #ddd;">Decision</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
                {unlock_html}
                <p>If you have any questions, please reply to this email or contact us at <a href="mailto:support@deltapreneur.com">support@deltapreneur.com</a>.</p>
                <p>Thank you,<br />Deltapreneur Team</p>
            </div>
        </body>
    </html>
    """


def virtual_assistant_workspace_unlocked_email_template(
    *,
    full_name: str,
    reference_number: str,
    login_url: str,
) -> str:
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">Your Virtual Assistant Workspace is Ready</h2>
                <p>Dear {_esc(full_name)},</p>
                <p>Great news! Your Virtual Assistant workspace has been <strong>unlocked</strong>. You can now access your dashboard, manage your profile, and start receiving assignments.</p>
                <div style="background:#ecfdf5; border:1px solid #6ee7b7; color:#065f46;
                            padding:14px; border-radius:8px; margin:20px 0;">
                    <p><strong>Reference Number:</strong> {_esc(reference_number)}</p>
                    <p style="margin-top:8px;"><a href="{_esc(login_url)}" style="color:#065f46; font-weight:600;">Access Your Workspace</a></p>
                </div>
                <p>If you have any questions, please reply to this email or contact us at <a href="mailto:support@deltapreneur.com">support@deltapreneur.com</a>.</p>
                <p>Thank you,<br />Deltapreneur Team</p>
            </div>
        </body>
    </html>
    """


def virtual_assistant_new_assignment_email_template(
    *,
    full_name: str,
    reference_number: str,
    assigned_company: str | None,
    assigned_role: str | None,
    start_date: str | None,
    end_date: str | None,
    notes: str | None,
) -> str:
    company = _esc(assigned_company or "Not specified")
    role = _esc(assigned_role or "Not specified")
    start = _esc(start_date or "Not specified")
    end = _esc(end_date or "Not specified")
    notes_block = f"<p><strong>Notes:</strong> {_esc(notes)}</p>" if notes else ""
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">New Assignment Assigned</h2>
                <p>Dear {_esc(full_name)},</p>
                <p>You have been assigned a new task through your Virtual Assistant workspace.</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Reference Number:</strong> {_esc(reference_number)}</p>
                    <p><strong>Company:</strong> {company}</p>
                    <p><strong>Role:</strong> {role}</p>
                    <p><strong>Start Date:</strong> {start}</p>
                    <p><strong>End Date:</strong> {end}</p>
                    {notes_block}
                </div>
                <p>Please log in to your workspace to view more details.</p>
                <p>Thank you,<br />Deltapreneur Team</p>
            </div>
        </body>
    </html>
    """


def virtual_assistant_assignment_cancelled_email_template(
    *,
    full_name: str,
    reference_number: str,
    assigned_company: str | None,
    assigned_role: str | None,
    reason: str | None,
) -> str:
    company = _esc(assigned_company or "Not specified")
    role = _esc(assigned_role or "Not specified")
    reason_block = f"<p><strong>Reason:</strong> {_esc(reason)}</p>" if reason else ""
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">Assignment Cancelled</h2>
                <p>Dear {_esc(full_name)},</p>
                <p>An assignment linked to your Virtual Assistant profile has been cancelled.</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Reference Number:</strong> {_esc(reference_number)}</p>
                    <p><strong>Company:</strong> {company}</p>
                    <p><strong>Role:</strong> {role}</p>
                    {reason_block}
                </div>
                <p>Please log in to your workspace for the latest updates.</p>
                <p>Thank you,<br />Deltapreneur Team</p>
            </div>
        </body>
    </html>
    """


def premium_marketplace_buyer_confirmation_email_template(
    *,
    buyer_name: str,
    domain_fqdn: str,
    asking_price: float,
    enquiry_id: str,
) -> str:
    # asking_price retained for call-site compatibility; approved copy does not surface it.
    _ = asking_price
    return f"""
    <html>
        <body style="font-family: Georgia, 'Times New Roman', serif; color:#1a1a2e; background:#f7f7f5;">
            <div style="max-width: 640px; margin: 0 auto; padding: 28px 20px;">
                <div style="background:#ffffff; border:1px solid #e8e6e1; border-radius:16px; padding:32px 28px;">
                    <p style="margin:0 0 6px; font-family:Arial,sans-serif; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:#8a8578;">
                        Deltapreneur Priority Managed Acquisition
                    </p>
                    <h2 style="margin:0 0 18px; font-size:26px; line-height:1.25; color:#111827;">
                        Priority Escalation: Managed Acquisition for {_esc(domain_fqdn)}
                    </h2>
                    <p style="font-family:Arial,sans-serif; font-size:15px; line-height:1.65; color:#374151;">
                        Dear {_esc(buyer_name)},
                    </p>
                    <p style="font-family:Arial,sans-serif; font-size:15px; line-height:1.65; color:#374151;">
                        Thank you for choosing Deltapreneur for your premium domain needs.
                        I am reaching out to confirm that we have received your managed acquisition
                        request for <strong>{_esc(domain_fqdn)}</strong>.
                    </p>
                    <p style="font-family:Arial,sans-serif; font-size:15px; line-height:1.65; color:#374151;">
                        Because this domain is a high-value asset, your request has bypassed our
                        standard queue. I have been assigned as your dedicated specialist and will
                        be personally handling this transaction to ensure it is secure, confidential,
                        and completely stress-free for you.
                    </p>
                    <p style="font-family:Arial,sans-serif; font-size:14px; font-weight:700; color:#111827; margin:22px 0 10px;">
                        Here is your priority timeline:
                    </p>
                    <ol style="font-family:Arial,sans-serif; font-size:14px; line-height:1.7; color:#374151; padding-left:18px; margin:0 0 18px;">
                        <li style="margin-bottom:10px;">
                            <strong>Step 1 (In Progress):</strong> Your managed acquisition file is
                            now open. I am currently conducting a background review of the domain&rsquo;s
                            registration status.
                        </li>
                        <li style="margin-bottom:10px;">
                            <strong>Step 2:</strong> I will be reaching out to the current owner today
                            to confirm their transfer readiness and to negotiate optimal terms on your
                            behalf.
                        </li>
                        <li>
                            <strong>Step 3:</strong> Once the terms are finalized, I will guide you
                            through our secure payment gateway and oversee the technical transfer to
                            your account.
                        </li>
                    </ol>
                    <p style="font-family:Arial,sans-serif; font-size:15px; line-height:1.65; color:#374151;">
                        As a reminder, no payment is required from you today. I will follow up with
                        an update on the owner&rsquo;s status within 24&ndash;48 hours.
                    </p>
                    <p style="font-family:Arial,sans-serif; font-size:15px; line-height:1.65; color:#374151;">
                        If you have any immediate questions regarding the process, please feel free
                        to reply directly to this email.
                    </p>
                    <p style="font-family:Arial,sans-serif; font-size:13px; line-height:1.55; color:#6b7280; margin:18px 0 0;">
                        Reference: {_esc(enquiry_id)}
                    </p>
                    <p style="font-family:Arial,sans-serif; font-size:15px; line-height:1.65; color:#374151; margin-bottom:0;">
                        Best regards,<br />
                        <strong>Priority Acquisition Specialist</strong><br />
                        Deltapreneur<br />
                        080 8575 8575
                    </p>
                </div>
            </div>
        </body>
    </html>
    """


def premium_marketplace_buyer_update_email_template(
    *,
    buyer_name: str,
    domain_fqdn: str,
    status_label: str,
    admin_message: str | None,
    enquiry_id: str,
) -> str:
    note_block = ""
    if admin_message:
        note_block = f"""
                <div style="background:#f8f6f1; border:1px solid #ebe6dc; border-radius:12px; padding:16px; margin:18px 0;">
                    <p style="margin:0 0 6px; font-family:Arial,sans-serif; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#8a8578;">
                        Message from Deltapreneur
                    </p>
                    <p style="margin:0; font-family:Arial,sans-serif; font-size:14px; line-height:1.65; color:#1f2937; white-space:pre-wrap;">
                        {_esc(admin_message)}
                    </p>
                </div>
                """
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif; color:#1a1a2e;">
            <div style="max-width: 600px; margin: 0 auto; padding: 24px;">
                <h2 style="color:#111827; margin-bottom:12px;">Update on your premium acquisition</h2>
                <p>Dear {_esc(buyer_name)},</p>
                <p>
                    There is an update on your managed acquisition for
                    <strong>{_esc(domain_fqdn)}</strong>.
                </p>
                <p><strong>Current status:</strong> {_esc(status_label)}</p>
                <p><strong>Reference:</strong> {_esc(enquiry_id)}</p>
                {note_block}
                <p>
                    You can reply directly to this email if you have questions —
                    our team is personally managing this acquisition with you.
                </p>
                <p>Thank you for your trust,<br />Deltapreneur Acquisition Team</p>
            </div>
        </body>
    </html>
    """


def premium_marketplace_admin_alert_email_template(
    *,
    domain_fqdn: str,
    asking_price: float,
    buyer_name: str,
    buyer_email: str,
    buyer_phone: str,
    message: str,
    enquiry_id: str,
) -> str:
    price_label = f"₹{asking_price:,.0f}"
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1a1a2e;">Premium Marketplace Acquisition Request</h2>
                <p>A buyer submitted a premium marketplace acquisition request.</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Domain:</strong> {_esc(domain_fqdn)}</p>
                    <p><strong>Listed price:</strong> {_esc(price_label)}</p>
                    <p><strong>Enquiry ID:</strong> {_esc(enquiry_id)}</p>
                    <p><strong>Buyer:</strong> {_esc(buyer_name)}</p>
                    <p><strong>Email:</strong> {_esc(buyer_email)}</p>
                    <p><strong>Phone:</strong> {_esc(buyer_phone or "—")}</p>
                    <p><strong>Message:</strong> {_esc(message or "—")}</p>
                </div>
                <p>Open Admin → Domain Enquiries to manage this request.</p>
            </div>
        </body>
    </html>
    """


def technology_purchase_confirmation_email_template(
    *,
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
) -> str:
    payment_line = (
        f"<p><strong>Razorpay Payment ID:</strong> {_esc(razorpay_payment_id)}</p>"
        if razorpay_payment_id
        else ""
    )
    provider_line = (
        f"<p><strong>Service Activation:</strong> {_esc(provider_info)}</p>"
        if provider_info
        else ""
    )
    billing_label = "Monthly" if billing_cycle.lower().startswith("mon") else "Annually" if billing_cycle.lower().startswith("ann") else billing_cycle.title()
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #7c3aed;">Your Deltapreneur purchase is confirmed – {_esc(service_name)}</h2>
                <p>Hi {_esc(customer_name)},</p>
                <p>Your purchase of <strong>{_esc(service_name)}</strong> – <strong>{_esc(plan_name)}</strong> was successful.</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Order ID:</strong> {_esc(cobrother_order_id)}</p>
                    {payment_line}
                    <p><strong>Payment:</strong> Successful</p>
                    <p><strong>Amount:</strong> ₹{amount_inr:,.2f}</p>
                    <p><strong>Billing:</strong> {_esc(billing_label)}</p>
                    <p><strong>Service Status:</strong> {_esc(service_status)}</p>
                    {provider_line}
                    <p><strong>Purchase Date:</strong> {_esc(purchase_date)}</p>
                </div>
                <p>Your service has been successfully activated through Deltapreneur.</p>
                <a href="{_esc(purchases_url)}" style="display:inline-block;padding:12px 20px;background:#7c3aed;color:white;text-decoration:none;border-radius:6px;">View My Purchase</a>
                <p>If the button does not work: <a href="{_esc(purchases_url)}">{_esc(purchases_url)}</a></p>
                <p>Thank you for choosing Deltapreneur.</p>
            </div>
        </body>
    </html>
    """


def technology_purchase_pending_email_template(
    *,
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
) -> str:
    payment_line = (
        f"<p><strong>Razorpay Payment ID:</strong> {_esc(razorpay_payment_id)}</p>"
        if razorpay_payment_id
        else ""
    )
    billing_label = "Monthly" if billing_cycle.lower().startswith("mon") else "Annually" if billing_cycle.lower().startswith("ann") else billing_cycle.title()
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #dc2626;">Payment received – service activation pending</h2>
                <p>Hi {_esc(customer_name)},</p>
                <p>We received your payment for <strong>{_esc(service_name)}</strong> – <strong>{_esc(plan_name)}</strong>. However, service activation is currently pending.</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Order ID:</strong> {_esc(cobrother_order_id)}</p>
                    {payment_line}
                    <p><strong>Payment:</strong> Successful</p>
                    <p><strong>Amount:</strong> ₹{amount_inr:,.2f}</p>
                    <p><strong>Billing:</strong> {_esc(billing_label)}</p>
                    <p><strong>Status:</strong> Pending activation</p>
                    <p><strong>Purchase Date:</strong> {_esc(purchase_date)}</p>
                    <p><strong>Reason:</strong> {_esc(reason)}</p>
                </div>
                <p>Our team has been notified and will complete activation shortly. You will receive a confirmation email once your service is active.</p>
                <a href="{_esc(purchases_url)}" style="display:inline-block;padding:12px 20px;background:#7c3aed;color:white;text-decoration:none;border-radius:6px;">View My Purchase</a>
                <p>If the button does not work: <a href="{_esc(purchases_url)}">{_esc(purchases_url)}</a></p>
                <p>Thank you for your patience,<br />Deltapreneur Support Team</p>
            </div>
        </body>
    </html>
    """


def technology_purchase_failed_email_template(
    *,
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
) -> str:
    payment_line = (
        f"<p><strong>Razorpay Payment ID:</strong> {_esc(razorpay_payment_id)}</p>"
        if razorpay_payment_id
        else ""
    )
    billing_label = "Monthly" if billing_cycle.lower().startswith("mon") else "Annually" if billing_cycle.lower().startswith("ann") else billing_cycle.title()
    return f"""
    <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #dc2626;">Action needed – {_esc(service_name)} activation failed</h2>
                <p>Hi {_esc(customer_name)},</p>
                <p>We received your payment for <strong>{_esc(service_name)}</strong> – <strong>{_esc(plan_name)}</strong>, but the service could not be activated automatically.</p>
                <div style="background:#f4f4f4; padding:15px; border-radius:8px; margin:20px 0;">
                    <p><strong>Order ID:</strong> {_esc(cobrother_order_id)}</p>
                    {payment_line}
                    <p><strong>Payment:</strong> Successful</p>
                    <p><strong>Amount:</strong> ₹{amount_inr:,.2f}</p>
                    <p><strong>Billing:</strong> {_esc(billing_label)}</p>
                    <p><strong>Status:</strong> Activation failed</p>
                    <p><strong>Reason:</strong> {_esc(reason)}</p>
                    <p><strong>Purchase Date:</strong> {_esc(purchase_date)}</p>
                </div>
                <p>No further action is required from you right now — your payment is safe and has not been charged again. Please contact Deltapreneur support and quote your Order ID so we can activate your service or arrange a refund.</p>
                <a href="{_esc(purchases_url)}" style="display:inline-block;padding:12px 20px;background:#7c3aed;color:white;text-decoration:none;border-radius:6px;">View My Purchase</a>
                <p>If the button does not work: <a href="{_esc(purchases_url)}">{_esc(purchases_url)}</a></p>
                <p>We apologise for the inconvenience,<br />Deltapreneur Support Team</p>
            </div>
        </body>
    </html>
    """

