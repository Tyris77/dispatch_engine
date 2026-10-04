from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.commercial import (
    CommercialWorkOrder,
    ConsolidatedMonthlyStatement,
    PropertyPortfolio,
)


class CommercialService:
    """
    Commercial Property Manager Multi-Unit Portal & Work Order Automation Service.
    Handles multi-family building portfolios, automated approval threshold routing,
    1-tap SMS approvals, and consolidated Net-30 monthly corporate billing statements.
    """

    DEFAULT_PORTFOLIOS: List[Dict[str, Any]] = [
        {
            "portfolio_id": "meridian-pentagon",
            "property_name": "The Meridian at Pentagon City",
            "property_address": "1401 S Joyce St, Arlington, VA 22202",
            "unit_count": 240,
            "manager_name": "Elena Rostova",
            "manager_phone": "+17035550182",
            "manager_email": "elena.rostova@meridianliving.com",
            "auto_approval_threshold": 500.0,
        },
        {
            "portfolio_id": "dupont-lofts",
            "property_name": "Dupont Historic Lofts",
            "property_address": "1620 19th St NW, Washington, DC 20009",
            "unit_count": 85,
            "manager_name": "Marcus Vance",
            "manager_phone": "+12025550144",
            "manager_email": "mvance@dupontlofts-dc.com",
            "auto_approval_threshold": 650.0,
        },
        {
            "portfolio_id": "bethesda-gateway",
            "property_name": "Bethesda Gateway Office Park",
            "property_address": "7315 Wisconsin Ave, Bethesda, MD 20814",
            "unit_count": 42,
            "manager_name": "Sarah Jenkins",
            "manager_phone": "+13015550199",
            "manager_email": "sjenkins@bethesdagateway.com",
            "auto_approval_threshold": 1200.0,
        },
    ]

    def get_tenant_portfolios(self, tenant: Tenant) -> List[PropertyPortfolio]:
        """
        Retrieves managed property portfolios configured for this tenant,
        or yields standard regional commercial building portfolios.
        """
        tenant_settings = tenant.settings or {}
        portfolios_raw = tenant_settings.get("commercial_portfolios")

        if portfolios_raw and isinstance(portfolios_raw, list):
            portfolios = []
            for item in portfolios_raw:
                try:
                    portfolios.append(PropertyPortfolio.model_validate(item))
                except Exception as exc:
                    logger.warning(f"Error parsing commercial portfolio {item}: {exc}")
            if portfolios:
                return portfolios

        return [PropertyPortfolio.model_validate(p) for p in self.DEFAULT_PORTFOLIOS]

    def estimate_repair_cost(self, issue_text: str) -> float:
        """
        Estimates commercial repair costs based on scope keywords.
        """
        text_lower = (issue_text or "").lower()

        # High complexity / major mechanical / commercial refrigeration / mainline sewer
        if any(
            kw in text_lower
            for kw in [
                "compressor",
                "rtu",
                "sewer",
                "main line",
                "boiler",
                "flood",
                "heat pump replacement",
                "electrical panel",
                "transformer",
                "chiller",
                "cooling tower",
            ]
        ):
            return 1450.0

        # Medium complexity / leaks / motors / elements / breakers / AC cooling failure
        if any(
            kw in text_lower
            for kw in [
                "water heater",
                "blower",
                "ac not cooling",
                "heat not working",
                "leak",
                "circuit breaker",
                "condensate",
                "thermostat",
                "fan motor",
                "disposal",
            ]
        ):
            return 580.0

        # Low complexity / clogged toilet / dripping faucet / filter / minor fixture
        return 285.0

    async def process_commercial_tenant_request(
        self,
        portfolio: PropertyPortfolio,
        unit_number: str,
        tenant_name: str,
        issue_text: str,
        tenant: Tenant,
        db: AsyncSession,
    ) -> CommercialWorkOrder:
        """
        Processes an incoming commercial maintenance request from a tenant unit:
        1. Estimates repair cost.
        2. Evaluates cost against property auto-approval threshold.
        3. If <= threshold: Auto-approves and advances to active dispatch.
        4. If > threshold: Flags as PENDING_PM_APPROVAL and dispatches 1-tap SMS approval link to PM.
        5. Persists LeadAction with commercial_data.
        """
        estimated_cost = self.estimate_repair_cost(issue_text)
        order_id = f"WO-{uuid.uuid4().hex[:6].upper()}"
        base_url = (tenant.settings or {}).get("base_url") or "http://localhost:8000"
        approval_link = f"{base_url}/commercial/{tenant.slug}?approve={order_id}"

        is_auto_approved = estimated_cost <= portfolio.auto_approval_threshold

        approval_status = "APPROVED_AUTO" if is_auto_approved else "PENDING_PM_APPROVAL"
        dispatch_status = "SCHEDULED" if is_auto_approved else "NEEDS_MANUAL_DISPATCH"

        # Construct initial work order schema
        work_order = CommercialWorkOrder(
            order_id=order_id,
            property_name=portfolio.property_name,
            unit_number=unit_number,
            tenant_name=tenant_name,
            issue_description=issue_text,
            estimated_cost=estimated_cost,
            approval_status=approval_status,
            action_id="",  # Updated after LeadAction creation
            portfolio_id=portfolio.portfolio_id,
            manager_name=portfolio.manager_name,
            approval_link=approval_link if not is_auto_approved else None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Create linked LeadAction
        lead_action = LeadAction(
            tenant_id=tenant.id,
            lead_external_id=f"COMMERCIAL-{portfolio.portfolio_id}-{unit_number}-{order_id}",
            qualification_score=0.95,
            qualification_summary=(
                f"Commercial Work Order {order_id} ({portfolio.property_name} Unit {unit_number}): "
                f"{issue_text[:120]} [Status: {approval_status}, Est: ${estimated_cost:.2f}]"
            ),
            action_type="COMMERCIAL_DISPATCH",
            dispatch_status=dispatch_status,
            crm_sync_status="PENDING",
            metadata_payload={
                "address": f"{portfolio.property_address}, Unit {unit_number}",
                "customer_name": tenant_name,
                "customer_phone": portfolio.manager_phone,
                "property_name": portfolio.property_name,
                "unit_number": unit_number,
                "portfolio_id": portfolio.portfolio_id,
                "order_id": order_id,
            },
            commercial_data=work_order.model_dump(),
        )

        db.add(lead_action)
        await db.commit()
        await db.refresh(lead_action)

        # Update action_id on work order and persist
        work_order.action_id = str(lead_action.id)
        lead_action.commercial_data = work_order.model_dump()
        await db.commit()

        # Handle SMS notification if approval required
        if not is_auto_approved and portfolio.manager_phone:
            sms_text = (
                f"APPROVAL REQUIRED: Work Order {order_id} at {portfolio.property_name} "
                f"Unit {unit_number} ({issue_text[:50]}). Est: ${estimated_cost:.2f} "
                f"exceeds ${portfolio.auto_approval_threshold:.2f} cap. 1-tap approve: {approval_link}"
            )
            self._dispatch_sms(
                to_phone=portfolio.manager_phone,
                body=sms_text,
                tenant=tenant,
            )

        logger.info(
            f"Commercial work order {order_id} processed for {portfolio.property_name} "
            f"Unit {unit_number}: status={approval_status}, cost=${estimated_cost:.2f}"
        )
        return work_order

    async def approve_commercial_work_order(
        self,
        order_id: str,
        tenant: Tenant,
        db: AsyncSession,
    ) -> Optional[CommercialWorkOrder]:
        """
        1-tap approval triggered by property manager.
        Advances status to APPROVED_BY_PM and dispatch status to DISPATCHED.
        """
        stmt = select(LeadAction).where(LeadAction.tenant_id == tenant.id)
        result = await db.execute(stmt)
        leads = result.scalars().all()

        target_lead: Optional[LeadAction] = None
        for lead in leads:
            cdata = lead.commercial_data or {}
            if cdata.get("order_id") == order_id:
                target_lead = lead
                break

        if not target_lead:
            logger.warning(f"Work order {order_id} not found for tenant {tenant.slug}")
            return None

        cdata = dict(target_lead.commercial_data or {})
        cdata["approval_status"] = "APPROVED_BY_PM"
        target_lead.commercial_data = cdata
        target_lead.dispatch_status = "DISPATCHED"

        await db.commit()
        await db.refresh(target_lead)

        work_order = CommercialWorkOrder.model_validate(target_lead.commercial_data)

        # Send confirmation SMS to property manager
        manager_phone = (
            work_order.manager_name
            and target_lead.metadata_payload.get("customer_phone")
        )
        if manager_phone:
            conf_sms = (
                f"CONFIRMED: Work order {order_id} at {work_order.property_name} "
                f"Unit {work_order.unit_number} has been approved. Priority dispatch initiated."
            )
            self._dispatch_sms(to_phone=manager_phone, body=conf_sms, tenant=tenant)

        return work_order

    async def get_portfolio_work_orders(
        self,
        tenant: Tenant,
        db: AsyncSession,
        portfolio_id: Optional[str] = None,
    ) -> List[CommercialWorkOrder]:
        """
        Lists commercial work orders for a tenant, optionally filtered by portfolio ID.
        If no records exist in the database, provides realistic sample orders.
        """
        stmt = select(LeadAction).where(LeadAction.tenant_id == tenant.id)
        result = await db.execute(stmt)
        leads = result.scalars().all()

        orders: List[CommercialWorkOrder] = []
        for lead in leads:
            if lead.commercial_data and isinstance(lead.commercial_data, dict):
                try:
                    wo = CommercialWorkOrder.model_validate(lead.commercial_data)
                    if not portfolio_id or wo.portfolio_id == portfolio_id:
                        orders.append(wo)
                except Exception as exc:
                    logger.warning(f"Failed to parse commercial work order: {exc}")

        if not orders:
            # Provide initial baseline records for instant visual rendering
            default_p = self.get_tenant_portfolios(tenant)[0]
            orders = [
                CommercialWorkOrder(
                    order_id="WO-50182A",
                    property_name=default_p.property_name,
                    unit_number="Suite 402",
                    tenant_name="Apex Logistics LLC",
                    issue_description="Rooftop HVAC unit making grinding noise, airflow restricted",
                    estimated_cost=620.0,
                    approval_status="PENDING_PM_APPROVAL",
                    action_id=str(uuid.uuid4()),
                    portfolio_id=default_p.portfolio_id,
                    manager_name=default_p.manager_name,
                    approval_link=f"http://localhost:8000/commercial/{tenant.slug}?approve=WO-50182A",
                ),
                CommercialWorkOrder(
                    order_id="WO-49931B",
                    property_name=default_p.property_name,
                    unit_number="Unit 214",
                    tenant_name="Marcus Vance",
                    issue_description="Under-sink shutoff valve dripping, replaced compression nut",
                    estimated_cost=285.0,
                    approval_status="APPROVED_AUTO",
                    action_id=str(uuid.uuid4()),
                    portfolio_id=default_p.portfolio_id,
                    manager_name=default_p.manager_name,
                ),
                CommercialWorkOrder(
                    order_id="WO-48710C",
                    property_name=default_p.property_name,
                    unit_number="Unit 108",
                    tenant_name="Dr. Aris Thorne",
                    issue_description="Main breaker panel safety inspection and thermal imaging",
                    estimated_cost=450.0,
                    approval_status="COMPLETED",
                    action_id=str(uuid.uuid4()),
                    portfolio_id=default_p.portfolio_id,
                    manager_name=default_p.manager_name,
                ),
            ]

        return orders

    async def generate_consolidated_statement(
        self,
        portfolio_id: str,
        billing_period: str,
        db: AsyncSession,
        tenant: Optional[Tenant] = None,
    ) -> ConsolidatedMonthlyStatement:
        """
        Compiles all completed and approved commercial work orders into an official
        end-of-month consolidated statement with Net 30 corporate payment terms.
        """
        portfolios = self.get_tenant_portfolios(tenant) if tenant else [
            PropertyPortfolio.model_validate(p) for p in self.DEFAULT_PORTFOLIOS
        ]
        target_portfolio = next((p for p in portfolios if p.portfolio_id == portfolio_id), portfolios[0])

        itemized_orders: List[Dict[str, Any]] = []
        total_billed = 0.0

        if tenant:
            orders = await self.get_portfolio_work_orders(tenant=tenant, db=db, portfolio_id=portfolio_id)
            for ord_item in orders:
                if ord_item.approval_status in ["APPROVED_AUTO", "APPROVED_BY_PM", "COMPLETED"]:
                    itemized_orders.append(ord_item.model_dump())
                    total_billed += ord_item.estimated_cost

        # Fallback to realistic itemized monthly billing if no database records
        if not itemized_orders:
            itemized_orders = [
                {
                    "order_id": "WO-41091",
                    "unit_number": "Suite 201",
                    "tenant_name": "Kensington Partners",
                    "issue_description": "Variable air volume (VAV) controller recalibration and sensor test",
                    "estimated_cost": 480.0,
                    "approval_status": "COMPLETED",
                    "created_at": "2026-10-02T10:15:00Z",
                },
                {
                    "order_id": "WO-41188",
                    "unit_number": "Unit 305",
                    "tenant_name": "Amina Chen",
                    "issue_description": "Commercial garbage disposal replacement with stainless 3/4 HP unit",
                    "estimated_cost": 395.0,
                    "approval_status": "COMPLETED",
                    "created_at": "2026-10-03T14:30:00Z",
                },
                {
                    "order_id": "WO-41250",
                    "unit_number": "Suite 110",
                    "tenant_name": "Nexus Dental Studio",
                    "issue_description": "Main water pressure regulator valve rebuilding and testing",
                    "estimated_cost": 725.0,
                    "approval_status": "APPROVED_BY_PM",
                    "created_at": "2026-10-04T08:45:00Z",
                },
            ]
            total_billed = sum(item["estimated_cost"] for item in itemized_orders)

        due_date = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

        return ConsolidatedMonthlyStatement(
            statement_id=f"STM-{datetime.now(timezone.utc).strftime('%Y%m')}-{uuid.uuid4().hex[:4].upper()}",
            billing_period=billing_period or datetime.now(timezone.utc).strftime("%B %Y"),
            portfolio_id=target_portfolio.portfolio_id,
            portfolio_name=target_portfolio.property_name,
            property_address=target_portfolio.property_address,
            manager_name=target_portfolio.manager_name,
            itemized_orders=itemized_orders,
            total_billed=round(total_billed, 2),
            payment_terms="NET_30",
            due_date=due_date,
        )

    def _dispatch_sms(self, to_phone: str, body: str, tenant: Tenant) -> None:
        """Internal helper to dispatch Twilio SMS or log to console."""
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            try:
                from twilio.rest import Client

                twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                from_num = (tenant.settings or {}).get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER or "+15005550006"
                twilio_client.messages.create(
                    to=to_phone,
                    from_=from_num,
                    body=body,
                )
                logger.info(f"Dispatched commercial SMS to {to_phone}")
            except Exception as exc:
                logger.warning(f"Twilio commercial SMS dispatch failed ({exc}), continuing.")
        else:
            logger.info(f"[SMS MOCK TO {to_phone}]: {body}")


commercial_service = CommercialService()
