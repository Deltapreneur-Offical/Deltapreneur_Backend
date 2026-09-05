"""Deltapreneur domain transfer knowledge base for Bro AI assistant."""

from __future__ import annotations

import re
from typing import Any

COMMISSION_RATE_PERCENT = 15

TRANSFER_STATUS_EXPLANATIONS: dict[str, str] = {
    "PAYMENT_COMPLETED": "Buyer has successfully paid.",
    "AWAITING_AUTH_CODE": "Payment is complete. The seller must submit transfer information including the authorization code.",
    "AUTH_CODE_SUBMITTED": "Seller has submitted transfer information.",
    "AUTH_CODE_AVAILABLE": "Buyer can access the transfer authorization code.",
    "AUTH_CODE_RECEIVED": "Authorization code has been received by the platform.",
    "AUTH_CODE_VIEWED": "Buyer has viewed the authorization code.",
    "TRANSFER_IN_PROGRESS": "Domain transfer is currently being processed.",
    "TRANSFER_COMPLETED": "Domain transfer finished successfully.",
    "PAYOUT_PENDING": "Seller payout is waiting for admin review.",
    "PAYOUT_APPROVED": "Payout approved for release.",
    "PAYOUT_RELEASED": "Funds have been sent to the seller.",
    "SELLER_PAID": "Seller has received payout funds.",
    "COMPLETED": "Transaction is fully completed.",
    "REFUNDED": "Transaction was cancelled and refunded.",
    "DISPUTED": "Transfer is under review due to a dispute.",
    "ADMIN_REVIEW_REQUIRED": "Transfer requires admin review before proceeding.",
}

COMMON_REGISTRARS = (
    "GoDaddy",
    "Namecheap",
    "Cloudflare",
    "Hostinger",
    "Google Domains",
    "Dynadot",
    "Porkbun",
    "Name.com",
)

SUPPORT_CONTACT_MESSAGE = "Please contact Deltapreneur Support for account-specific assistance."

SECURITY_RULES = (
    "Never reveal passwords, payment credentials, internal admin information, other user information, or full bank account numbers.",
    "Only display masked account numbers when appropriate (example: *****6789).",
    "If platform data is unavailable for account-specific questions, say: "
    f'"{SUPPORT_CONTACT_MESSAGE}"',
    "Do not guess account-specific transfer status, payout amounts, or user details.",
)

TRANSFER_TOPIC_PATTERNS: list[tuple[str, str]] = [
    (
        "auth_code",
        r"\b(auth(?:orization)?\s*code|epp\s*code|auth\s*code|transfer\s*code)\b",
    ),
    (
        "commission",
        r"\b(commission|fee|how much do i (?:get|receive|earn)|seller (?:receives|gets|net))\b",
    ),
    (
        "payout",
        r"\b(payout|get paid|when will i (?:get|receive) (?:paid|payment|money|funds)|payout pending|payout settings|upi|bank account)\b",
    ),
    (
        "refund",
        r"\b(refund|transfer fail|failed transfer|cancel(?:led)? transaction)\b",
    ),
    (
        "transfer_status",
        r"\b(transfer status|what does .+ mean|payment completed|payout pending|payout approved|payout released)\b",
    ),
    (
        "buyer_receive",
        r"\b(when will i receive (?:my )?domain|when do i get (?:my )?domain|how long.*domain)\b",
    ),
    (
        "transfer_time",
        r"\b(how long.*transfer|transfer take|transfer time|transfer duration)\b",
    ),
    (
        "seller_flow",
        r"\b(how do i (?:sell|transfer)|seller (?:process|flow|steps)|submit auth|unlock domain|list.*sold)\b",
    ),
    (
        "buyer_flow",
        r"\b(how do i (?:buy|transfer|receive)|buyer (?:process|flow|steps)|initiate transfer|purchase flow)\b",
    ),
    (
        "escrow",
        r"\b(escrow|payment held|funds held|when does seller get paid)\b",
    ),
]


def is_domain_transfer_question(text: str) -> bool:
    lowered = text.lower()
    if any(re.search(pattern, lowered) for _, pattern in TRANSFER_TOPIC_PATTERNS):
        return True
    return bool(
        re.search(
            r"\b(domain transfer|transfer a domain|transfer process|transfer my domain|"
            r"marketplace transfer|sold domain|after (?:payment|purchase))\b",
            lowered,
        )
    )


def detect_transfer_topic(text: str) -> str:
    lowered = text.lower()
    for topic, pattern in TRANSFER_TOPIC_PATTERNS:
        if re.search(pattern, lowered):
            return topic
    if is_domain_transfer_question(lowered):
        return "general"
    return "general"


def commission_example(sale_price: int = 1000) -> dict[str, int]:
    commission = round(sale_price * COMMISSION_RATE_PERCENT / 100)
    return {
        "sale_price": sale_price,
        "commission": commission,
        "seller_receives": sale_price - commission,
    }


def build_knowledge_context() -> dict[str, Any]:
    example = commission_example()
    return {
        "about": (
            "Deltapreneur is a secure domain marketplace. Buyers purchase domains and sellers list domains for sale. "
            "All payments are protected through an escrow-style process. "
            "The seller does not receive funds until the domain transfer has been completed and verified."
        ),
        "buyer_purchase_flow": [
            "Buyer selects a domain listing.",
            "Buyer completes payment.",
            "Deltapreneur securely holds the payment.",
            "Seller receives a notification.",
            "Seller begins transfer process.",
            "Buyer receives transfer instructions.",
            "Domain transfer is completed.",
            "Transfer is verified.",
            "Seller payout becomes eligible.",
            "Admin releases payout.",
            "Transaction is completed.",
        ],
        "domain_transfer_flow": [
            "Seller unlocks the domain at the registrar.",
            "Seller obtains Authorization Code (EPP/Auth Code) if required.",
            "Seller submits transfer information.",
            "Buyer initiates transfer at their registrar.",
            "Buyer enters the Authorization Code when required.",
            "Domain transfer proceeds.",
            "Transfer completion is confirmed.",
            "Deltapreneur updates transfer status.",
        ],
        "registrars": list(COMMON_REGISTRARS),
        "authorization_code": (
            "Authorization Code (Auth Code / EPP Code) is a security code used to transfer domains between registrars. "
            "The buyer may need this code to initiate the transfer. "
            "Not every domain transfer requires the same steps because registrars differ."
        ),
        "transfer_statuses": TRANSFER_STATUS_EXPLANATIONS,
        "seller_payout_flow": [
            "Open Payout Settings.",
            "Configure payout details.",
            "Add UPI or Bank Account.",
            "Save payout profile.",
            "After transfer completion, transfer is verified.",
            "Payout becomes eligible.",
            "Admin reviews payout.",
            "Admin releases payout.",
            "Seller receives funds.",
        ],
        "commission": {
            "rate_percent": COMMISSION_RATE_PERCENT,
            "deducted_from": "seller proceeds",
            "example": example,
        },
        "security_rules": list(SECURITY_RULES),
        "support_message": SUPPORT_CONTACT_MESSAGE,
    }


def build_system_prompt_section() -> str:
    kb = build_knowledge_context()
    example = kb["commission"]["example"]
    status_lines = "\n".join(
        f"- {label}: {description}"
        for label, description in kb["transfer_statuses"].items()
    )
    return "\n".join(
        [
            "COBROTHER DOMAIN TRANSFER KNOWLEDGE BASE (source of truth for buying, selling, transferring, payouts, escrow, commissions, and refunds):",
            kb["about"],
            "",
            "Buyer purchase flow:",
            *[f"{index}. {step}" for index, step in enumerate(kb["buyer_purchase_flow"], start=1)],
            "",
            "Domain transfer flow:",
            *[f"{index}. {step}" for index, step in enumerate(kb["domain_transfer_flow"], start=1)],
            "",
            f"Authorization code: {kb['authorization_code']}",
            "",
            "Transfer status explanations:",
            status_lines,
            "",
            "Seller payout flow:",
            *[f"{index}. {step}" for index, step in enumerate(kb["seller_payout_flow"], start=1)],
            "",
            f"Commission: Deltapreneur charges {COMMISSION_RATE_PERCENT}% commission deducted from seller proceeds. "
            f"Example: sale ₹{example['sale_price']} → commission ₹{example['commission']} → seller receives ₹{example['seller_receives']}.",
            "",
            "Support rules:",
            f"- For account-specific transfer or payout data you do not have, say: {SUPPORT_CONTACT_MESSAGE}",
            "- Always provide step-by-step explanations.",
            "- Follow the Deltapreneur workflow above instead of generic marketplace workflows.",
            "- Never reveal passwords, payment credentials, internal admin information, other user information, or full bank account numbers.",
        ]
    )


def _format_steps(title: str, steps: list[str]) -> str:
    return "\n".join([title, ""] + [f"{index}. {step}" for index, step in enumerate(steps, start=1)])


CONTEXT_UNAVAILABLE_MESSAGE = (
    "I couldn't determine your current transfer status. "
    "Please open your order details page or contact Deltapreneur Support."
)

CONTEXT_AWARE_TOPIC_PATTERNS: list[tuple[str, str]] = [
    ("auth_code_where", r"\b(where (?:do i|to|can i) enter|where.*auth\s*code|enter the auth)\b"),
    (
        "auth_code_received_next",
        r"\b(got the auth|received the auth|i have the auth|auth code.*what next|what do i do now|what next)\b",
    ),
    ("auth_code_cant_see", r"\b(can'?t see|cannot see|not visible|don'?t see).*(auth|code|authorization)\b"),
    ("otp_issue", r"\b(where is the otp|cannot see.*otp|didn'?t receive.*otp|verify.*otp|send otp)\b"),
    ("transfer_pending", r"\b(transfer is pending|my transfer is pending|still pending|why.*pending)\b"),
    ("what_next", r"\b(what should i do next|what do i do next|next step|what now)\b"),
    ("how_transfer", r"\b(how do i transfer|how to transfer my domain|transfer my domain)\b"),
]


def needs_live_transfer_context(text: str) -> bool:
    lowered = text.lower()
    if any(re.search(pattern, lowered) for _, pattern in CONTEXT_AWARE_TOPIC_PATTERNS):
        return True
    return bool(
        re.search(
            r"\b(my order|my transfer|my payout|my domain purchase|current status|this order)\b",
            lowered,
        )
    )


def detect_context_aware_topic(text: str) -> str:
    lowered = text.lower()
    for topic, pattern in CONTEXT_AWARE_TOPIC_PATTERNS:
        if re.search(pattern, lowered):
            return topic
    if needs_live_transfer_context(lowered):
        return "what_next"
    return "what_next"


def _format_registrar_steps(registrar_name: str) -> list[str]:
    from app.service.domain.domain_transfer_instruction_service import get_transfer_instructions

    return get_transfer_instructions(registrar_name).get("steps", [])


def _transfer_header(ctx: dict[str, Any]) -> str:
    domain = ctx.get("domain_fqdn") or "your domain"
    status = (ctx.get("transfer_status") or "").replace("_", " ").title()
    role = ctx.get("user_role") or "user"
    return f"**{domain}** — Status: **{status}** (you are the {role})"


def build_context_aware_response(message: str, transfer_context: dict[str, Any]) -> str | None:
    if not transfer_context.get("available"):
        if needs_live_transfer_context(message) or is_domain_transfer_question(message):
            return CONTEXT_UNAVAILABLE_MESSAGE
        return None

    topic = detect_context_aware_topic(message)
    if topic == "general" and detect_transfer_topic(message) != "general":
        topic = detect_context_aware_topic(message)

    handlers = {
        "auth_code_where": _response_auth_code_where,
        "auth_code_received_next": _response_auth_code_received_next,
        "auth_code_cant_see": _response_auth_code_cant_see,
        "otp_issue": _response_otp_issue,
        "transfer_pending": _response_transfer_pending,
        "what_next": _response_what_next,
        "how_transfer": _response_how_transfer,
    }
    handler = handlers.get(topic, _response_what_next)
    response = handler(message, transfer_context)
    if response:
        return response

    if is_domain_transfer_question(message):
        return _response_what_next(message, transfer_context)
    return None


def _response_auth_code_where(message: str, ctx: dict[str, Any]) -> str:
    from app.service.domain.domain_transfer_instruction_service import detect_registrar_from_text

    role = ctx.get("user_role")
    if role == "seller":
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "As the seller, you submit the authorization code in Deltapreneur on your seller transfer page — not at the buyer's registrar.",
                "",
                "Next steps:",
                "1. Unlock the domain at your current registrar.",
                "2. Obtain the authorization (EPP) code.",
                "3. Open your seller transfer page in Deltapreneur.",
                "4. Submit the auth code and registrar details.",
            ]
        )

    registrar = (
        detect_registrar_from_text(message)
        or ctx.get("buyer_target_registrar")
        or ctx.get("seller_registrar_name")
        or ""
    )
    otp = ctx.get("otp_status") or {}
    auth = ctx.get("auth_code_status") or {}

    lines = [_transfer_header(ctx), ""]
    if auth.get("status") == "not_submitted":
        lines.extend(
            [
                "The authorization code is not available yet. Wait for the seller to submit transfer information.",
                "",
                ctx.get("next_step") or "",
            ]
        )
        return "\n".join(lines)

    if otp.get("required_for_reveal") and not otp.get("verified"):
        lines.extend(
            [
                "Before you can use the authorization code, verify the OTP sent to your registered email on your buyer transfer page.",
                "",
                "Steps:",
                "1. Click **Send OTP** on your transfer page.",
                "2. Check your email.",
                "3. Enter the verification code and submit.",
                "4. The authorization code will become visible.",
            ]
        )
        return "\n".join(lines)

    if not registrar.strip():
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "Which registrar are you transferring the domain to?",
                "",
                "Common registrars: GoDaddy, Namecheap, Hostinger, Cloudflare, Dynadot, Porkbun, Name.com.",
                "",
                "Tell me your registrar and I can give step-by-step instructions for entering the authorization code.",
            ]
        )

    steps = _format_registrar_steps(registrar)
    lines.extend(
        [
            f"Enter the authorization code at **{registrar.strip()}**:",
            "",
            *[f"{index}. {step}" for index, step in enumerate(steps, start=1)],
            "",
            "The auth code is shown on your Deltapreneur buyer transfer page after OTP verification. "
            "For security, I cannot display the code here in chat.",
        ]
    )
    return "\n".join(lines)


def _response_auth_code_received_next(message: str, ctx: dict[str, Any]) -> str:
    role = ctx.get("user_role")
    otp = ctx.get("otp_status") or {}
    auth = ctx.get("auth_code_status") or {}

    if role == "seller":
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "You have submitted transfer information. The buyer will verify OTP (if required), initiate transfer at their registrar, and confirm completion.",
                "",
                ctx.get("next_step") or "",
            ]
        )

    if auth.get("status") == "not_submitted":
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "The seller has not submitted the authorization code yet. You will be notified when it becomes available.",
            ]
        )

    if otp.get("required_for_reveal") and not otp.get("verified"):
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "For security reasons, you must first verify the OTP sent to your registered email. "
                "Once verified, the authorization code will be revealed on your transfer page.",
                "",
                "Steps:",
                "1. Click **Send OTP**.",
                "2. Check your email.",
                "3. Enter the verification code.",
                "4. Submit OTP — the auth code will become visible.",
            ]
        )

    return "\n".join(
        [
            _transfer_header(ctx),
            "",
            "Your authorization code is now available on your buyer transfer page. "
            "Use this code at your registrar when initiating the domain transfer.",
            "",
            "Next steps:",
            "1. Log in to your registrar.",
            "2. Start **Transfer domain in**.",
            "3. Enter the domain and authorization code.",
            "4. Mark transfer as started in Deltapreneur.",
            "5. Confirm transfer completion once the domain appears in your account.",
        ]
    )


def _response_auth_code_cant_see(message: str, ctx: dict[str, Any]) -> str:
    role = ctx.get("user_role")
    auth = ctx.get("auth_code_status") or {}
    otp = ctx.get("otp_status") or {}

    if role == "seller":
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "Sellers enter the authorization code on the seller transfer page — it is not revealed via OTP.",
                "",
                ctx.get("next_step") or "",
            ]
        )

    if auth.get("status") == "not_submitted":
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "The authorization code is not visible yet because the seller has not submitted it.",
                "",
                ctx.get("next_step") or "",
            ]
        )

    if otp.get("required_for_reveal") and not otp.get("verified"):
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "The authorization code is hidden until you verify your identity.",
                "",
                "Steps:",
                "1. Click **Send OTP** on your transfer page.",
                "2. Check your registered email.",
                "3. Enter the verification code.",
                "4. Submit OTP — the authorization code will become visible.",
            ]
        )

    return "\n".join(
        [
            _transfer_header(ctx),
            "",
            "Your authorization code should be visible on your buyer transfer page.",
            "Open **Purchases → Transfers** and select this domain if you are not already on the transfer page.",
        ]
    )


def _response_otp_issue(message: str, ctx: dict[str, Any]) -> str:
    otp = ctx.get("otp_status") or {}
    if ctx.get("user_role") != "buyer":
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "OTP verification applies to buyers revealing the authorization code. "
                "As the seller, submit the auth code directly on your transfer page.",
            ]
        )

    if otp.get("verified"):
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                "Your OTP is already verified. The authorization code should be visible on your buyer transfer page.",
            ]
        )

    return "\n".join(
        [
            _transfer_header(ctx),
            "",
            "To reveal the authorization code:",
            "",
            "1. Click **Send OTP** on your transfer page.",
            "2. Check your registered email (including spam).",
            "3. Enter the 6-digit verification code.",
            "4. Submit OTP.",
            "",
            "If you did not receive the email, wait a minute and request a new OTP. "
            "Contact Deltapreneur Support if the issue continues.",
        ]
    )


def _response_transfer_pending(message: str, ctx: dict[str, Any]) -> str:
    status = ctx.get("transfer_status") or ""
    payout = ctx.get("payout_status") or {}

    if "payout" in message.lower() and status in {
        "PAYOUT_PENDING",
        "PAYOUT_APPROVED",
    }:
        return _response_payout_pending(ctx)

    explanation = TRANSFER_STATUS_EXPLANATIONS.get(status, "")
    lines = [
        _transfer_header(ctx),
        "",
        explanation or "Your transfer is in progress.",
        "",
        ctx.get("next_step") or "",
    ]
    if payout.get("eligible") and ctx.get("user_role") == "seller":
        lines.append("")
        if not payout.get("payout_profile_complete"):
            lines.append("Tip: complete **Payout Settings** (bank or UPI) so admin can release your funds.")
    return "\n".join(lines)


def _response_payout_pending(ctx: dict[str, Any]) -> str:
    payout = ctx.get("payout_status") or {}
    lines = [
        _transfer_header(ctx),
        "",
        "Your domain transfer is complete and your payout is eligible for release.",
        "",
    ]
    if ctx.get("user_role") == "seller":
        if not payout.get("payout_profile_complete"):
            lines.extend(
                [
                    "Payout is pending because your payout profile may be incomplete.",
                    "",
                    "Next steps:",
                    "1. Open **Settings → Payouts**.",
                    "2. Add bank account or UPI details.",
                    "3. Save your payout profile.",
                    "4. Admin will review and release funds manually.",
                ]
            )
        else:
            lines.extend(
                [
                    "Your payout details are on file. Admin will review and transfer funds manually.",
                    "You will be notified once payout is released.",
                ]
            )
        if payout.get("seller_payout_inr") is not None:
            lines.append("")
            lines.append(f"Expected seller payout: ₹{payout['seller_payout_inr']} (after 15% commission).")
    else:
        lines.append("The seller's payout is awaiting admin review. No action is required from you as the buyer.")
    return "\n".join(lines)


def _response_what_next(message: str, ctx: dict[str, Any]) -> str:
    if detect_transfer_topic(message) == "payout":
        return _response_payout_pending(ctx)

    status = ctx.get("transfer_status") or ""
    status_responses = {
        "PAYMENT_COMPLETED": (
            "Payment is complete and held in escrow. The seller is preparing transfer information. "
            "You will be notified when the authorization code becomes available."
        ),
        "AWAITING_AUTH_CODE": (
            "Payment is secured. The seller must unlock the domain and submit the authorization code."
        ),
        "AUTH_CODE_AVAILABLE": (
            "Your authorization code is ready. Verify your OTP (if required) and begin the transfer at your registrar."
        ),
        "AUTH_CODE_RECEIVED": (
            "Transfer information has been received. Verify OTP to reveal the authorization code, then start transfer at your registrar."
        ),
        "AUTH_CODE_VIEWED": (
            "You have viewed the authorization code. Initiate transfer at your registrar and mark it as started in Deltapreneur."
        ),
        "TRANSFER_IN_PROGRESS": (
            "The transfer has already been initiated. Please wait for your registrar to complete the transfer, "
            "then confirm completion in Deltapreneur."
        ),
        "TRANSFER_COMPLETED": "Your transfer has been completed successfully.",
        "PAYOUT_PENDING": "Transfer is complete. Seller payout is awaiting admin review and release.",
        "PAYOUT_APPROVED": "Payout has been approved and is awaiting release.",
        "PAYOUT_RELEASED": "Payout has been released to the seller.",
        "SELLER_PAID": "The seller has received payout funds.",
        "COMPLETED": "This transaction is fully completed.",
        "REFUNDED": "This order was cancelled and funds were returned.",
        "DISPUTED": "This transfer is under dispute review.",
    }

    role = ctx.get("user_role")
    body = status_responses.get(status)
    if role == "seller" and status == "PAYMENT_COMPLETED":
        body = "Payment is complete. Submit the authorization code and transfer details on your seller transfer page."
    if role == "seller" and status == "AWAITING_AUTH_CODE":
        body = "Unlock the domain at your registrar, obtain the auth code, and submit it in Deltapreneur."

    return "\n".join(
        [
            _transfer_header(ctx),
            "",
            body or ctx.get("next_step") or "Review your transfer page for available actions.",
            "",
            f"**Your next step:** {ctx.get('next_step') or 'Check your transfer page.'}",
        ]
    )


def _response_how_transfer(message: str, ctx: dict[str, Any]) -> str:
    role = ctx.get("user_role")
    if role == "seller":
        kb = build_knowledge_context()
        return "\n".join(
            [
                _transfer_header(ctx),
                "",
                _format_steps("Domain transfer steps for sellers:", kb["domain_transfer_flow"]),
                "",
                f"**Your next step:** {ctx.get('next_step') or 'Open your seller transfer page.'}",
            ]
        )
    return _response_what_next(message, ctx)


def build_deterministic_response(message: str) -> str | None:
    if not is_domain_transfer_question(message):
        return None

    topic = detect_transfer_topic(message)
    kb = build_knowledge_context()
    example = kb["commission"]["example"]

    if topic == "auth_code":
        return "\n".join(
            [
                "An Auth Code (Authorization Code / EPP Code) is a transfer security code used by many registrars.",
                "",
                "How it works on Deltapreneur:",
                "1. After payment, the seller unlocks the domain at their registrar.",
                "2. The seller obtains the Auth Code from the registrar if required.",
                "3. The seller submits the transfer information in Deltapreneur.",
                "4. The buyer can then access the code and initiate transfer at their registrar.",
                "",
                "Note: registrar steps differ. Common registrars include GoDaddy, Namecheap, Cloudflare, Hostinger, Dynadot, and Porkbun.",
                "",
                f"For your specific transaction status, {SUPPORT_CONTACT_MESSAGE.lower()}",
            ]
        )

    if topic == "commission":
        return "\n".join(
            [
                f"Deltapreneur charges a {COMMISSION_RATE_PERCENT}% commission on domain sales.",
                "",
                "Example:",
                f"- Sale price: ₹{example['sale_price']}",
                f"- Commission: ₹{example['commission']}",
                f"- Seller receives: ₹{example['seller_receives']}",
                "",
                "Commission is deducted from seller proceeds before payout release.",
            ]
        )

    if topic == "payout":
        return "\n".join(
            [
                _format_steps("To receive seller payout on Deltapreneur:", kb["seller_payout_flow"]),
                "",
                "Important:",
                "- Payouts are processed only after successful transfer completion and verification.",
                "- Payout Pending means the transfer completed and payout is awaiting admin review.",
                "- Ensure Payout Settings include UPI or bank account details before payout release.",
                "",
                f"For your specific payout status, {SUPPORT_CONTACT_MESSAGE.lower()}",
            ]
        )

    if topic == "refund":
        return "\n".join(
            [
                "If a domain transfer cannot be completed, Deltapreneur may review the case and determine whether a refund or alternative resolution is appropriate.",
                "",
                "General guidance:",
                "1. Check your transfer timeline in your Deltapreneur purchase or seller dashboard.",
                "2. Confirm whether the seller submitted transfer information and whether the buyer initiated transfer at their registrar.",
                "3. If the transfer is blocked or disputed, Deltapreneur support can review the transaction.",
                "",
                f"{SUPPORT_CONTACT_MESSAGE}",
            ]
        )

    if topic == "transfer_status":
        lowered = message.lower()
        for status_key, description in TRANSFER_STATUS_EXPLANATIONS.items():
            readable = status_key.replace("_", " ").title()
            if status_key.lower().replace("_", " ") in lowered or readable.lower() in lowered:
                return f"**{readable}**: {description}"
        status_block = "\n".join(
            f"- {key.replace('_', ' ').title()}: {value}"
            for key, value in TRANSFER_STATUS_EXPLANATIONS.items()
        )
        return "\n".join(
            [
                "Deltapreneur transfer status meanings:",
                "",
                status_block,
                "",
                f"For your specific transaction, {SUPPORT_CONTACT_MESSAGE.lower()}",
            ]
        )

    if topic == "buyer_receive":
        return "\n".join(
            [
                "After successful payment, the seller must complete the transfer process before you receive the domain.",
                "",
                "Typical buyer steps:",
                "1. Complete payment — Deltapreneur holds funds securely.",
                "2. Wait for the seller to submit transfer information.",
                "3. Access transfer instructions and the Auth Code when available.",
                "4. Initiate transfer at your registrar.",
                "5. Confirm transfer completion in Deltapreneur.",
                "",
                "Transfer times vary depending on the registrar and seller response time.",
            ]
        )

    if topic == "transfer_time":
        return "\n".join(
            [
                "Domain transfer times depend on the registrar and how quickly both parties complete their steps.",
                "",
                "Some transfers complete quickly; others may take several days.",
                "",
                "Deltapreneur holds payment in escrow until transfer completion is verified, then seller payout becomes eligible.",
            ]
        )

    if topic == "seller_flow":
        return "\n".join(
            [
                _format_steps("When you sell a domain on Deltapreneur:", kb["domain_transfer_flow"]),
                "",
                "After transfer is verified:",
                "- Payout becomes eligible.",
                "- Admin reviews and releases payout to your configured UPI or bank account.",
                "",
                "Tip: submit the Auth Code promptly after payment to keep the transfer moving.",
            ]
        )

    if topic == "buyer_flow":
        return "\n".join(
            [
                _format_steps("When you buy a domain on Deltapreneur:", kb["buyer_purchase_flow"]),
                "",
                "Your payment is held securely until the domain transfer is completed and verified.",
            ]
        )

    if topic == "escrow":
        return "\n".join(
            [
                "Deltapreneur uses an escrow-style payment process for domain purchases.",
                "",
                "1. Buyer completes payment.",
                "2. Deltapreneur securely holds the payment.",
                "3. Seller completes the domain transfer.",
                "4. Transfer is verified.",
                "5. Seller payout becomes eligible and is released after admin review.",
                "",
                "The seller does not receive funds until transfer completion is verified.",
            ]
        )

    return "\n".join(
        [
            kb["about"],
            "",
            _format_steps("Buyer purchase flow:", kb["buyer_purchase_flow"]),
            "",
            _format_steps("Domain transfer flow:", kb["domain_transfer_flow"]),
            "",
            f"Commission: {COMMISSION_RATE_PERCENT}% deducted from seller proceeds "
            f"(example: ₹{example['sale_price']} sale → ₹{example['seller_receives']} to seller).",
            "",
            f"For account-specific transfer or payout details, {SUPPORT_CONTACT_MESSAGE.lower()}",
        ]
    )
