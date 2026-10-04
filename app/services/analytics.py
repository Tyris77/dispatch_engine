import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.models.webhook_event import WebhookEvent

# Industry benchmark: Average ticket value for residential & commercial emergency trade jobs
AVERAGE_TRADE_JOB_VALUE = 3500.0
ESTIMATED_MINUTES_PER_DISPATCH = 15.0  # 0.25 hours saved per autonomous call


def render_executive_email_html(
    tenant_name: str,
    tenant_slug: str,
    total_calls: int,
    emergencies_bridged: int,
    pipeline_value: float,
    hours_saved: float,
    roi_multiplier: float,
    recent_leads: List[LeadAction],
) -> str:
    """Render a clean, high-conversion dark-mode executive HTML email digest."""
    rows_html = ""
    for lead in recent_leads:
        urgency = "EMERGENCY" if ("EMERGENCY" in lead.action_type or (lead.qualification_score or 0) >= 0.8) else "QUALIFIED"
        badge_color = "#f43f5e" if urgency == "EMERGENCY" else "#06b6d4"
        rows_html += f"""
        <tr style="border-bottom: 1px solid #1f2937;">
            <td style="padding: 10px 12px; font-family: monospace; color: #9ca3af; font-size: 12px;">{lead.created_at.strftime('%b %d, %H:%M') if lead.created_at else 'Recent'}</td>
            <td style="padding: 10px 12px; color: #ffffff; font-size: 13px; font-weight: 500;">{lead.lead_external_id or 'Caller'}</td>
            <td style="padding: 10px 12px; font-size: 11px;"><span style="background-color: {badge_color}20; color: {badge_color}; border: 1px solid {badge_color}40; padding: 2px 8px; border-radius: 9999px; font-weight: bold;">{urgency}</span></td>
            <td style="padding: 10px 12px; color: #d1d5db; font-size: 12px; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{lead.qualification_summary or 'Inquiry resolved autonomously'}</td>
        </tr>
        """

    if not rows_html:
        rows_html = '<tr><td colspan="4" style="padding: 16px; text-align: center; color: #6b7280; font-size: 13px;">No inquiries recorded this period.</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Weekly Operations & ROI Digest — {tenant_name}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #030712; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f3f4f6;">
<table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #030712; padding: 32px 16px;">
  <tr>
    <td align="center">
      <table width="600" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; width: 100%; background-color: #111827; border-radius: 20px; border: 1px solid #374151; overflow: hidden; box-shadow: 0 20px 40px rgba(0,0,0,0.5);">
        
        <!-- Header -->
        <tr>
          <td style="background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%); padding: 32px; text-align: center;">
            <p style="margin: 0; font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #e0e7ff; font-weight: bold;">Autonomous Operations Engine</p>
            <h1 style="margin: 8px 0 0 0; font-size: 26px; font-weight: 900; color: #ffffff;">Weekly Performance Digest</h1>
            <p style="margin: 6px 0 0 0; font-size: 14px; color: #f3f4f6;">Client: <strong>{tenant_name}</strong></p>
          </td>
        </tr>

        <!-- Metrics Grid -->
        <tr>
          <td style="padding: 24px 32px;">
            <table width="100%" border="0" cellspacing="12" cellpadding="0">
              <tr>
                <td width="50%" style="background-color: #1f2937; border-radius: 14px; padding: 18px; border: 1px solid #374151;">
                  <span style="font-size: 11px; text-transform: uppercase; color: #9ca3af; font-weight: bold;">Recovered Pipeline</span>
                  <div style="font-size: 28px; font-weight: 900; color: #10b981; margin-top: 4px;">${pipeline_value:,.2f}</div>
                  <span style="font-size: 11px; color: #6b7280;">Benchmark @ $3,500/job</span>
                </td>
                <td width="50%" style="background-color: #1f2937; border-radius: 14px; padding: 18px; border: 1px solid #374151;">
                  <span style="font-size: 11px; text-transform: uppercase; color: #9ca3af; font-weight: bold;">Emergencies Bridged</span>
                  <div style="font-size: 28px; font-weight: 900; color: #f43f5e; margin-top: 4px;">{emergencies_bridged} Calls</div>
                  <span style="font-size: 11px; color: #6b7280;">Bypassed voicemail</span>
                </td>
              </tr>
              <tr>
                <td width="50%" style="background-color: #1f2937; border-radius: 14px; padding: 18px; border: 1px solid #374151;">
                  <span style="font-size: 11px; text-transform: uppercase; color: #9ca3af; font-weight: bold;">Total Inquiries Handled</span>
                  <div style="font-size: 24px; font-weight: 800; color: #ffffff; margin-top: 4px;">{total_calls} Inbound</div>
                  <span style="font-size: 11px; color: #6b7280;">24/7 autonomous reception</span>
                </td>
                <td width="50%" style="background-color: #1f2937; border-radius: 14px; padding: 18px; border: 1px solid #374151;">
                  <span style="font-size: 11px; text-transform: uppercase; color: #9ca3af; font-weight: bold;">Est. Hours Saved</span>
                  <div style="font-size: 24px; font-weight: 800; color: #38bdf8; margin-top: 4px;">{hours_saved:.1f} Hours</div>
                  <span style="font-size: 11px; color: #6b7280;">{roi_multiplier}x Monthly Net ROI</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Recent Activity Table -->
        <tr>
          <td style="padding: 0 32px 24px 32px;">
            <h3 style="margin: 0 0 12px 0; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #9ca3af;">Recent Emergency & High-Urgency Leads</h3>
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="border: 1px solid #374151; border-radius: 12px; overflow: hidden; background-color: #111827;">
              <thead>
                <tr style="background-color: #1f2937; text-align: left; font-size: 11px; text-transform: uppercase; color: #9ca3af;">
                  <th style="padding: 10px 12px;">Time</th>
                  <th style="padding: 10px 12px;">Contact</th>
                  <th style="padding: 10px 12px;">Urgency</th>
                  <th style="padding: 10px 12px;">Diagnosis</th>
                </tr>
              </thead>
              <tbody>
                {rows_html}
              </tbody>
            </table>
          </td>
        </tr>

        <!-- CTA Button -->
        <tr>
          <td style="padding: 0 32px 32px 32px; text-align: center;">
            <a href="https://example.com/portal/{tenant_slug}" style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%); color: #ffffff; text-decoration: none; padding: 14px 32px; font-size: 14px; font-weight: bold; border-radius: 12px; box-shadow: 0 10px 25px rgba(79, 70, 229, 0.4);">
              Open Live Client Portal &rarr;
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background-color: #0b0f19; padding: 20px 32px; text-align: center; border-top: 1px solid #1f2937; font-size: 11px; color: #6b7280;">
            This automated executive digest was prepared by <strong>DispatchEngine</strong>.<br>
            To manage notifications or alert phone settings, visit your Client Portal.
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


async def generate_weekly_roi_digest(
    tenant_id: uuid.UUID,
    db: AsyncSession,
    lookback_days: int = 7,
) -> Dict[str, Any]:
    """
    Generate 7-day ROI analytics digest for a specific tenant:
    - Counts total calls/events, emergency bridges, and qualified leads.
    - Calculates estimated recovered pipeline value at $3,500/job benchmark.
    - Produces a fully-rendered executive email HTML report.
    """
    # 1. Resolve Tenant
    query = select(Tenant).where(Tenant.id == tenant_id)
    tenant = (await db.execute(query)).scalar_one_or_none()

    if not tenant:
        raise ValueError(f"Tenant with id '{tenant_id}' not found.")

    # 2. Time Window
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=lookback_days)

    # 3. Aggregate Total Inbound Calls / Events
    total_calls_q = select(func.count(WebhookEvent.id)).where(
        WebhookEvent.tenant_id == tenant_id,
        WebhookEvent.created_at >= since,
    )
    total_calls = (await db.execute(total_calls_q)).scalar() or 0

    # 4. Aggregate Emergencies Bridged
    emergencies_q = select(func.count(LeadAction.id)).where(
        LeadAction.tenant_id == tenant_id,
        LeadAction.created_at >= since,
        or_(
            LeadAction.action_type.like("%EMERGENCY%"),
            LeadAction.qualification_score >= 0.8,
        ),
    )
    emergencies_bridged = (await db.execute(emergencies_q)).scalar() or 0

    # 5. Aggregate Qualified Trade Leads
    qualified_leads_q = select(func.count(LeadAction.id)).where(
        LeadAction.tenant_id == tenant_id,
        LeadAction.created_at >= since,
        LeadAction.qualification_score >= 0.4,
    )
    qualified_leads_count = (await db.execute(qualified_leads_q)).scalar() or 0

    # 6. Aggregate Dispatched Actions
    dispatched_actions_q = select(func.count(LeadAction.id)).where(
        LeadAction.tenant_id == tenant_id,
        LeadAction.created_at >= since,
        LeadAction.dispatch_status == "COMPLETED",
    )
    dispatched_actions = (await db.execute(dispatched_actions_q)).scalar() or 0

    # 7. Fetch Recent Leads for Table
    recent_leads_q = (
        select(LeadAction)
        .where(
            LeadAction.tenant_id == tenant_id,
            LeadAction.created_at >= since,
        )
        .order_by(LeadAction.created_at.desc())
        .limit(5)
    )
    recent_leads = list((await db.execute(recent_leads_q)).scalars().all())

    # 8. Financial Calculations
    # Trade multiplier can be customized via tenant.settings
    multiplier = float(tenant.settings.get("avg_job_value", AVERAGE_TRADE_JOB_VALUE))
    pipeline_recovered = round(qualified_leads_count * multiplier, 2)
    hours_saved = round(total_calls * (ESTIMATED_MINUTES_PER_DISPATCH / 60.0), 1)
    monthly_plan_cost = 149.0
    roi_multiplier = round(pipeline_recovered / max(1.0, monthly_plan_cost), 1) if pipeline_recovered > 0 else 0.0

    # 9. Render Executive Email
    email_html = render_executive_email_html(
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        total_calls=total_calls,
        emergencies_bridged=emergencies_bridged,
        pipeline_value=pipeline_recovered,
        hours_saved=hours_saved,
        roi_multiplier=roi_multiplier,
        recent_leads=recent_leads,
    )

    digest = {
        "tenant_id": str(tenant.id),
        "tenant_slug": tenant.slug,
        "tenant_name": tenant.name,
        "period": f"Last {lookback_days} Days",
        "generated_at": now.isoformat(),
        "total_calls": total_calls,
        "emergencies_bridged": emergencies_bridged,
        "qualified_leads": qualified_leads_count,
        "dispatched_actions": dispatched_actions,
        "benchmark_job_value": multiplier,
        "pipeline_value_recovered": pipeline_recovered,
        "hours_saved": hours_saved,
        "roi_multiplier": roi_multiplier,
        "email_html": email_html,
    }

    logger.info(
        f"[ROI Analytics] Generated weekly digest for {tenant.slug}: "
        f"{emergencies_bridged} emergencies, ${pipeline_recovered:,.2f} recovered pipeline."
    )
    return digest
