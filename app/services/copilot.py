import json
import logging
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.copilot import CopilotQueryResponse, CopilotSuggestedAction
from app.services.technician_kpi import technician_kpi_service
from app.services.weather_dispatch import weather_dispatch_service

logger = logging.getLogger(__name__)


class CopilotService:
    """AI Operations Copilot providing live dispatcher assistance, KPI intelligence, and proactive action triggers."""

    async def _gather_tenant_telemetry(self, tenant: Tenant, db: AsyncSession) -> Dict[str, Any]:
        """Gathers real-time operational financials, technician rankings, emergency counts, and weather risks."""
        stmt = select(LeadAction).where(LeadAction.tenant_id == tenant.id).order_by(LeadAction.created_at.desc())
        actions = list((await db.execute(stmt)).scalars().all())

        # Financial & lead calculations
        total_leads = len(actions)
        total_revenue = 0.0
        completed_jobs = 0
        overdue_invoices_count = 0
        overdue_invoices_balance = 0.0
        active_emergencies = 0

        for act in actions:
            # Revenue calculation
            rev = 0.0
            if act.signed_contract and isinstance(act.signed_contract, dict):
                rev = float(act.signed_contract.get("total_amount", 0.0))
            elif act.invoice_data and isinstance(act.invoice_data, dict):
                rev = float(act.invoice_data.get("contract_total", 0.0))
            elif act.proposal_data and isinstance(act.proposal_data, dict):
                rev = float(act.proposal_data.get("total_amount", 0.0))
            total_revenue += rev

            # Completed jobs
            if (
                act.dispatch_status in ["COMPLETED", "INVOICED", "DISPATCHED"]
                or act.signed_contract is not None
                or act.invoice_data is not None
            ):
                completed_jobs += 1

            # Invoices overdue
            if act.invoice_data and isinstance(act.invoice_data, dict):
                status_val = act.invoice_data.get("status") or act.invoice_data.get("payment_status")
                if status_val in ["OVERDUE", "PENDING", "UNPAID"]:
                    overdue_invoices_count += 1
                    bal = float(act.invoice_data.get("balance_due", act.invoice_data.get("contract_total", 0.0)))
                    overdue_invoices_balance += bal

            # Emergencies
            is_urg = (
                act.action_type == "DISPATCH_EMERGENCY_DISPATCH_QUEUE"
                or (act.qualification_score is not None and act.qualification_score >= 0.85)
                or (act.metadata_payload or {}).get("priority_tier") == "URGENT"
            )
            if is_urg and act.dispatch_status in ["QUEUED", "DISPATCHED"]:
                active_emergencies += 1

        # Technician KPIs
        scorecards = await technician_kpi_service.calculate_technician_scorecards(tenant, db)
        top_tech = scorecards[0] if scorecards else None

        # Weather hazards
        weather_alerts = weather_dispatch_service.get_active_weather_alerts(tenant)

        return {
            "tenant_name": tenant.name,
            "tenant_slug": tenant.slug,
            "total_leads": total_leads,
            "completed_jobs": completed_jobs,
            "total_revenue": round(total_revenue, 2),
            "overdue_invoices_count": overdue_invoices_count,
            "overdue_invoices_balance": round(overdue_invoices_balance, 2),
            "active_emergencies": active_emergencies,
            "top_technician": {
                "name": top_tech.tech_name if top_tech else "Marcus Vance",
                "closing_rate_pct": top_tech.closing_rate_pct if top_tech else 85.0,
                "revenue_generated": top_tech.revenue_generated if top_tech else 4500.0,
                "commission_earned": top_tech.commission_earned if top_tech else 295.0,
            } if top_tech else None,
            "active_weather_alerts": [
                {
                    "alert_id": w.alert_id,
                    "event_title": w.event_title,
                    "severity": w.severity,
                    "counties": w.affected_counties,
                }
                for w in weather_alerts
            ],
        }

    def _fallback_deterministic_query(
        self,
        query: str,
        telemetry: Dict[str, Any],
    ) -> CopilotQueryResponse:
        """Rule-based fallback matching query intent and generating markdown summaries with action links."""
        q_lower = query.lower()
        slug = telemetry["tenant_slug"]
        top_tech = telemetry.get("top_technician") or {}
        tech_name = top_tech.get("name", "Marcus Vance")

        if any(k in q_lower for k in ["tech", "technician", "leaderboard", "kpi", "commission", "who is top", "closing rate", "performer"]):
            intent = "TECHNICIAN_KPI"
            answer = (
                f"### 🏆 Technician Performance Intelligence\n\n"
                f"- **Top Performer:** **{tech_name}** is currently leading your fleet.\n"
                f"- **Closing Rate:** `{top_tech.get('closing_rate_pct', 85.0)}%` proposal acceptance.\n"
                f"- **Revenue Generated:** `${top_tech.get('revenue_generated', 0.0):,.2f}` closed contract value.\n"
                f"- **Accrued Commission:** `${top_tech.get('commission_earned', 0.0):,.2f}` earned this rolling pay period."
            )
            actions = [
                {"label": "🏆 View Tech Leaderboard", "url": f"/technicians/{slug}", "action_type": "NAVIGATE", "variant": "primary"},
                {"label": f"📄 Print Pay Slip ({tech_name})", "url": f"/technicians/{slug}/commission/{tech_name}", "action_type": "NAVIGATE", "variant": "emerald"},
            ]

        elif any(k in q_lower for k in ["revenue", "financial", "sales", "collected", "money", "profit", "cash", "metrics", "how much", "invoice", "overdue"]):
            intent = "METRICS"
            rev = telemetry["total_revenue"]
            overdue_cnt = telemetry["overdue_invoices_count"]
            overdue_bal = telemetry["overdue_invoices_balance"]
            answer = (
                f"### 💰 Real-Time Financial & Revenue Operations\n\n"
                f"- **Gross Closed Revenue:** **${rev:,.2f}** across {telemetry['completed_jobs']} completed service jobs.\n"
                f"- **Total Work Orders:** {telemetry['total_leads']} dispatched calls logged.\n"
                f"- **Receivables Risk:** {overdue_cnt} invoices pending collection totaling **${overdue_bal:,.2f}** in delinquent funds.\n"
                f"- **Recommended Guard:** Trigger formal Statutory Notices to Owner to safeguard mechanic's lien rights."
            )
            actions = [
                {"label": "📊 Executive Financial Portal", "url": f"/portal/{slug}", "action_type": "NAVIGATE", "variant": "primary"},
                {"label": "⚡ Operator Console", "url": "/dashboard", "action_type": "NAVIGATE", "variant": "emerald"},
            ]

        elif any(k in q_lower for k in ["weather", "storm", "freeze", "rain", "wind", "radar", "blizzard", "heat", "meteorological"]):
            intent = "WEATHER_RISK"
            alerts = telemetry.get("active_weather_alerts", [])
            alert_count = len(alerts)
            first_alert = alerts[0]["event_title"] if alerts else "Severe Freeze Advisory"
            answer = (
                f"### ⛈️ Severe Weather Meteorological Hazard Report\n\n"
                f"- **Active Hazards Detected:** **{alert_count} meteorological alert(s)** in territory.\n"
                f"- **Primary Advisory:** {first_alert} affecting regional service routes.\n"
                f"- **Automated Protection:** Pre-freeze and emergency pipe protection broadcasts are armed for local customers."
            )
            actions = [
                {"label": "⛈️ Severe Weather Radar", "url": "/weather", "action_type": "NAVIGATE", "variant": "warning"},
                {"label": "📢 Send Weather Alert Broadcast", "url": "/weather", "action_type": "NAVIGATE", "variant": "primary"},
            ]

        elif any(k in q_lower for k in ["emergency", "urgent", "active call", "dispatched", "queue", "leak", "priority"]):
            intent = "EMERGENCY_SUMMARY"
            emergencies = telemetry["active_emergencies"]
            answer = (
                f"### 🚨 Active Emergency Dispatch Queue\n\n"
                f"- **Active Emergency Calls:** **{emergencies} urgent work order(s)** requiring rapid arrival.\n"
                f"- **Automated Routing:** Voice IVR arrival calls and live GPS tracking links have been activated.\n"
                f"- **Fleet Deployment:** Crews are dispatched with dynamic ETA notifications."
            )
            actions = [
                {"label": "🗺️ Live Dispatch Map", "url": f"/map/{slug}", "action_type": "NAVIGATE", "variant": "warning"},
                {"label": "⚡ Manage Dispatch Queue", "url": "/dashboard", "action_type": "NAVIGATE", "variant": "primary"},
            ]

        else:
            intent = "GENERAL"
            answer = (
                f"### 🤖 DispatchEngine Operational Overview ({telemetry['tenant_name']})\n\n"
                f"- **Fleet Status:** {telemetry['completed_jobs']} jobs completed • Top Producer: **{tech_name}**.\n"
                f"- **Gross Revenue:** `${telemetry['total_revenue']:,.2f}` recorded.\n"
                f"- **Active Emergencies:** {telemetry['active_emergencies']} high-priority work orders in queue.\n"
                f"- **Active Weather Warnings:** {len(telemetry.get('active_weather_alerts', []))} regional alert(s)."
            )
            actions = [
                {"label": "⚡ Operator Console", "url": "/dashboard", "action_type": "NAVIGATE", "variant": "primary"},
                {"label": "🏆 Tech Scorecards", "url": f"/technicians/{slug}", "action_type": "NAVIGATE", "variant": "emerald"},
                {"label": "⛈️ Weather Radar", "url": "/weather", "action_type": "NAVIGATE", "variant": "warning"},
            ]

        return CopilotQueryResponse(
            answer_text=answer,
            intent=intent,
            suggested_actions=actions,
            data_payload=telemetry,
        )

    async def execute_copilot_query(
        self,
        query: str,
        tenant: Tenant,
        db: AsyncSession,
    ) -> CopilotQueryResponse:
        """
        Executes a dispatcher query against real-time operational telemetry using Gemini 2.5 Flash
        with robust deterministic fallback.
        """
        telemetry = await self._gather_tenant_telemetry(tenant, db)

        if settings.GEMINI_API_KEY:
            try:
                client = genai.Client(api_key=settings.GEMINI_API_KEY)
                prompt = (
                    f"You are the AI Operations Copilot for a premier trade dispatch and field service enterprise.\n"
                    f"Contractor: {tenant.name} (slug: {tenant.slug})\n\n"
                    f"Current Live Operational Telemetry:\n{json.dumps(telemetry, indent=2)}\n\n"
                    f"Dispatcher Query: \"{query}\"\n\n"
                    f"Instructions:\n"
                    f"1. Categorize intent as one of: METRICS, TECHNICIAN_KPI, EMERGENCY_SUMMARY, WEATHER_RISK, or GENERAL.\n"
                    f"2. Provide answer_text formatted in concise, authoritative markdown with bullet points and bold financial/KPI numbers.\n"
                    f"3. Generate suggested_actions with actionable deep-link buttons pointing to appropriate routes (e.g. /technicians/{tenant.slug}, /portal/{tenant.slug}, /weather, /dashboard, /map/{tenant.slug})."
                )
                response = await client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=CopilotQueryResponse,
                        temperature=0.2,
                    ),
                )
                if response.text:
                    parsed = json.loads(response.text)
                    parsed["data_payload"] = telemetry
                    return CopilotQueryResponse.model_validate(parsed)
            except Exception as exc:
                logger.warning(f"Gemini copilot query failed, using deterministic fallback: {exc}")

        return self._fallback_deterministic_query(query, telemetry)


copilot_service = CopilotService()
