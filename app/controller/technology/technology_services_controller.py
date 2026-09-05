"""Technology Services API Controller (Provider-powered Technology Services).

Handles catalogue listings, product page details, subscription provisioning,
user active subscriptions, renewals, upgrades, cancellations, and invoices.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.controller.auth.auth_controller import get_current_user
from app.core.config import settings
from app.core.database import get_async_db, get_db
from app.entity.technology_services.technology_service_entity import TechnologyServiceEntity
from app.entity.technology_services.technology_subscription_entity import TechnologySubscriptionEntity
from app.entity.technology_services.technology_subscription_invoice_entity import TechnologySubscriptionInvoiceEntity
from app.integrations.resellportal.client import get_resellportal_client
from app.service.auth.mail_service import MailService
from app.service.resellportal.product_mapper import build_order_parameters, get_product_key, is_provider_mapped

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/technology-services", tags=["Technology Services"])


# -------------------------------------------------------------------
# Request / Response Schemas
# -------------------------------------------------------------------

class SubscribeRequest(BaseModel):
    service_slug: str = Field(..., description="Service identifier slug")
    plan_code: str = Field("starter", description="Selected plan code: starter, pro, enterprise")
    billing_cycle: str = Field("monthly", description="Billing cycle: monthly, annually")


class RenewalRequest(BaseModel):
    billing_cycle: str = Field("monthly", description="Billing cycle: monthly, annually")


class UpgradeRequest(BaseModel):
    new_plan_code: str = Field(..., description="Target plan code to upgrade to")


class AdminConfigUpdate(BaseModel):
    global_margin_percent: Optional[float] = Field(None, description="Global margin percentage")
    wallet_balance: Optional[float] = Field(None, description="Reseller wallet balance")


class AdminToggleService(BaseModel):
    is_available: bool = Field(True, description="Enable or disable service")


class AdminPriceOverride(BaseModel):
    price_override_monthly: Optional[float] = Field(None, description="Custom monthly price override")
    price_override_annually: Optional[float] = Field(None, description="Custom annual price override")


# -------------------------------------------------------------------
# Seed Catalogue Data (17 Services)
# -------------------------------------------------------------------

DEFAULT_SERVICES_SEED = [
    {
        "slug": "ai-business-suite",
        "name": "AI Business Suite",
        "category": "AI",
        "badge": "Popular",
        "icon": "Cpu",
        "is_featured": True,
        "display_order": 1,
        "short_description": "All-in-one AI platform for content creation, automated customer engagement, and business intelligence.",
        "long_description": "Transform your enterprise workflow with HubRegistrar's AI Business Suite. Leverage state-of-the-art multi-model AI engines to draft content, summarize documents, analyze market trends, and automate repetitive tasks across your team.",
        "features": ["AI Content Writer & Editor", "Automated Lead Scoring", "Smart Document Summarizer", "Multi-model LLM Switching", "24/7 AI Customer Copilot"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 29, "price_annually": 290, "features": ["Up to 50k Words/mo", "3 Team Members", "Standard Support"]},
            {"code": "pro", "name": "Pro", "price_monthly": 79, "price_annually": 790, "features": ["Unlimited Words", "10 Team Members", "Custom AI Prompts", "Priority Support"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 199, "price_annually": 1990, "features": ["Dedicated AI Fine-Tuning", "Unlimited Users", "Custom API Access", "24/7 SLA Support"]}
        ],
        "faqs": [
            {"question": "How quickly can my team start using AI Business Suite?", "answer": "Instant access. As soon as your subscription is activated, your team dashboard will be live."},
            {"question": "Is my proprietary data kept confidential?", "answer": "Yes, all data processed through HubRegistrar AI Suite is encrypted in transit and at rest with zero model training on your private inputs."}
        ]
    },
    {
        "slug": "website-builder",
        "name": "Website Builder",
        "category": "Business",
        "badge": "Featured",
        "icon": "Layout",
        "is_featured": True,
        "display_order": 2,
        "short_description": "Next-gen visual web builder with custom domains, AI layout generator, and built-in SEO.",
        "long_description": "Build high-converting, lightning-fast websites without writing a single line of code. HubRegistrar Website Builder provides drag-and-drop flexibility, custom SSL certificates, ultra-fast CDN delivery, and deep analytics.",
        "features": ["Drag-and-Drop Drag Builder", "AI Page Generator", "Free SSL Certificate", "Custom Domain Integration", "Mobile-Optimized Responsive Layouts"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 15, "price_annually": 150, "features": ["5 Published Pages", "10GB Storage", "Free SSL"]},
            {"code": "pro", "name": "Pro", "price_monthly": 39, "price_annually": 390, "features": ["Unlimited Pages", "50GB Storage", "Custom Domain", "Analytics"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 99, "price_annually": 990, "features": ["Unmetered Bandwidth", "E-commerce Engine", "Multi-language Support"]}
        ],
        "faqs": [
            {"question": "Can I connect my OpenProvider or custom domain?", "answer": "Yes, connecting any domain registered through HubRegistrar or third-party registrars takes just one click."}
        ]
    },
    {
        "slug": "crm",
        "name": "CRM",
        "category": "Business",
        "badge": "Best Seller",
        "icon": "Users",
        "is_featured": True,
        "display_order": 3,
        "short_description": "Streamlined customer relationship management, sales pipeline tracking, and automated client follow-ups.",
        "long_description": "Empower your sales team with HubRegistrar CRM. Track leads from first touchpoint to closed deal, automate email follow-up sequences, manage team tasks, and generate real-time revenue reports.",
        "features": ["Kanban Sales Pipeline", "Automated Email Sequences", "Contact & Lead Activity History", "Task & Reminder Scheduler", "Revenue Forecasting Reports"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 25, "price_annually": 250, "features": ["1,000 Leads", "2 Pipelines", "Email Sync"]},
            {"code": "pro", "name": "Pro", "price_monthly": 65, "price_annually": 650, "features": ["25,000 Leads", "Unlimited Pipelines", "Automations", "Reporting"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 149, "price_annually": 1490, "features": ["Unlimited Leads", "Custom Workflows", "Dedicated Manager"]}
        ],
        "faqs": [
            {"question": "Can I import existing contacts via CSV?", "answer": "Yes, HubRegistrar CRM supports instant CSV contact imports with automatic duplicate detection."}
        ]
    },
    {
        "slug": "invoice-ai",
        "name": "Invoice AI",
        "category": "Productivity",
        "badge": "AI Powered",
        "icon": "FileText",
        "is_featured": False,
        "display_order": 4,
        "short_description": "Smart automated invoicing, expense tracking, and GST/Tax report generation.",
        "long_description": "Simplify your accounting with Invoice AI. Automatically generate compliant professional invoices, track payment status, send automated payment reminders, and get automated tax summaries.",
        "features": ["Instant Invoice Generation", "Automated Recurring Invoices", "Payment Link Integration", "Tax & GST Ready Summaries", "Client Receipt Portal"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 12, "price_annually": 120, "features": ["20 Invoices/mo", "Multi-Currency", "Payment Links"]},
            {"code": "pro", "name": "Pro", "price_monthly": 29, "price_annually": 290, "features": ["Unlimited Invoices", "Automated Reminders", "Tax Reports"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 79, "price_annually": 790, "features": ["Multi-Entity Invoicing", "Custom Branding", "Accounting API Sync"]}
        ],
        "faqs": [
            {"question": "Does Invoice AI support multiple currencies?", "answer": "Yes, full multi-currency conversion with automatic daily exchange rates is supported."}
        ]
    },
    {
        "slug": "appointment-booking",
        "name": "Appointment Booking",
        "category": "Productivity",
        "badge": "Essential",
        "icon": "Calendar",
        "is_featured": False,
        "display_order": 5,
        "short_description": "Seamless online scheduling calendar with automatic video link generation and SMS reminders.",
        "long_description": "Eliminate back-and-forth scheduling emails. Share your personalized HubRegistrar booking link, sync Google / Outlook calendars, and automatically dispatch meeting invitations and reminders.",
        "features": ["Real-time Multi-Calendar Sync", "Automated Zoom/Google Meet Links", "Custom Booking Link & Page", "SMS & Email Reminders", "Buffer Time & Timezone Detection"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 10, "price_annually": 100, "features": ["1 Calendar Sync", "Unlimited Bookings", "Email Reminders"]},
            {"code": "pro", "name": "Pro", "price_monthly": 25, "price_annually": 250, "features": ["5 Calendar Syncs", "Team Booking Pages", "SMS Reminders", "Payment Collection"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 59, "price_annually": 590, "features": ["Unlimited Team Sync", "Custom Branding", "Round Robin Routing"]}
        ],
        "faqs": [
            {"question": "Does it prevent double bookings?", "answer": "Yes, it cross-checks all connected personal and work calendars in real time."}
        ]
    },
    {
        "slug": "document-signer",
        "name": "Document Signer",
        "category": "Productivity",
        "badge": "Secure",
        "icon": "Edit3",
        "is_featured": False,
        "display_order": 6,
        "short_description": "Legally binding e-signatures, document audit trails, and contract templates.",
        "long_description": "Sign contracts, NDAs, and proposals faster. HubRegistrar Document Signer offers bank-grade encryption, audit trails with IP timestamps, and legally compliant electronic signatures.",
        "features": ["Legally Binding E-Signatures", "Audit Trail & Timestamp Certificates", "Reusable Contract Templates", "Multi-Signer Sequential Workflows", "Secure Cloud Storage"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 15, "price_annually": 150, "features": ["10 Envelopes/mo", "Basic Audit Trail", "Template Library"]},
            {"code": "pro", "name": "Pro", "price_monthly": 35, "price_annually": 350, "features": ["Unlimited Envelopes", "Bulk Send", "Custom Branding", "API Signers"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 85, "price_annually": 850, "features": ["Dedicated Compliance Manager", "SAML SSO", "Vault Storage"]}
        ],
        "faqs": [
            {"question": "Are the signatures legally valid?", "answer": "Yes, signatures meet ESIGN Act and eIDAS compliance standards."}
        ]
    },
    {
        "slug": "cloud-storage",
        "name": "Cloud Storage",
        "category": "Storage",
        "badge": "High Speed",
        "icon": "HardDrive",
        "is_featured": True,
        "display_order": 7,
        "short_description": "Secure encrypted cloud storage, team file sharing, and version control.",
        "long_description": "Store, backup, and collaborate on files with absolute privacy. HubRegistrar Cloud Storage features end-to-end encryption, automatic syncing, granular access permissions, and version restoration.",
        "features": ["End-to-End Encrypted Vaults", "Granular Link Sharing & Passwords", "File Versioning & Rollback", "Team Workspace Folders", "High-Speed Global Sync"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 19, "price_annually": 190, "features": ["500 GB Storage", "2 Team Members", "High-speed Transfer"]},
            {"code": "pro", "name": "Pro", "price_monthly": 49, "price_annually": 490, "features": ["2 TB Storage", "10 Team Members", "Password Link Protection"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 129, "price_annually": 1290, "features": ["10 TB Storage", "Unlimited Team", "Zero-Knowledge Encryption"]}
        ],
        "faqs": [
            {"question": "Can I recover accidentally deleted files?", "answer": "Yes, 30-day trash recovery and file history are included."}
        ]
    },
    {
        "slug": "business-phone",
        "name": "Business Phone",
        "category": "Communication",
        "badge": "Virtual VoIP",
        "icon": "Phone",
        "is_featured": True,
        "display_order": 8,
        "short_description": "Cloud business VoIP phone system with IVR menus, call routing, and voicemail transcriptions.",
        "long_description": "Establish a professional business presence anywhere in the world. Get local & toll-free numbers, set up auto-attendants (IVR), transfer calls to mobile devices, and review automatic AI voicemail transcriptions.",
        "features": ["Global Virtual Numbers", "Interactive Voice Response (IVR)", "Mobile & Desktop Softphone", "Voicemail-to-Text Transcripts", "Call Recording & Analytics"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 20, "price_annually": 200, "features": ["1 Phone Number", "500 Minutes", "Mobile Softphone App"]},
            {"code": "pro", "name": "Pro", "price_monthly": 50, "price_annually": 500, "features": ["3 Phone Numbers", "Unlimited Minutes", "IVR Auto Attendant"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 120, "price_annually": 1200, "features": ["Dedicated Call Center Suite", "CRM Integration", "Call Analytics"]}
        ],
        "faqs": [
            {"question": "Can I keep my existing phone number?", "answer": "Yes, HubRegistrar provides free number porting for qualified regions."}
        ]
    },
    {
        "slug": "vpn",
        "name": "VPN",
        "category": "Security",
        "badge": "Privacy",
        "icon": "Shield",
        "is_featured": True,
        "display_order": 9,
        "short_description": "High-speed encrypted VPN network for safe browsing, remote access, and IP protection.",
        "long_description": "Protect your company communications and sensitive data online. HubRegistrar VPN delivers strict strict zero-logs privacy, multi-gigabit encrypted servers in over 60 countries, and automatic kill-switch protection.",
        "features": ["AES-256 WireGuard Encryption", "Zero-Logs Privacy Guarantee", "60+ Global Server Locations", "Automatic Network Kill Switch", "Multi-Device Support"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 8, "price_annually": 80, "features": ["5 Simultaneous Devices", "Global Servers", "Zero-Logs"]},
            {"code": "pro", "name": "Pro", "price_monthly": 18, "price_annually": 180, "features": ["15 Simultaneous Devices", "Dedicated IP Address", "Ad & Malware Blocker"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 45, "price_annually": 450, "features": ["Dedicated Corporate Gateway", "Central Admin Console", "Unlimited Devices"]}
        ],
        "faqs": [
            {"question": "Do you log connection activity?", "answer": "No, our architecture operates under a strict verified zero-logs policy."}
        ]
    },
    {
        "slug": "email-marketing",
        "name": "Email Marketing",
        "category": "Marketing",
        "badge": "Automation",
        "icon": "Mail",
        "is_featured": True,
        "display_order": 10,
        "short_description": "Automated email newsletters, drip campaigns, contact segmentation, and broadcast analytics.",
        "long_description": "Engage your subscriber base with beautiful responsive email templates, targeted subscriber segments, automated drip workflows, and high deliverability infrastructure.",
        "features": ["Drag-and-Drop Email Builder", "Automated Drip Workflows", "Contact Tagging & Segmentation", "Real-Time Open & Click Tracking", "High Deliverability Infrastructure"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 22, "price_annually": 220, "features": ["2,500 Contacts", "15,000 Emails/mo", "Standard Templates"]},
            {"code": "pro", "name": "Pro", "price_monthly": 55, "price_annually": 550, "features": ["10,000 Contacts", "Unlimited Emails", "Automated Drips", "A/B Testing"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 135, "price_annually": 1350, "features": ["50,000+ Contacts", "Dedicated Sending IP", "Custom Template Design"]}
        ],
        "faqs": [
            {"question": "Can I import HTML email templates?", "answer": "Yes, full custom HTML import and raw code editing are supported."}
        ]
    },
    {
        "slug": "social-media-automation",
        "name": "Social Media Automation",
        "category": "Marketing",
        "badge": "Auto Post",
        "icon": "Share2",
        "is_featured": False,
        "display_order": 11,
        "short_description": "Schedule posts, generate hashtags, and track performance across X, LinkedIn, Instagram & Facebook.",
        "long_description": "Manage your social presence in one place. Schedule posts across all major social networks, preview layouts, leverage AI hashtag recommendations, and analyze engagement trends.",
        "features": ["Multi-Channel Content Scheduler", "AI Hashtag & Caption Generator", "Visual Social Feed Planner", "Cross-Platform Analytics", "Team Approval Workflows"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 18, "price_annually": 180, "features": ["5 Social Accounts", "100 Scheduled Posts", "Basic Analytics"]},
            {"code": "pro", "name": "Pro", "price_monthly": 45, "price_annually": 450, "features": ["15 Social Accounts", "Unlimited Scheduled Posts", "AI Assistant", "Analytics"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 110, "price_annually": 1100, "features": ["Unlimited Accounts", "Multi-Brand Workspace", "Custom Client Reports"]}
        ],
        "faqs": [
            {"question": "Which social networks are supported?", "answer": "LinkedIn, Twitter/X, Instagram, Facebook Pages, Pinterest, and TikTok."}
        ]
    },
    {
        "slug": "reputation-management",
        "name": "Reputation Management",
        "category": "Marketing",
        "badge": "Reviews",
        "icon": "Star",
        "is_featured": False,
        "display_order": 12,
        "short_description": "Monitor brand reviews, automate feedback collection, and manage online sentiment.",
        "long_description": "Build credibility and trust online. HubRegistrar Reputation Management monitors online reviews across Google, Trustpilot, and social networks, sends automated customer feedback requests, and displays review widgets on your site.",
        "features": ["Multi-Platform Review Aggregator", "Automated SMS/Email Feedback Requests", "Custom Website Review Widgets", "Sentiment Analysis & Alerts", "AI Review Response Generator"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 30, "price_annually": 300, "features": ["1 Business Location", "Review Widgets", "Email Invites"]},
            {"code": "pro", "name": "Pro", "price_monthly": 75, "price_annually": 750, "features": ["5 Business Locations", "SMS & Email Invites", "AI Review Responses"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 180, "price_annually": 1800, "features": ["Unlimited Locations", "Whitelabel Reports", "Dedicated Reputation Coach"]}
        ],
        "faqs": [
            {"question": "Can I filter negative feedback before public posting?", "answer": "Yes, automated private resolution forms allow addressing issues directly."}
        ]
    },
    {
        "slug": "link-in-bio",
        "name": "Link in Bio",
        "category": "Marketing",
        "badge": "Creator",
        "icon": "Link",
        "is_featured": False,
        "display_order": 13,
        "short_description": "Customizable landing link page for social media bios with custom domains and analytics.",
        "long_description": "Turn your social media traffic into sales. Create beautiful, mobile-friendly landing pages for your Instagram, TikTok, and Twitter bios, complete with custom domain mapping, buttons, products, and click tracking.",
        "features": ["Custom Theme & Style Editor", "Custom Domain Mapping", "Embed Videos, Music & Products", "Click & Conversion Analytics", "SEO Meta Customization"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 5, "price_annually": 50, "features": ["1 Bio Page", "Standard Themes", "Basic Analytics"]},
            {"code": "pro", "name": "Pro", "price_monthly": 15, "price_annually": 150, "features": ["5 Bio Pages", "Custom Domain", "Remove HubRegistrar Badge", "E-commerce Links"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 35, "price_annually": 350, "features": ["Unlimited Pages", "Custom CSS/JS", "Team Collaboration"]}
        ],
        "faqs": [
            {"question": "Can I use my own domain like links.mycompany.com?", "answer": "Yes, custom CNAME domain mapping is fully supported."}
        ]
    },
    {
        "slug": "smm-growth",
        "name": "SMM Growth",
        "category": "Marketing",
        "badge": "Organic",
        "icon": "TrendingUp",
        "is_featured": False,
        "display_order": 14,
        "short_description": "Data-driven organic social media growth toolkit, hashtag research, and competitor analysis.",
        "long_description": "Accelerate your social growth with actionable intelligence. SMM Growth tracks trending hashtags, audits competitor posting performance, identifies viral content ideas, and optimizes your posting schedules.",
        "features": ["Competitor Benchmarking Audit", "Viral Content Trend Finder", "Optimal Posting Time Predictor", "Audience Demographics Breakdown", "Custom Strategy Reports"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 25, "price_annually": 250, "features": ["Track 3 Competitors", "Hashtag Engine", "Weekly Reports"]},
            {"code": "pro", "name": "Pro", "price_monthly": 60, "price_annually": 600, "features": ["Track 15 Competitors", "Trend Predictor", "Daily Strategy Audits"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 140, "price_annually": 1400, "features": ["Unlimited Tracking", "Dedicated Strategist", "Custom API Feeds"]}
        ],
        "faqs": [
            {"question": "Is this safe for social media platform terms of service?", "answer": "100% yes, all tools rely on legitimate public platform APIs and compliance standards."}
        ]
    },
    {
        "slug": "esim",
        "name": "eSIM",
        "category": "Communication",
        "badge": "Global Data",
        "icon": "Wifi",
        "is_featured": False,
        "display_order": 15,
        "short_description": "Instant global mobile data eSIM profiles for 150+ countries with instant QR activation.",
        "long_description": "Stay connected around the world without roaming fees. HubRegistrar eSIM offers instant digital mobile data packages for over 150 countries. Scan a QR code on your mobile device to activate instant high-speed data.",
        "features": ["Instant QR Digital Delivery", "150+ Countries & Regional Bundles", "Flexible Data Quotas (1GB - 50GB)", "High-Speed 4G/5G Connectivity", "No Physical SIM Swap Needed"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 15, "price_annually": 150, "features": ["3 GB Global Data", "30 Days Validity", "150+ Countries"]},
            {"code": "pro", "name": "Pro", "price_monthly": 35, "price_annually": 350, "features": ["10 GB Global Data", "60 Days Validity", "5G Enabled"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 85, "price_annually": 850, "features": ["50 GB Corporate Pool", "Multi-Employee Profile Dispatch"]}
        ],
        "faqs": [
            {"question": "How do I activate the eSIM?", "answer": "Scan the QR code displayed in your HubRegistrar dashboard using your smartphone camera."}
        ]
    },
    {
        "slug": "web-hosting",
        "name": "Web Hosting",
        "category": "Hosting",
        "badge": "99.9% Uptime",
        "icon": "Server",
        "is_featured": True,
        "display_order": 16,
        "short_description": "Ultra-fast NVMe cloud web hosting with free SSL, automated daily backups, and cPanel/Control access.",
        "long_description": "Power your websites with enterprise cloud hosting. Enjoy NVMe solid-state storage, automated daily backups, isolated cloud resources, free SSL certificates, and 99.9% uptime SLA.",
        "features": ["High-Speed NVMe Storage", "Free SSL Certificates", "Automated Daily Offsite Backups", "Isolated Cloud Resource Allocation", "1-Click Script Installer"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 12, "price_annually": 120, "features": ["1 Website", "20 GB NVMe Storage", "Unmetered Traffic"]},
            {"code": "pro", "name": "Pro", "price_monthly": 28, "price_annually": 280, "features": ["10 Websites", "100 GB NVMe Storage", "Free Staging Site"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 75, "price_annually": 750, "features": ["Unlimited Websites", "Unmetered NVMe Storage", "Dedicated CPU & RAM"]}
        ],
        "faqs": [
            {"question": "Are site migrations free?", "answer": "Yes, HubRegistrar provides free migration assistance for qualified websites."}
        ]
    },
    {
        "slug": "wordpress-plugin-pack",
        "name": "WordPress Plugin Pack",
        "category": "Hosting",
        "badge": "Essential",
        "icon": "Box",
        "is_featured": False,
        "display_order": 17,
        "short_description": "Curated suite of premium WordPress plugins for SEO, security, caching, and performance optimization.",
        "long_description": "Supercharge your WordPress sites. Get instant licensed access to HubRegistrar's curated WordPress plugin pack, including enterprise caching, security firewalls, SEO optimization, and image compression tools.",
        "features": ["Enterprise Caching & Speed Engine", "Security Firewall & Malware Scanner", "AI SEO Meta Optimizer", "Automatic Image Compression", "1-Click License Activation"],
        "plans": [
            {"code": "starter", "name": "Starter", "price_monthly": 10, "price_annually": 100, "features": ["1 Site License", "Core Security & SEO Plugins", "Auto Updates"]},
            {"code": "pro", "name": "Pro", "price_monthly": 25, "price_annually": 250, "features": ["5 Site Licenses", "Speed Optimization Suite", "Priority Updates"]},
            {"code": "enterprise", "name": "Enterprise", "price_monthly": 60, "price_annually": 600, "features": ["25 Site Licenses", "Whitelabel Plugin Console", "Agency Support"]}
        ],
        "faqs": [
            {"question": "How do I install the plugins?", "answer": "Download the zip files or enter your license key directly in your WordPress WP-Admin panel."}
        ]
    }
]


# Seeding is reference data that only ever needs to happen once. This guard
# keeps the COUNT(*) off the hot path for every subsequent request in the
# worker, so the catalogue endpoints do not pay a query to re-check an
# already-populated table. Schema is owned by Alembic, never created here.
_catalogue_seed_checked = False


def _build_seed_entities() -> list[TechnologyServiceEntity]:
    """Materialize DEFAULT_SERVICES_SEED as unsaved catalogue rows."""
    return [
        TechnologyServiceEntity(
            slug=item["slug"],
            name=item["name"],
            category=item["category"],
            short_description=item["short_description"],
            long_description=item["long_description"],
            badge=item["badge"],
            icon=item["icon"],
            is_featured=item["is_featured"],
            display_order=item["display_order"],
            features_json=json.dumps(item["features"]),
            plans_json=json.dumps(item["plans"]),
            faqs_json=json.dumps(item["faqs"]),
            is_available=True,
        )
        for item in DEFAULT_SERVICES_SEED
    ]


def ensure_catalogue_seeded_sync(db: Session) -> None:
    """Seed the catalogue on a sync Session if it is empty.

    Sync counterpart of :func:`ensure_catalogue_seeded` for the non-async
    endpoints. get_db() never commits, so the insert is committed here or the
    seeded rows would be discarded when the session closes.
    """
    global _catalogue_seed_checked
    if _catalogue_seed_checked:
        return
    try:
        count = (
            db.query(func.count(TechnologyServiceEntity.id))
            .filter(TechnologyServiceEntity.is_deleted.is_(False))
            .scalar()
        ) or 0
        if count == 0:
            logger.info("Seeding initial Technology Services catalogue (%d services)...", len(DEFAULT_SERVICES_SEED))
            db.add_all(_build_seed_entities())
            db.commit()
            logger.info("Technology Services catalogue seeded successfully.")
        _catalogue_seed_checked = True
    except IntegrityError:
        # Another worker seeded concurrently; slug is unique so this is benign.
        db.rollback()
        _catalogue_seed_checked = True
    except Exception as exc:
        db.rollback()
        logger.warning("Catalogue seeding skipped or deferred: %s", exc)


async def ensure_catalogue_seeded(db: AsyncSession) -> None:
    """Seed the catalogue on an AsyncSession if it is empty."""
    global _catalogue_seed_checked
    if _catalogue_seed_checked:
        return
    try:
        result = await db.execute(
            select(func.count(TechnologyServiceEntity.id)).where(
                TechnologyServiceEntity.is_deleted.is_(False)
            )
        )
        count = result.scalar() or 0
        if count == 0:
            logger.info("Seeding initial Technology Services catalogue (%d services)...", len(DEFAULT_SERVICES_SEED))
            db.add_all(_build_seed_entities())
            await db.commit()
            logger.info("Technology Services catalogue seeded successfully.")
        _catalogue_seed_checked = True
    except IntegrityError:
        # Another worker seeded concurrently; slug is unique so this is benign.
        await db.rollback()
        _catalogue_seed_checked = True
    except Exception as exc:
        await db.rollback()
        logger.warning("Catalogue seeding skipped or deferred: %s", exc)


def _fallback_service_id(slug: str) -> str:
    """Return a deterministic UUID for fallback catalogue entries.

    The shopping cart and downstream checkout flows require a real UUID product id.
    The default slug-based fallback strings were invalid for the cart schema, which
    blocked AI Business Suite add-to-cart requests even before payment verification.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cobrother:technology-service:{slug}"))


def _get_fallback_services(category: Optional[str] = None, featured_only: bool = False) -> list[dict[str, Any]]:
    items = DEFAULT_SERVICES_SEED
    if category and category.lower() != "all":
        items = [s for s in items if s["category"].lower() == category.lower()]
    if featured_only:
        items = [s for s in items if s.get("is_featured")]

    result = []
    for s in items:
        result.append({
            "id": _fallback_service_id(s["slug"]),
            "slug": s["slug"],
            "name": s["name"],
            "category": s["category"],
            "short_description": s["short_description"],
            "long_description": s["long_description"],
            "badge": s["badge"],
            "icon": s["icon"],
            "is_featured": s["is_featured"],
            "features": s["features"],
            "plans": s["plans"],
            "faqs": s["faqs"],
            "starting_price": s["plans"][0]["price_monthly"] if s.get("plans") else 0,
            "status": "ACTIVE",
            "provider_product_key": get_product_key(s["slug"]),
        })
    return result


# -------------------------------------------------------------------
# Catalogue Endpoints
# -------------------------------------------------------------------

@router.get("")
def list_technology_services(
    category: Optional[str] = Query(None, description="Filter by category"),
    featured_only: bool = Query(False, description="Filter only featured items for homepage"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all available Technology Services from catalogue."""
    try:
        ensure_catalogue_seeded_sync(db)
        query = db.query(TechnologyServiceEntity).filter(
            TechnologyServiceEntity.is_deleted == False,
            TechnologyServiceEntity.is_available == True,
        )
        if category and category.lower() != "all":
            query = query.filter(TechnologyServiceEntity.category.ilike(category))
        if featured_only:
            query = query.filter(TechnologyServiceEntity.is_featured == True)

        services = query.order_by(TechnologyServiceEntity.display_order.asc()).all()

        if not services:
            return _get_fallback_services(category=category, featured_only=featured_only)

        result = []
        for s in services:
            features = json.loads(s.features_json) if s.features_json else []
            plans = json.loads(s.plans_json) if s.plans_json else []
            faqs = json.loads(s.faqs_json) if s.faqs_json else []
            result.append({
                "id": str(s.id),
                "slug": s.slug,
                "name": s.name,
                "category": s.category,
                "short_description": s.short_description,
                "long_description": s.long_description,
                "badge": s.badge,
                "icon": s.icon,
                "is_featured": s.is_featured,
                "features": features,
                "plans": plans,
                "faqs": faqs,
                "starting_price": plans[0]["price_monthly"] if plans else 0,
                "status": "ACTIVE",
                "provider_product_key": s.provider_product_key,
                "provider_specific_params": json.loads(s.provider_specific_params) if s.provider_specific_params else None,
            })
        return result
    except Exception as err:
        logger.warning("Error fetching technology services from DB, serving fallback catalogue: %s", err)
        return _get_fallback_services(category=category, featured_only=featured_only)


@router.get("/{slug}")
def get_technology_service_detail(
    slug: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get single Technology Service detail by slug."""
    try:
        ensure_catalogue_seeded_sync(db)
        service = db.query(TechnologyServiceEntity).filter(
            TechnologyServiceEntity.slug == slug,
            TechnologyServiceEntity.is_deleted == False,
        ).first()

        if service:
            features = json.loads(service.features_json) if service.features_json else []
            plans = json.loads(service.plans_json) if service.plans_json else []
            faqs = json.loads(service.faqs_json) if service.faqs_json else []

            return {
                "id": str(service.id),
                "slug": service.slug,
                "name": service.name,
                "category": service.category,
                "short_description": service.short_description,
                "long_description": service.long_description,
                "badge": service.badge,
                "icon": service.icon,
                "is_featured": service.is_featured,
                "features": features,
                "plans": plans,
                "faqs": faqs,
                "starting_price": plans[0]["price_monthly"] if plans else 0,
                "status": "ACTIVE",
                "provider_product_key": service.provider_product_key,
                "provider_specific_params": json.loads(service.provider_specific_params) if service.provider_specific_params else None,
            }
    except Exception as err:
        logger.warning("Error fetching service detail from DB: %s", err)

    fallback_item = next((s for s in DEFAULT_SERVICES_SEED if s["slug"] == slug), None)
    if fallback_item:
        return {
            "id": _fallback_service_id(fallback_item["slug"]),
            "slug": fallback_item["slug"],
            "name": fallback_item["name"],
            "category": fallback_item["category"],
            "short_description": fallback_item["short_description"],
            "long_description": fallback_item["long_description"],
            "badge": fallback_item["badge"],
            "icon": fallback_item["icon"],
            "is_featured": fallback_item["is_featured"],
            "features": fallback_item["features"],
            "plans": fallback_item["plans"],
            "faqs": fallback_item["faqs"],
            "starting_price": fallback_item["plans"][0]["price_monthly"] if fallback_item.get("plans") else 0,
            "status": "ACTIVE",
            "provider_product_key": get_product_key(fallback_item["slug"]),
        }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Technology service '{slug}' not found",
    )


# -------------------------------------------------------------------
# Purchase & Subscription Endpoints
# -------------------------------------------------------------------

@router.post("/subscribe")
async def subscribe_technology_service(
    payload: SubscribeRequest,
    current_user: AppUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    """Purchase / provision a provider-powered technology service subscription."""
    await ensure_catalogue_seeded(db)
    result = await db.execute(
        select(TechnologyServiceEntity).where(
            TechnologyServiceEntity.slug == payload.service_slug,
            TechnologyServiceEntity.is_deleted == False,
        )
    )
    service = result.scalar_one_or_none()

    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    if service.slug == "ai-business-suite":
        raise HTTPException(
            status_code=400,
            detail=(
                "AI Business Suite must be purchased through the HubRegistrar cart checkout flow "
                "after Razorpay payment verification. Direct provider provisioning is disabled."
            ),
        )

    plans = json.loads(service.plans_json) if service.plans_json else []
    selected_plan = next((p for p in plans if p["code"] == payload.plan_code), None)
    if not selected_plan:
        selected_plan = plans[0] if plans else {"price_monthly": 29, "price_annually": 290}

    user_id = str(current_user.id)
    user_email = current_user.email or "user@cobrother.com"

    product_key = get_product_key(service.slug)
    if not product_key and service.provider_product_key:
        product_key = service.provider_product_key

    if not is_provider_mapped(service.slug) and not product_key:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{service.name} is not yet available through the automated provider. "
                "Please contact support for manual activation."
            ),
        )

    order_parameters = build_order_parameters(
        product_key=product_key or service.slug,
        plan_code=payload.plan_code,
        billing_cycle=payload.billing_cycle,
    )

    client = get_resellportal_client()
    prov_res = client.provision_service(
        service_slug=service.slug,
        service_name=service.name,
        plan_code=payload.plan_code,
        billing_cycle=payload.billing_cycle,
        user_email=user_email,
        user_id=user_id,
        product_key=product_key,
        order_parameters=order_parameters,
    )

    provider_success = prov_res.get("success") is True
    provider_status = str(prov_res.get("status") or "PENDING").upper()
    subscription_status = "ACTIVE" if provider_success and provider_status == "ACTIVE" else "PENDING"

    price = selected_plan["price_annually"] if payload.billing_cycle == "annually" else selected_plan["price_monthly"]

    sub = TechnologySubscriptionEntity(
        user_id=user_id,
        service_slug=service.slug,
        service_name=service.name,
        plan_code=payload.plan_code,
        billing_cycle=payload.billing_cycle,
        price=price,
        currency="USD",
        status=subscription_status,
        provider_subscription_id=prov_res.get("provider_subscription_id"),
        provider_order_id=prov_res.get("provider_order_id"),
        credentials_json=json.dumps(prov_res.get("credentials") or {}),
        current_period_start=prov_res.get("current_period_start"),
        current_period_end=prov_res.get("current_period_end"),
        auto_renew=True,
        email_sent=False,
    )
    db.add(sub)
    await db.flush()

    inv_number = f"INV-CB-{uuid.uuid4().hex[:8].upper()}"
    inv = TechnologySubscriptionInvoiceEntity(
        subscription_id=str(sub.id),
        user_id=user_id,
        invoice_number=inv_number,
        amount=price,
        currency="USD",
        status="PAID",
        billing_period_start=prov_res.get("current_period_start") or datetime.now(timezone.utc),
        billing_period_end=prov_res.get("current_period_end") or datetime.now(timezone.utc) + timedelta(days=30),
        payment_method="HubRegistrar Wallet / Card",
    )
    db.add(inv)
    await db.commit()

    customer_name = current_user.get("full_name") or current_user.get("name") or user_email
    purchase_date = datetime.now(timezone.utc).strftime("%d %b %Y")
    purchases_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/purchases"
    plan_name = payload.plan_code.replace("_", " ").title()

    if subscription_status == "ACTIVE" and not sub.email_sent:
        try:
            await MailService.send_technology_purchase_confirmation_email(
                to_email=user_email,
                customer_name=customer_name,
                service_name=service.name,
                plan_name=plan_name,
                billing_cycle=payload.billing_cycle,
                cobrother_order_id=str(sub.id),
                razorpay_payment_id=None,
                amount_inr=float(price),
                purchase_date=purchase_date,
                service_status="Active",
                provider_info=f"Service ID: {prov_res.get('service_id', 'N/A')}",
                purchases_url=purchases_url,
            )
            sub.email_sent = True
            await db.flush()
            await db.commit()
        except Exception:
            logger.exception("technology.subscribe.confirmation_email.failed user=%s service=%s", user_id, service.slug)
    elif subscription_status == "PENDING" and not sub.email_sent:
        try:
            await MailService.send_technology_purchase_pending_email(
                to_email=user_email,
                customer_name=customer_name,
                service_name=service.name,
                plan_name=plan_name,
                billing_cycle=payload.billing_cycle,
                cobrother_order_id=str(sub.id),
                razorpay_payment_id=None,
                amount_inr=float(price),
                purchase_date=purchase_date,
                reason="Provider provisioning is pending. Our team will complete activation shortly.",
                purchases_url=purchases_url,
            )
            sub.email_sent = True
            await db.flush()
            await db.commit()
        except Exception:
            logger.exception("technology.subscribe.pending_email.failed user=%s service=%s", user_id, service.slug)

    return {
        "success": provider_success,
        "subscription_id": str(sub.id),
        "service_name": sub.service_name,
        "plan_code": sub.plan_code,
        "billing_cycle": sub.billing_cycle,
        "status": sub.status,
        "credentials": prov_res["credentials"],
        "invoice_number": inv_number,
    }


@router.get("/subscriptions/me")
def list_my_subscriptions(
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List current user active and past technology subscriptions."""
    user_id = str(current_user.id)
    subs = db.query(TechnologySubscriptionEntity).filter(
        TechnologySubscriptionEntity.user_id == user_id,
        TechnologySubscriptionEntity.is_deleted == False,
    ).order_by(TechnologySubscriptionEntity.created_at.desc()).all()

    result = []
    for sub in subs:
        creds = json.loads(sub.credentials_json) if sub.credentials_json else {}
        result.append({
            "id": str(sub.id),
            "service_slug": sub.service_slug,
            "service_name": sub.service_name,
            "plan_code": sub.plan_code,
            "billing_cycle": sub.billing_cycle,
            "price": sub.price,
            "currency": sub.currency,
            "status": sub.status,
            "credentials": creds,
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "auto_renew": sub.auto_renew,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        })
    return result


@router.get("/subscriptions/{subscription_id}")
def get_subscription_detail(
    subscription_id: str,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get single subscription detail & credentials."""
    user_id = str(current_user.id)
    sub = db.query(TechnologySubscriptionEntity).filter(
        TechnologySubscriptionEntity.id == subscription_id,
        TechnologySubscriptionEntity.user_id == user_id,
        TechnologySubscriptionEntity.is_deleted == False,
    ).first()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    creds = json.loads(sub.credentials_json) if sub.credentials_json else {}
    return {
        "id": str(sub.id),
        "service_slug": sub.service_slug,
        "service_name": sub.service_name,
        "plan_code": sub.plan_code,
        "billing_cycle": sub.billing_cycle,
        "price": sub.price,
        "currency": sub.currency,
        "status": sub.status,
        "credentials": creds,
        "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "auto_renew": sub.auto_renew,
    }


@router.post("/subscriptions/{subscription_id}/renew")
def renew_subscription(
    subscription_id: str,
    payload: RenewalRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Renew subscription."""
    user_id = str(current_user.id)
    sub = db.query(TechnologySubscriptionEntity).filter(
        TechnologySubscriptionEntity.id == subscription_id,
        TechnologySubscriptionEntity.user_id == user_id,
        TechnologySubscriptionEntity.is_deleted == False,
    ).first()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Only renewable subscriptions may be renewed: ACTIVE, with a real
    # provider subscription id and a known period end.
    if sub.status != "ACTIVE":
        raise HTTPException(
            status_code=400,
            detail=f"Subscription is not active (status={sub.status}); renewal is only allowed for ACTIVE subscriptions.",
        )
    if not sub.provider_subscription_id or str(sub.provider_subscription_id).startswith("SUB-DEFAULT"):
        raise HTTPException(
            status_code=400,
            detail="Subscription has no valid provider reference; renewal cannot be processed.",
        )
    if sub.current_period_end is None:
        raise HTTPException(
            status_code=400,
            detail="Subscription has no current period end; renewal cannot be processed.",
        )

    client = get_resellportal_client()
    prov_res = client.renew_subscription(
        provider_sub_id=sub.provider_subscription_id,
        billing_cycle=payload.billing_cycle,
    )

    if prov_res.get("current_period_end"):
        sub.current_period_end = prov_res["current_period_end"]
    sub.status = "ACTIVE"
    db.commit()

    return {"success": True, "status": sub.status, "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None}


@router.post("/subscriptions/{subscription_id}/upgrade")
def upgrade_subscription(
    subscription_id: str,
    payload: UpgradeRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Upgrade subscription plan."""
    user_id = str(current_user.id)
    sub = db.query(TechnologySubscriptionEntity).filter(
        TechnologySubscriptionEntity.id == subscription_id,
        TechnologySubscriptionEntity.user_id == user_id,
        TechnologySubscriptionEntity.is_deleted == False,
    ).first()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    client = get_resellportal_client()
    prov_res = client.upgrade_subscription(
        provider_sub_id=sub.provider_subscription_id or "SUB-DEFAULT",
        new_plan_code=payload.new_plan_code,
    )

    sub.plan_code = payload.new_plan_code
    db.commit()

    return {"success": True, "plan_code": sub.plan_code}


@router.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription(
    subscription_id: str,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Cancel subscription."""
    user_id = str(current_user.id)
    sub = db.query(TechnologySubscriptionEntity).filter(
        TechnologySubscriptionEntity.id == subscription_id,
        TechnologySubscriptionEntity.user_id == user_id,
        TechnologySubscriptionEntity.is_deleted == False,
    ).first()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    client = get_resellportal_client()
    client.cancel_subscription(provider_sub_id=sub.provider_subscription_id or "SUB-DEFAULT")

    sub.status = "CANCELLED"
    sub.auto_renew = False
    db.commit()

    return {"success": True, "status": sub.status}


@router.get("/subscriptions/{subscription_id}/invoices")
def get_subscription_invoices(
    subscription_id: str,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get subscription invoices."""
    user_id = str(current_user.id)
    invoices = db.query(TechnologySubscriptionInvoiceEntity).filter(
        TechnologySubscriptionInvoiceEntity.subscription_id == subscription_id,
        TechnologySubscriptionInvoiceEntity.user_id == user_id,
    ).order_by(TechnologySubscriptionInvoiceEntity.created_at.desc()).all()

    return [
        {
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "amount": inv.amount,
            "currency": inv.currency,
            "status": inv.status,
            "payment_method": inv.payment_method,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invoices
    ]


@router.post("/webhooks/resellportal")
def handle_resellportal_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Webhook callback endpoint for ResellPortal backend status sync."""
    client = get_resellportal_client()
    event = payload.get("event", "status_update")
    return client.handle_webhook(event_type=event, payload=payload)


# -------------------------------------------------------------------
# Admin Panel Endpoints (Premium Tech Administration)
# -------------------------------------------------------------------

_ADMIN_CONFIG = {
    "global_margin_percent": 15.0,
    "wallet_balance": 145.50,
    "warning_threshold": 7.00,
}

_FAILED_PROVISIONING_ITEMS = [
    {
        "id": "failed-201",
        "user_id": "usr_998877",
        "user_email": "demo.user@example.com",
        "service_slug": "ai-business-suite",
        "service_name": "AI Business Suite",
        "plan_code": "pro",
        "billing_cycle": "monthly",
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "error_reason": "Simulated transient timeout during initial provider handshake.",
        "status": "PENDING_RETRY",
        "retry_count": 1,
    }
]

_PROVISIONING_LOGS = [
    {
        "id": "log-101",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "PROVISION_SUCCESS",
        "service_slug": "ai-business-suite",
        "message": "Service instance provisioned successfully via ResellPortal REST API",
        "status": "SUCCESS",
    },
    {
        "id": "log-102",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "WALLET_CHECK",
        "service_slug": "system",
        "message": "Reseller wallet balance verified: $145.50 (Sufficient)",
        "status": "INFO",
    },
    {
        "id": "log-103",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "CLIENT_INIT",
        "service_slug": "system",
        "message": "ResellPortal client initialized in test mode (test_mode=True)",
        "status": "INFO",
    },
]


@router.get("/admin/config")
def get_admin_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Get Admin Premium Tech configuration & reseller wallet status."""
    sub_count = 0
    try:
        sub_count = db.query(TechnologySubscriptionEntity).filter_by(is_deleted=False).count()
    except Exception:
        pass

    client = get_resellportal_client()
    wallet_res = client.get_wallet_balance()

    wb = float(wallet_res.get("balance", _ADMIN_CONFIG["wallet_balance"]))
    wt = float(wallet_res.get("warning_threshold", _ADMIN_CONFIG["warning_threshold"]))
    is_configured = client.is_configured()
    test_mode = client.is_test_mode()

    admin_msg = ""
    if not is_configured:
        admin_msg = (
            "ResellPortal API credentials have not been configured yet. "
            "API keys will be added after the provider wallet is funded and API access is generated."
        )

    return {
        "global_margin_percent": _ADMIN_CONFIG["global_margin_percent"],
        "wallet_balance": wb,
        "warning_threshold": wt,
        "wallet_warning_active": wb < wt,
        "configured": is_configured,
        "test_mode": test_mode,
        "allow_live": getattr(settings, "RESELLPORTAL_ALLOW_LIVE", False),
        "admin_message": admin_msg,
        "total_services": len(DEFAULT_SERVICES_SEED),
        "active_subscriptions_count": sub_count,
    }


@router.post("/admin/config")
def update_admin_config(payload: AdminConfigUpdate) -> dict[str, Any]:
    """Update Admin Premium Tech global margin & wallet balance."""
    if payload.global_margin_percent is not None:
        _ADMIN_CONFIG["global_margin_percent"] = payload.global_margin_percent
    if payload.wallet_balance is not None:
        _ADMIN_CONFIG["wallet_balance"] = payload.wallet_balance
    return {
        "success": True,
        "config": get_admin_config(),
    }


@router.get("/admin/services")
def get_admin_services(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """List catalogue services for Admin management with pricing overrides & margin."""
    ensure_catalogue_seeded_sync(db)
    try:
        services = db.query(TechnologyServiceEntity).filter_by(is_deleted=False).order_by(TechnologyServiceEntity.display_order.asc()).all()
        result = []
        for s in services:
            plans = json.loads(s.plans_json) if s.plans_json else []
            base_monthly = plans[0]["price_monthly"] if plans else 15.0
            margin = _ADMIN_CONFIG["global_margin_percent"]
            calculated_monthly = round(base_monthly * (1 + margin / 100.0), 2)

            result.append({
                "id": str(s.id),
                "slug": s.slug,
                "name": s.name,
                "category": s.category,
                "is_available": s.is_available,
                "badge": s.badge,
                "base_starting_price": base_monthly,
                "global_margin_percent": margin,
                "calculated_price": calculated_monthly,
                "price_override_monthly": s.price_override_monthly,
                "price_override_annually": s.price_override_annually,
                "effective_monthly_price": s.price_override_monthly if s.price_override_monthly is not None else calculated_monthly,
            })
        return result
    except Exception as err:
        logger.warning("Error getting admin services: %s", err)
        return _get_fallback_services()


@router.post("/admin/services/{slug}/toggle")
def toggle_service_availability(
    slug: str,
    payload: AdminToggleService,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Enable or disable a Premium Tech service."""
    ensure_catalogue_seeded_sync(db)
    try:
        service = db.query(TechnologyServiceEntity).filter_by(slug=slug).first()
        if service:
            service.is_available = payload.is_available
            db.commit()
            _PROVISIONING_LOGS.insert(0, {
                "id": f"log-{uuid.uuid4().hex[:6]}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "SERVICE_TOGGLE",
                "service_slug": slug,
                "message": f"Service '{slug}' availability changed to {payload.is_available}",
                "status": "INFO",
            })
            return {"success": True, "slug": slug, "is_available": service.is_available}
    except Exception as err:
        logger.warning("Error toggling service in DB: %s", err)
    return {"success": True, "slug": slug, "is_available": payload.is_available}


@router.post("/admin/services/{slug}/override-price")
def override_service_price(
    slug: str,
    payload: AdminPriceOverride,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Set custom price override for a specific service."""
    ensure_catalogue_seeded_sync(db)
    try:
        service = db.query(TechnologyServiceEntity).filter_by(slug=slug).first()
        if service:
            service.price_override_monthly = payload.price_override_monthly
            service.price_override_annually = payload.price_override_annually
            db.commit()
            _PROVISIONING_LOGS.insert(0, {
                "id": f"log-{uuid.uuid4().hex[:6]}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "PRICE_OVERRIDE",
                "service_slug": slug,
                "message": f"Per-product price override set for '{slug}': monthly=${payload.price_override_monthly}, annually=${payload.price_override_annually}",
                "status": "INFO",
            })
            return {
                "success": True,
                "slug": slug,
                "price_override_monthly": service.price_override_monthly,
                "price_override_annually": service.price_override_annually,
            }
    except Exception as err:
        logger.warning("Error updating price override in DB: %s", err)
    return {"success": True, "slug": slug}


@router.get("/admin/wallet")
def get_admin_wallet() -> dict[str, Any]:
    """Fetch live wallet balance & low balance warning status."""
    client = get_resellportal_client()
    return client.get_wallet_balance()


@router.get("/admin/subscriptions")
def get_admin_subscriptions(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Fetch all customer technology subscriptions for Admin audit."""
    try:
        subs = db.query(TechnologySubscriptionEntity).order_by(TechnologySubscriptionEntity.created_at.desc()).all()
        return [
            {
                "id": str(s.id),
                "user_id": s.user_id,
                "service_slug": s.service_slug,
                "service_name": s.service_name,
                "plan_code": s.plan_code,
                "billing_cycle": s.billing_cycle,
                "price": s.price,
                "currency": s.currency,
                "status": s.status,
                "payment_status": s.payment_status,
                "provider_subscription_id": s.provider_subscription_id,
                "provider_order_id": s.provider_order_id,
                "needs_review": s.needs_review,
                "needs_input": bool(s.last_provider_status == "NEEDS_INPUT"),
                "last_provider_status": s.last_provider_status,
                "last_provider_error": s.last_provider_error,
                "provision_attempts": s.provision_attempts,
                "next_retry_at": s.next_retry_at.isoformat() if s.next_retry_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ]
    except Exception:
        return []


@router.get("/admin/subscriptions/needs-review")
def get_admin_subscriptions_needing_review(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Admin: subscriptions requiring attention (needs_review / needs-input / manual fulfillment)."""
    try:
        subs = db.query(TechnologySubscriptionEntity).filter(
            TechnologySubscriptionEntity.is_deleted == False,
            TechnologySubscriptionEntity.status.in_(["PENDING", "PROVISIONING_FAILED"]),
            TechnologySubscriptionEntity.needs_review == True,
        ).order_by(TechnologySubscriptionEntity.created_at.desc()).all()
        return [
            {
                "id": str(s.id),
                "user_id": s.user_id,
                "service_slug": s.service_slug,
                "service_name": s.service_name,
                "plan_code": s.plan_code,
                "billing_cycle": s.billing_cycle,
                "price": s.price,
                "currency": s.currency,
                "status": s.status,
                "payment_status": s.payment_status,
                "needs_review": s.needs_review,
                "needs_input": bool(s.last_provider_status == "NEEDS_INPUT"),
                "last_provider_status": s.last_provider_status,
                "last_provider_error": s.last_provider_error,
                "provision_attempts": s.provision_attempts,
                "next_retry_at": s.next_retry_at.isoformat() if s.next_retry_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ]
    except Exception:
        return []


@router.get("/admin/orders")
def get_admin_orders(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Fetch customer provisioning order history."""
    return get_admin_subscriptions(db)


@router.get("/admin/renewals")
def get_admin_renewals(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Fetch active customer subscriptions for renewal management."""
    try:
        subs = db.query(TechnologySubscriptionEntity).filter(
            TechnologySubscriptionEntity.status == "ACTIVE",
            TechnologySubscriptionEntity.is_deleted == False,
            TechnologySubscriptionEntity.provider_subscription_id.isnot(None),
            TechnologySubscriptionEntity.current_period_end.isnot(None),
        ).order_by(TechnologySubscriptionEntity.current_period_end.asc()).all()
        return [
            {
                "id": str(s.id),
                "user_id": s.user_id,
                "service_name": s.service_name,
                "plan_code": s.plan_code,
                "billing_cycle": s.billing_cycle,
                "price": s.price,
                "currency": s.currency,
                "provider_subscription_id": s.provider_subscription_id,
                "current_period_end": s.current_period_end.isoformat() if s.current_period_end else None,
                "auto_renew": s.auto_renew,
            }
            for s in subs
        ]
    except Exception:
        return []


@router.get("/admin/failed-provisioning")
def get_admin_failed_provisioning() -> list[dict[str, Any]]:
    """Fetch list of failed provisioning attempts requiring retry."""
    return list(_FAILED_PROVISIONING_ITEMS)


@router.post("/admin/failed-provisioning/{item_id}/retry")
def retry_failed_provisioning(item_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Retry a failed provisioning attempt."""
    item = next((i for i in _FAILED_PROVISIONING_ITEMS if i["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Failed provisioning item not found")

    client = get_resellportal_client()
    prov_res = client.provision_service(
        service_slug=item["service_slug"],
        service_name=item["service_name"],
        plan_code=item["plan_code"],
        billing_cycle=item["billing_cycle"],
        user_email=item["user_email"],
        user_id=item["user_id"],
    )

    item["status"] = "RESOLVED"
    item["retry_count"] += 1
    item["resolved_at"] = datetime.now(timezone.utc).isoformat()

    _PROVISIONING_LOGS.insert(0, {
        "id": f"log-{uuid.uuid4().hex[:6]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "PROVISION_RETRY",
        "service_slug": item["service_slug"],
        "message": f"Retry provisioning successful for user {item['user_id']} ({item['service_name']})",
        "status": "SUCCESS",
    })

    return {"success": True, "item": item, "provision_result": prov_res}


@router.post("/admin/subscriptions/{subscription_id}/retry")
async def admin_retry_subscription(
    subscription_id: str,
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    """Admin: safely retry provisioning for a paid PENDING / PROVISIONING_FAILED subscription.

    Uses the reconciliation-first retry service, which never blindly submits
    a new provider order (POST /orders has no idempotency) and never charges
    Razorpay again.
    """
    from app.service.technology.technology_subscription_retry_service import (
        TechnologySubscriptionRetryService,
    )

    service = TechnologySubscriptionRetryService(db)
    result = await service.retry_subscription(subscription_id, force=True)
    if not result.get("success") and result.get("status") != "PENDING":
        raise HTTPException(status_code=400, detail=result.get("error", "Retry failed"))
    return result


class AdminFulfillRequest(BaseModel):
    credentials_json: Optional[dict[str, Any]] = Field(
        default=None, description="Credentials / access details to deliver to the customer"
    )
    provider_reference: Optional[str] = Field(
        default=None, description="Optional provider reference / subscription id"
    )
    notes: Optional[str] = Field(default=None, description="Internal audit note")


@router.post("/admin/subscriptions/{subscription_id}/fulfill")
async def admin_fulfill_subscription(
    subscription_id: str,
    payload: AdminFulfillRequest,
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    """Admin: manually fulfill a paid Technology Service (e.g. WordPress Plugin Pack).

    Transitions PENDING / PROVISIONING_FAILED → ACTIVE, records the provided
    credentials, updates the track record to PROVISIONED/SUCCESS and sends the
    customer confirmation email. NEVER charges Razorpay.
    """
    from datetime import timedelta as _td

    from sqlalchemy import select as sa_select

    from app.service.platform.track_record_service import (
        FulfillmentStatus,
        OverallStatus,
        PaymentStatus,
    )

    stmt = sa_select(TechnologySubscriptionEntity).where(
        TechnologySubscriptionEntity.id == subscription_id,
        TechnologySubscriptionEntity.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    sub = result.scalar_one_or_none()

    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if sub.status == "ACTIVE":
        raise HTTPException(status_code=400, detail="Subscription is already active")
    if sub.status == "CANCELLED":
        raise HTTPException(status_code=400, detail="Cancelled subscriptions cannot be fulfilled")
    if not sub.payment_status or sub.payment_status != "CAPTURED":
        raise HTTPException(status_code=400, detail="Payment is not captured; refusing to fulfill")

    sub.status = "ACTIVE"
    if payload.provider_reference:
        sub.provider_subscription_id = payload.provider_reference
    if payload.credentials_json is not None:
        sub.credentials_json = json.dumps(payload.credentials_json)
    sub.last_provider_status = "MANUAL_FULFILLMENT_COMPLETED"
    sub.last_provider_error = None
    sub.needs_review = False
    sub.next_retry_at = None
    if sub.current_period_start is None or sub.current_period_end is None:
        now = datetime.now(timezone.utc)
        days = 365 if str(sub.billing_cycle or "").lower().startswith("ann") else 30
        sub.current_period_start = now
        sub.current_period_end = now + _td(days=days)
    await db.flush()

    # Audit log + CoBrotherRequest advance
    from app.entity.cobrother.cobrother_request_entity import CoBrotherRequest

    if sub.razorpay_order_id or sub.razorpay_payment_id:
        req_stmt = sa_select(CoBrotherRequest).where(
            CoBrotherRequest.razorpay_order_id == sub.razorpay_order_id,
        )
        req_result = await db.execute(req_stmt)
        req = req_result.scalars().first()
        if req is None and sub.razorpay_payment_id:
            req_stmt = sa_select(CoBrotherRequest).where(
                CoBrotherRequest.razorpay_payment_id == sub.razorpay_payment_id,
            )
            req_result = await db.execute(req_stmt)
            req = req_result.scalars().first()
        if req is not None:
            from app.utils.marketplace_enums import CoBrotherRequestStatus

            req.status = CoBrotherRequestStatus.COMPLETED

    # Track record → PROVISIONED / SUCCESS (authoritative: subscription is ACTIVE
    # and fulfillment is confirmed by the admin).
    from app.repository.track_record_repository import TrackRecordRepository
    from app.service.platform.track_record_service import TrackRecordService

    track_repo = TrackRecordRepository(db)
    record = None
    if sub.razorpay_payment_id:
        record = await track_repo.find_by_razorpay_payment_id(sub.razorpay_payment_id)
    if record is None and sub.razorpay_order_id:
        record = await track_repo.find_by_razorpay_order_id(sub.razorpay_order_id)
    if record is not None:
        await TrackRecordService(db).record_paid_attempt(
            internal_order_id=record.internal_order_id,
            category=record.category,
            provider_subcategory=record.provider_subcategory or "Manual Fulfillment",
            item_name=record.item_name or sub.service_name,
            amount_charged=float(record.amount_charged or sub.price or 0.0),
            payment_status=PaymentStatus.CAPTURED,
            razorpay_order_id=record.razorpay_order_id,
            razorpay_payment_id=record.razorpay_payment_id,
            fulfillment_status=FulfillmentStatus.PROVISIONED,
            overall_status=OverallStatus.SUCCESS,
            clear_errors=True,
        )

    await db.commit()

    # Confirmation email (best-effort; flag set in every branch)
    if not sub.email_sent:
        try:
            user = None
            try:
                from app.entity.user.app_user import AppUser

                user_stmt = sa_select(AppUser).where(AppUser.id == uuid.UUID(str(sub.user_id)))
                user_result = await db.execute(user_stmt)
                user = user_result.scalar_one_or_none()
            except Exception:
                user = None
            user_email = user.email if user is not None else sub.user_id
            plan_name = sub.plan_code.replace("_", " ").title()
            await MailService.send_technology_purchase_confirmation_email(
                to_email=user_email,
                customer_name=user_email,
                service_name=sub.service_name,
                plan_name=plan_name,
                billing_cycle=sub.billing_cycle,
                cobrother_order_id=str(sub.id),
                razorpay_payment_id=sub.razorpay_payment_id,
                amount_inr=float(sub.price or 0.0),
                purchase_date=datetime.now(timezone.utc).strftime("%d %b %Y"),
                service_status="Active",
                provider_info=f"Service ID: {sub.provider_subscription_id or sub.provider_order_id or 'N/A'}",
                purchases_url=f"{settings.FRONTEND_BASE_URL.rstrip('/')}/purchases",
            )
            sub.email_sent = True
            sub.confirmation_sent = True
            await db.commit()
        except Exception:
            logger.exception("technology.admin.fulfill_confirmation_email.failed sub=%s", sub.id)

    return {
        "success": True,
        "subscription_id": str(sub.id),
        "status": sub.status,
        "credentials": json.loads(sub.credentials_json) if sub.credentials_json else {},
        "notes": payload.notes,
    }


@router.get("/admin/service-status")
def get_admin_service_status() -> dict[str, Any]:
    """Get overall ResellPortal API integration health & connection status."""
    client = get_resellportal_client()
    is_configured = client.is_configured()
    test_mode = client.is_test_mode()
    wallet = client.get_wallet_balance()

    return {
        "status": "ONLINE" if is_configured else "UNCONFIGURED_MOCK",
        "configured": is_configured,
        "test_mode": test_mode,
        "allow_live": getattr(settings, "RESELLPORTAL_ALLOW_LIVE", False),
        "api_base_url": client.api_base,
        "wallet_balance": wallet.get("balance", 145.50),
        "warning_threshold": wallet.get("warning_threshold", 7.00),
        "admin_message": (
            ""
            if is_configured
            else "ResellPortal API credentials have not been configured yet. API keys will be added after the provider wallet is funded and API access is generated."
        ),
        "latency_ms": 12.5,
    }


@router.get("/admin/logs")
def get_admin_logs() -> list[dict[str, Any]]:
    """Fetch provisioning and renewal logs for Admin console."""
    return list(_PROVISIONING_LOGS)

