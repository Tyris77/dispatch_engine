import hashlib
import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.tenant import Tenant
from app.schemas.w9 import TAX_CLASSIFICATIONS, W9CertificationRecord, W9FormSubmission

EIN_RE = re.compile(r"^\d{2}-?\d{7}$")
SSN_RE = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")
MIN_SIGNATURE_BYTES = 8


def crew_key(crew_name: str) -> str:
    return (crew_name or "").strip().lower()


def mask_tin(raw: str) -> str:
    """Validate an EIN/SSN and return a masked form showing only the last four digits."""
    value = (raw or "").strip()
    digits = re.sub(r"\D", "", value)
    if EIN_RE.match(value):
        return f"XX-XXX{digits[-4:]}"
    if SSN_RE.match(value):
        return f"XXX-XX-{digits[-4:]}"
    raise ValueError("Taxpayer ID must be a valid EIN (XX-XXXXXXX) or SSN (XXX-XX-XXXX)")


async def send_w9_sms(to_phone: str, message_body: str) -> bool:
    if not to_phone:
        return False
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            client.messages.create(
                to=to_phone,
                from_=settings.TWILIO_FROM_NUMBER or "+15005550006",
                body=message_body,
            )
            return True
        except Exception as exc:
            logger.error(f"Failed to send W-9 request SMS to {to_phone}: {exc}")
            return False
    logger.info(f"[Simulation] W-9 request SMS to {to_phone}: {message_body}")
    return True


class W9Service:
    """Digital IRS Form W-9 collection for subcontractor crews."""

    _send_sms = staticmethod(send_w9_sms)

    @staticmethod
    def build_w9_link(tenant: Tenant, crew_name: str) -> str:
        base = (tenant.settings or {}).get("base_url") or "http://localhost:8000"
        return f"{base.rstrip('/')}/w9/{tenant.slug}/{urllib.parse.quote(crew_name, safe='')}"

    @staticmethod
    def get_w9_entry(tenant: Tenant, crew_name: str) -> Optional[Dict[str, Any]]:
        entries = (tenant.settings or {}).get("tax_vault_w9s") or {}
        return entries.get(crew_key(crew_name))

    async def submit_digital_w9(
        self,
        submission: W9FormSubmission,
        tenant: Tenant,
        db: AsyncSession,
    ) -> W9CertificationRecord:
        """
        Validate and record a W-9. Only the masked TIN and a signature hash are stored;
        the full taxpayer ID is never persisted.
        """
        if submission.federal_tax_classification not in TAX_CLASSIFICATIONS:
            raise ValueError(f"Invalid federal tax classification: {submission.federal_tax_classification}")
        for field in ("crew_name", "foreman_name", "business_legal_name", "address"):
            if not (getattr(submission, field) or "").strip():
                raise ValueError(f"{field} is required")

        signature = submission.signature_base64.split(",", 1)[-1].strip()
        if len(signature) < MIN_SIGNATURE_BYTES:
            raise ValueError("A signature is required to certify this form")

        tin_masked = mask_tin(submission.ein_or_ssn)
        signed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        record = W9CertificationRecord(
            w9_id=f"W9-{uuid.uuid4().hex[:8].upper()}",
            crew_name=submission.crew_name.strip(),
            tax_classification=submission.federal_tax_classification,
            tin_masked=tin_masked,
            signed_at=signed_at,
            status="VERIFIED_ON_FILE",
        )

        # Reassign a fresh dict so SQLAlchemy detects the JSON change
        new_settings = dict(tenant.settings or {})
        w9s = dict(new_settings.get("tax_vault_w9s") or {})
        w9s[crew_key(submission.crew_name)] = {
            **record.model_dump(),
            "w9_status": "ON_FILE",
            "foreman_name": submission.foreman_name.strip(),
            "business_legal_name": submission.business_legal_name.strip(),
            "address": submission.address.strip(),
            "signature_sha256": hashlib.sha256(signature.encode()).hexdigest(),
        }
        new_settings["tax_vault_w9s"] = w9s
        tenant.settings = new_settings
        await db.commit()

        logger.info(f"W-9 on file for crew '{record.crew_name}' (tenant {tenant.slug}), TIN {tin_masked}")
        return record

    async def request_w9_via_sms(
        self, crew_name: str, foreman_phone: str, tenant: Tenant
    ) -> Dict[str, Any]:
        link = self.build_w9_link(tenant, crew_name)
        body = (
            f"{tenant.name}: please complete your IRS Form W-9 for {crew_name} "
            f"so we can issue your 1099. It takes 2 minutes: {link}"
        )
        sent = await self._send_sms(foreman_phone, body)
        return {"sent": sent, "link": link, "crew_name": crew_name}


w9_service = W9Service()
