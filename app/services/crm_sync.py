import asyncio
from typing import Any, Dict, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant


def format_jobber_payload(action: LeadAction, tenant: Tenant) -> Dict[str, Any]:
    """Format standardized lead data for Jobber Request Webhook / API."""
    qualification = action.metadata_payload.get("qualification", {})
    urgency = qualification.get("intent_level", "NORMAL")
    score = action.qualification_score or 0.0

    return {
        "client": {
            "first_name": "Inbound",
            "last_name": "Caller",
            "phones": [
                {
                    "number": action.lead_external_id or "+15550000000",
                    "primary": True,
                    "type": "Mobile",
                }
            ],
        },
        "request": {
            "title": f"[{urgency}] {action.action_type.replace('_', ' ')}",
            "description": action.qualification_summary or "Voice inquiry qualified by DispatchEngine AI.",
            "urgency": urgency,
            "referral": f"DispatchEngine ({tenant.slug})",
        },
        "custom_fields": {
            "gemini_qualification_score": score,
            "channel": action.metadata_payload.get("channel", "voice"),
            "speech_transcript": action.metadata_payload.get("speech_result", ""),
            "action_id": str(action.id),
        },
    }


def format_servicetitan_payload(action: LeadAction, tenant: Tenant) -> Dict[str, Any]:
    """Format standardized lead data for ServiceTitan Job Booking API."""
    qualification = action.metadata_payload.get("qualification", {})
    is_emergency = "EMERGENCY" in action.action_type or qualification.get("intent_level") == "EMERGENCY"

    return {
        "customer": {
            "phoneNumber": action.lead_external_id or "+15550000000",
            "name": f"Inbound Lead ({action.lead_external_id})",
        },
        "job": {
            "jobType": "Emergency Dispatch" if is_emergency else "Standard Service Estimate",
            "summary": action.qualification_summary or "Inbound inquiry via DispatchEngine AI.",
            "priority": "Critical" if is_emergency else "Standard",
            "source": f"DispatchEngine AI ({tenant.name})",
        },
        "metadata": {
            "qualification_score": action.qualification_score or 0.0,
            "channel": action.metadata_payload.get("channel", "voice"),
            "pain_points": qualification.get("pain_points", []),
            "lead_action_id": str(action.id),
        },
    }


def format_hubspot_payload(action: LeadAction, tenant: Tenant) -> Dict[str, Any]:
    """Format standardized lead data for HubSpot Contacts & Deals API."""
    qualification = action.metadata_payload.get("qualification", {})

    return {
        "properties": {
            "phone": action.lead_external_id or "",
            "lifecyclestage": "lead",
            "hs_lead_status": "NEW",
            "lead_source": "DispatchEngine AI Voice",
            "urgency_rating": qualification.get("intent_level", "MEDIUM"),
            "qualification_summary": action.qualification_summary or "",
            "gemini_score": str(action.qualification_score or 0.0),
            "dispatchengine_tenant": tenant.slug,
            "channel": action.metadata_payload.get("channel", "voice"),
        }
    }


def format_generic_webhook_payload(action: LeadAction, tenant: Tenant) -> Dict[str, Any]:
    """Format standardized JSON payload for generic REST webhooks."""
    return {
        "event": "lead.qualified_and_dispatched",
        "tenant": {
            "id": str(tenant.id),
            "slug": tenant.slug,
            "name": tenant.name,
        },
        "lead": {
            "id": str(action.id),
            "external_id": action.lead_external_id,
            "action_type": action.action_type,
            "dispatch_status": action.dispatch_status,
            "qualification_score": action.qualification_score,
            "summary": action.qualification_summary,
            "created_at": action.created_at.isoformat() if action.created_at else None,
        },
        "metadata": action.metadata_payload,
    }


async def sync_lead_to_external_crm(
    lead_action: LeadAction,
    tenant: Tenant,
    db: Optional[AsyncSession] = None,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """
    Standardized Enterprise CRM Forwarding engine.
    Formats payload according to provider (Jobber, ServiceTitan, HubSpot, Webhook)
    and pushes to destination with exponential backoff retries.
    """
    crm_config = tenant.settings.get("crm", {})
    provider = str(crm_config.get("provider", "generic_webhook")).lower().strip()
    destination_url = (
        crm_config.get("webhook_url")
        or tenant.settings.get("crm_webhook_url")
        or tenant.settings.get("webhook_url")
        or tenant.settings.get("destination_url")
    )

    # 1. Format Payload per provider
    if provider == "jobber":
        payload = format_jobber_payload(lead_action, tenant)
    elif provider == "servicetitan":
        payload = format_servicetitan_payload(lead_action, tenant)
    elif provider == "hubspot":
        payload = format_hubspot_payload(lead_action, tenant)
    else:
        payload = format_generic_webhook_payload(lead_action, tenant)

    # 2. Check Destination
    if not destination_url:
        logger.info(
            f"[CRM Sync] Tenant {tenant.slug} simulated CRM push to '{provider}' "
            f"(No destination webhook configured for lead {lead_action.lead_external_id})."
        )
        lead_action.crm_sync_status = "SYNCED"
        if db:
            await db.flush()
        return {
            "success": True,
            "status": "SIMULATED",
            "provider": provider,
            "payload": payload,
        }

    # 3. Network Push with Exponential Backoff
    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(destination_url, json=payload)
                if response.is_success:
                    logger.info(
                        f"[CRM Sync] Successfully pushed lead {lead_action.id} to {provider} "
                        f"at {destination_url} (Attempt {attempt}, Status {response.status_code})"
                    )
                    lead_action.crm_sync_status = "SYNCED"
                    lead_action.metadata_payload = {
                        **lead_action.metadata_payload,
                        "crm_sync": {
                            "provider": provider,
                            "status_code": response.status_code,
                            "attempts": attempt,
                        },
                    }
                    if db:
                        await db.flush()
                    return {
                        "success": True,
                        "status": "SYNCED",
                        "status_code": response.status_code,
                        "provider": provider,
                        "payload": payload,
                        "attempts": attempt,
                    }
                else:
                    last_error = RuntimeError(f"HTTP {response.status_code}: {response.text}")
        except Exception as exc:
            last_error = exc

        # Exponential Backoff Delay
        if attempt < max_retries:
            delay = 0.05 * (2 ** (attempt - 1))
            logger.warning(
                f"[CRM Sync] Attempt {attempt} failed for tenant {tenant.slug} ({last_error}). "
                f"Retrying in {delay:.2f}s..."
            )
            await asyncio.sleep(delay)

    logger.error(f"[CRM Sync] All {max_retries} attempts failed for {tenant.slug} to {destination_url}: {last_error}")
    lead_action.crm_sync_status = "FAILED"
    lead_action.metadata_payload = {
        **lead_action.metadata_payload,
        "crm_sync": {
            "provider": provider,
            "error": str(last_error),
            "attempts": max_retries,
        },
    }
    if db:
        await db.flush()

    return {
        "success": False,
        "status": "FAILED",
        "provider": provider,
        "error": str(last_error),
        "attempts": max_retries,
        "payload": payload,
    }


class CrmSyncService:
    """Handles external synchronization of qualified leads to CRMs (Jobber, ServiceTitan, HubSpot, Webhooks)."""

    async def sync_lead(
        self,
        tenant: Tenant,
        action: LeadAction,
        lead_payload: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """Backward-compatible helper invoking sync_lead_to_external_crm."""
        result = await sync_lead_to_external_crm(action, tenant, db=db)
        return result.get("success", False)

    sync_lead_to_external_crm = staticmethod(sync_lead_to_external_crm)
    format_jobber_payload = staticmethod(format_jobber_payload)
    format_servicetitan_payload = staticmethod(format_servicetitan_payload)
    format_hubspot_payload = staticmethod(format_hubspot_payload)
    format_generic_webhook_payload = staticmethod(format_generic_webhook_payload)


crm_sync_service = CrmSyncService()
