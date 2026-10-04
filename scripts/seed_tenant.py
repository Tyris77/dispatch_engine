#!/usr/bin/env python3
"""
CLI Utility to onboard and seed client tenants for the Multi-Tenant Operations & Dispatch Engine.

Usage:
    python scripts/seed_tenant.py --name "Acme Roofing" --slug "acme-roofing" --alert-phone "+15551234567"
"""

import argparse
import asyncio
import os
import sys
import uuid
from typing import Optional

# Ensure project root is in sys.path when script is executed directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.config import settings
from app.core.security import generate_api_key, generate_webhook_secret
from app.db.base import Base
from app.db.session import AsyncSessionLocal, async_engine
from app.models.tenant import Tenant


async def seed_tenant(
    name: str,
    slug: str,
    alert_phone: Optional[str] = None,
    webhook_url: Optional[str] = None,
    min_score: float = 0.4,
) -> Tenant:
    # Ensure tables exist for local SQLite run
    if settings.DATABASE_URL.startswith("sqlite"):
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if slug exists
        query = select(Tenant).where(Tenant.slug == slug)
        existing = (await db.execute(query)).scalar_one_or_none()

        if existing:
            print(f"[!] Tenant with slug '{slug}' already exists (ID: {existing.id})")
            if alert_phone or webhook_url:
                updated_settings = dict(existing.settings)
                if alert_phone:
                    updated_settings["alert_phone_number"] = alert_phone
                if webhook_url:
                    updated_settings["webhook_url"] = webhook_url
                updated_settings["min_qualification_score"] = min_score
                existing.settings = updated_settings
                await db.commit()
                print(f"[+] Updated settings for existing tenant '{slug}'.")
            return existing

        # Generate credentials
        raw_api_key, api_key_hash = generate_api_key()
        webhook_secret = generate_webhook_secret()

        tenant_settings = {
            "min_qualification_score": min_score,
            "routing_rules": {
                "default_route": "general_inbox",
                "high_priority_route": "vip_sales_queue",
                "emergency_route": "emergency_dispatch_queue",
            },
        }
        if alert_phone:
            tenant_settings["alert_phone_number"] = alert_phone
        if webhook_url:
            tenant_settings["webhook_url"] = webhook_url

        tenant = Tenant(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            api_key_hash=api_key_hash,
            webhook_secret=webhook_secret,
            is_active=True,
            settings=tenant_settings,
        )
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

        # Pretty-print credentials and endpoints
        border = "=" * 70
        print(f"\n{border}")
        print(f"  CLIENT TENANT SUCCESSFULLY ONBOARDED: {name}")
        print(border)
        print(f"  Tenant ID:            {tenant.id}")
        print(f"  Tenant Slug:          {tenant.slug}")
        print(f"  Alert Phone:          {alert_phone or 'Not configured'}")
        print(f"  Min Qual. Score:      {min_score}")
        print(f"  External CRM Webhook: {webhook_url or 'None'}")
        print(f"\n  [SECURITY CREDENTIALS - STORE SECURELY]")
        print(f"  Raw API Key:          {raw_api_key}")
        print(f"  Webhook Secret:       {webhook_secret}")
        print(f"\n  [WEBHOOK ENDPOINTS]")
        print(f"  Twilio SMS Webhook:   http://localhost:8000/api/v1/webhooks/twilio/sms?tenant_slug={tenant.slug}")
        print(f"  Direct JSON Webhook:  http://localhost:8000/api/v1/webhooks/{tenant.slug}")
        print(f"  Operator Dashboard:   http://localhost:8000/dashboard?tenant_slug={tenant.slug}")
        print(f"{border}\n")

        return tenant


def main():
    parser = argparse.ArgumentParser(
        description="Seed and onboard a client tenant with credentials and routing configuration."
    )
    parser.add_argument("--name", required=True, help="Tenant / organization display name")
    parser.add_argument("--slug", required=True, help="URL-friendly identifier (e.g. acme-roofing)")
    parser.add_argument("--alert-phone", default=None, help="E.164 phone number for urgent SMS alerts")
    parser.add_argument("--webhook-url", default=None, help="External CRM or webhook destination URL")
    parser.add_argument("--min-score", type=float, default=0.4, help="Minimum lead qualification score (0.0-1.0)")

    args = parser.parse_args()

    try:
        asyncio.run(
            seed_tenant(
                name=args.name,
                slug=args.slug,
                alert_phone=args.alert_phone,
                webhook_url=args.webhook_url,
                min_score=args.min_score,
            )
        )
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
