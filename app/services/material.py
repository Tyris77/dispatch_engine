import datetime
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.material import JobProfitability, PurchaseOrder, PurchaseOrderItem


async def send_po_sms(
    to_phone: str,
    message_body: str,
    from_number: Optional[str] = None,
) -> bool:
    """Dispatches SMS alert with PO # and will-call navigation link to on-call technician."""
    if not to_phone:
        return False

    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client

            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            from_num = from_number or settings.TWILIO_FROM_NUMBER or "+15005550006"
            message = client.messages.create(
                to=to_phone,
                from_=from_num,
                body=message_body,
            )
            logger.info(f"Dispatched will-call PO SMS to {to_phone} (SID: {message.sid})")
            return True
        except Exception as exc:
            logger.error(f"Failed to send PO SMS to {to_phone}: {exc}")
            return False
    else:
        logger.info(f"[Simulation] Will-Call PO SMS to {to_phone}: {message_body}")
        return True


# Comprehensive trade distributor wholesale pricing catalog
WHOLESALE_CATALOG = [
    {"match": "capacitor", "name": "Dual Run Capacitor 45/5 uF 440V", "cost": 28.50},
    {"match": "contactor", "name": "Single Pole 30A Contactor 24V Coil", "cost": 34.00},
    {"match": "fan motor", "name": "1/3 HP Condenser Fan Motor 1075 RPM", "cost": 185.00},
    {"match": "blower", "name": "1/2 HP ECM Multi-Speed Blower Motor", "cost": 240.00},
    {"match": "compressor", "name": "Copeland Scroll Compressor 3-Ton R410A", "cost": 680.00},
    {"match": "hard start", "name": "Hard Start Kit / Potential Relay SPP6", "cost": 42.00},
    {"match": "txv", "name": "Thermostatic Expansion Valve (TXV) R410A", "cost": 115.00},
    {"match": "expansion valve", "name": "Thermostatic Expansion Valve (TXV) R410A", "cost": 115.00},
    {"match": "defrost", "name": "Universal Heat Pump Defrost Control Board", "cost": 135.00},
    {"match": "refrigerant", "name": "R-410A Virgin Refrigerant 25 lb Cylinder", "cost": 165.00},
    {"match": "element", "name": "4500W 240V Screw-in Water Heater Element", "cost": 32.00},
    {"match": "thermostat", "name": "Upper/Lower Water Heater Thermostat Set", "cost": 48.00},
    {"match": "ball valve", "name": "3/4-in Full Port Lead-Free Brass Ball Valve", "cost": 24.50},
    {"match": "valve", "name": "3/4-in Full Port Brass Ball Valve", "cost": 28.00},
    {"match": "pex", "name": "3/4-in x 100-ft PEX-A Barrier Pipe Coil", "cost": 48.00},
    {"match": "copper", "name": "3/4-in Copper ProPress / Solder Fitting Assortment", "cost": 35.00},
    {"match": "fitting", "name": "Lead-Free Brass & Copper Fitting Multi-Pack", "cost": 32.50},
    {"match": "prv", "name": "3/4-in Water Pressure Reducing Valve (PRV)", "cost": 110.00},
    {"match": "regulator", "name": "3/4-in Water Pressure Reducing Valve (PRV)", "cost": 110.00},
    {"match": "wax ring", "name": "Heavy Duty Wax Ring with Flange Kit", "cost": 18.50},
    {"match": "breaker", "name": "Square D QO 2-Pole 30A/50A Circuit Breaker", "cost": 38.00},
    {"match": "panel", "name": "Square D 200A Main Breaker Interior Kit", "cost": 145.00},
    {"match": "surge", "name": "Whole Home Surge Protective Device (SPD)", "cost": 85.00},
    {"match": "shingle", "name": "CertainTeed Landmark Architectural Shingles (Bundle)", "cost": 42.00},
    {"match": "underlayment", "name": "Synthetic High-Tear Roof Underlayment Roll", "cost": 78.00},
    {"match": "flashing", "name": "Aluminum Drip Edge & Step Flashing Pack", "cost": 45.00},
    {"match": "drip edge", "name": "Aluminum Drip Edge & Step Flashing Pack", "cost": 45.00},
]

# Major wholesale supply house branch directories
SUPPLY_HOUSES = {
    "hvac": {
        "name": "Johnstone Supply",
        "branch": "Branch #118 - North Metro",
        "address": "10405 Metric Blvd, Austin, TX 78758",
        "hours": "6:00 AM - 5:00 PM (M-F)",
    },
    "plumbing": {
        "name": "Ferguson Plumbing Supply",
        "branch": "Branch #402 - Industrial District",
        "address": "1420 Industrial Blvd, Dallas, TX 75207",
        "hours": "6:30 AM - 4:30 PM (M-F)",
    },
    "roofing": {
        "name": "ABC Supply Co.",
        "branch": "Branch #28 - Gulfway Center",
        "address": "8820 Interchange Way, Houston, TX 77054",
        "hours": "6:30 AM - 4:30 PM (M-F)",
    },
    "electrical": {
        "name": "Rexel Electrical Supply",
        "branch": "Branch #14 - Central",
        "address": "2200 E 7th St, Fort Worth, TX 76102",
        "hours": "7:00 AM - 4:30 PM (M-F)",
    },
    "general": {
        "name": "Ferguson Supply",
        "branch": "Branch #101 - Metro Depot",
        "address": "500 Supply House Rd, Austin, TX 78701",
        "hours": "6:30 AM - 5:00 PM (M-F)",
    },
}


class MaterialPOService:
    """
    Service managing wholesale material purchase orders, will-call supply house routing,
    and job profitability / gross margin calculations.
    """

    _send_sms = staticmethod(send_po_sms)

    def _match_wholesale_part(self, raw_part_text: str) -> Tuple[str, float]:
        """Matches a raw part or tool string from diagnostic vision against wholesale catalog."""
        text_lower = raw_part_text.lower()
        for item in WHOLESALE_CATALOG:
            if item["match"] in text_lower:
                return (item["name"], item["cost"])

        # Fallback heuristic pricing for uncataloged parts
        hash_offset = sum(ord(c) for c in raw_part_text) % 40
        unit_cost = round(35.0 + hash_offset, 2)
        clean_name = raw_part_text.strip().title()
        return (f"{clean_name} (OEM Wholesale Replacement)", unit_cost)

    def _resolve_supply_house(
        self,
        tenant: Tenant,
        equipment_type: Optional[str] = None,
        supplier_name_override: Optional[str] = None,
    ) -> Dict[str, str]:
        """Resolves the nearest trade distributor and will-call branch address."""
        if supplier_name_override:
            # Check if matching known profile
            s_lower = supplier_name_override.lower()
            for key, profile in SUPPLY_HOUSES.items():
                if key in s_lower or profile["name"].lower() in s_lower:
                    return profile
            return {
                "name": supplier_name_override,
                "branch": "Regional Will-Call Depot",
                "address": tenant.settings.get("supplier_address", "1200 Distribution Way, Metro Industrial Park, TX"),
                "hours": "6:30 AM - 5:00 PM (M-F)",
            }

        # Resolve by equipment or tenant trade
        eq_lower = (equipment_type or "").lower()
        trade_lower = str(tenant.settings.get("trade", "")).lower()

        if any(w in eq_lower or w in trade_lower for w in ["hvac", "heat pump", "condenser", "air conditioning", "furnace", "ac"]):
            return SUPPLY_HOUSES["hvac"]
        if any(w in eq_lower or w in trade_lower for w in ["plumb", "water heater", "pipe", "drain", "leak", "valve", "faucet"]):
            return SUPPLY_HOUSES["plumbing"]
        if any(w in eq_lower or w in trade_lower for w in ["roof", "shingle", "gutter", "flashing"]):
            return SUPPLY_HOUSES["roofing"]
        if any(w in eq_lower or w in trade_lower for w in ["electr", "breaker", "panel", "wiring"]):
            return SUPPLY_HOUSES["electrical"]

        return SUPPLY_HOUSES["general"]

    def generate_material_purchase_order(
        self,
        lead_action: LeadAction,
        tenant: Tenant,
        supplier_name: Optional[str] = None,
    ) -> Tuple[PurchaseOrder, JobProfitability]:
        """
        Builds or refreshes a PurchaseOrder and calculates real-time JobProfitability:
        1. Reads recommended_parts_tools from diagnostic_data.
        2. Assigns wholesale pricing to each material item.
        3. Assigns closest local supply house will-call counter.
        4. Calculates Net Profit ($) and Gross Margin (%) against the accepted proposal tier.
        5. Saves `material_po` and `profitability_data` on `lead_action`.
        """
        diagnostic_data = lead_action.diagnostic_data or {}
        signed_contract = lead_action.signed_contract or {}
        proposal_data = lead_action.proposal_data or {}
        invoice_data = lead_action.invoice_data or {}
        metadata = lead_action.metadata_payload or {}

        # 1. Resolve Recommended Parts
        recommended = diagnostic_data.get("recommended_parts_tools") or []
        equipment_type = diagnostic_data.get("equipment_type", "Mechanical System")

        po_items: List[PurchaseOrderItem] = []
        if recommended:
            for raw_item in recommended:
                name, unit_cost = self._match_wholesale_part(raw_item)
                po_items.append(
                    PurchaseOrderItem(
                        part_name=name,
                        quantity=1,
                        estimated_unit_cost=unit_cost,
                        line_total=unit_cost,
                    )
                )
        else:
            # Fallback baseline parts if diagnostic scan had no explicit parts listed
            fallback_profile = self._resolve_supply_house(tenant, equipment_type)
            if "Johnstone" in fallback_profile["name"]:
                default_parts = [
                    ("Dual Run Capacitor 45/5 uF 440V", 28.50),
                    ("Single Pole 30A Contactor 24V Coil", 34.00),
                ]
            elif "Ferguson" in fallback_profile["name"]:
                default_parts = [
                    ("3/4-in Full Port Lead-Free Brass Ball Valve", 24.50),
                    ("3/4-in Copper ProPress Fitting Multi-Pack", 35.00),
                ]
            else:
                default_parts = [
                    ("Universal Service Hardware & Sealant Pack", 49.50),
                ]

            for name, cost in default_parts:
                po_items.append(
                    PurchaseOrderItem(
                        part_name=name,
                        quantity=1,
                        estimated_unit_cost=cost,
                        line_total=cost,
                    )
                )

        total_material_cost = round(sum(i.line_total for i in po_items), 2)

        # 2. Resolve Supply House Will-Call Location
        supplier_info = self._resolve_supply_house(tenant, equipment_type, supplier_name)
        pickup_address = supplier_info["address"]
        encoded_dest = urllib.parse.quote(f"{supplier_info['name']}, {pickup_address}")
        nav_link = f"https://www.google.com/maps/dir/?api=1&destination={encoded_dest}"

        # 3. Determine Gross Contract Revenue
        contract_revenue = 0.0
        if signed_contract:
            contract_revenue = float(signed_contract.get("price_total", signed_contract.get("final_price", 0.0)))
        elif invoice_data:
            contract_revenue = float(invoice_data.get("contract_total", 0.0))
        elif proposal_data and proposal_data.get("options"):
            contract_revenue = float(proposal_data["options"][0].get("price_estimate", 1250.0))
        else:
            contract_revenue = float(tenant.settings.get("avg_job_value", 1250.0))

        if contract_revenue <= 0.0:
            contract_revenue = 1250.0

        # 4. Compute Real-Time Job Profitability
        # Estimated technician labor is modeled at ~22% of contract revenue (or minimum $120.00)
        estimated_labor_cost = round(max(120.0, contract_revenue * 0.22), 2)
        net_profit = round(contract_revenue - total_material_cost - estimated_labor_cost, 2)
        margin_percentage = round((net_profit / contract_revenue) * 100, 1) if contract_revenue > 0 else 0.0

        margin_tier = "EXCELLENT" if margin_percentage >= 65.0 else ("HEALTHY" if margin_percentage >= 50.0 else "LOW")

        profitability = JobProfitability(
            contract_revenue=contract_revenue,
            material_costs=total_material_cost,
            estimated_labor_cost=estimated_labor_cost,
            net_profit=net_profit,
            margin_percentage=margin_percentage,
            margin_tier=margin_tier,
        )

        # 5. Build PurchaseOrder
        existing_po = lead_action.material_po or {}
        po_number = existing_po.get("po_number") or f"PO-{datetime.datetime.utcnow().year}-{str(lead_action.id)[:8].upper()}"
        status = existing_po.get("status", "DRAFT")
        ordered_at = existing_po.get("ordered_at")

        customer_name = (
            signed_contract.get("customer_name")
            or invoice_data.get("customer_name")
            or metadata.get("customer_name")
            or metadata.get("caller_name")
            or "Customer Job"
        )
        customer_phone = (
            signed_contract.get("customer_phone")
            or invoice_data.get("customer_phone")
            or metadata.get("customer_phone")
            or lead_action.lead_external_id
            or ""
        )
        service_address = (
            invoice_data.get("service_address")
            or metadata.get("service_address")
            or "Customer Location"
        )

        equip_label = equipment_type
        if diagnostic_data.get("brand_manufacturer"):
            equip_label = f"{diagnostic_data['brand_manufacturer']} {equipment_type}"

        purchase_order = PurchaseOrder(
            po_number=po_number,
            action_id=str(lead_action.id),
            supplier_name=supplier_info["name"],
            supplier_branch=supplier_info["branch"],
            items=po_items,
            total_material_cost=total_material_cost,
            pickup_address=pickup_address,
            nav_link=nav_link,
            status=status,
            customer_name=customer_name,
            customer_phone=customer_phone,
            service_address=service_address,
            equipment_summary=equip_label,
            ordered_at=ordered_at,
            created_at=existing_po.get("created_at", datetime.datetime.utcnow().isoformat()),
        )

        # Save both objects on LeadAction
        lead_action.material_po = purchase_order.model_dump()
        lead_action.profitability_data = profitability.model_dump()
        flag_modified(lead_action, "material_po")
        flag_modified(lead_action, "profitability_data")

        return purchase_order, profitability

    async def dispatch_po_to_supplier(
        self,
        action_id: uuid.UUID,
        db: AsyncSession,
    ) -> PurchaseOrder:
        """
        Dispatches will-call PO:
        1. Transitions PO status to 'ORDERED'.
        2. Records ordered_at timestamp.
        3. Dispatches SMS alert with PO # and turn-by-turn Google Maps link to the technician.
        4. Commits changes to the database.
        """
        query = select(LeadAction).where(LeadAction.id == action_id)
        lead_action = (await db.execute(query)).scalar_one_or_none()
        if not lead_action:
            raise ValueError(f"Lead action '{action_id}' not found")

        tenant_query = select(Tenant).where(Tenant.id == lead_action.tenant_id)
        tenant = (await db.execute(tenant_query)).scalar_one_or_none()
        if not tenant:
            raise ValueError(f"Tenant for lead action '{action_id}' not found")

        # Ensure PO exists
        if not lead_action.material_po:
            self.generate_material_purchase_order(lead_action=lead_action, tenant=tenant)

        po_dict = dict(lead_action.material_po)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        po_dict["status"] = "ORDERED"
        po_dict["ordered_at"] = now_iso

        lead_action.material_po = po_dict
        flag_modified(lead_action, "material_po")
        await db.commit()
        await db.refresh(lead_action)

        # Resolve tech phone number for will-call dispatch SMS
        tracking = lead_action.tracking_data or {}
        roster = tenant.settings.get("on_call_roster") or []
        tech_phone = (
            tracking.get("technician_phone")
            or (roster[0].get("phone") if roster else None)
            or tenant.settings.get("alert_phone_number")
            or settings.TWILIO_FROM_NUMBER
        )

        po_number = po_dict.get("po_number")
        supplier_name = po_dict.get("supplier_name")
        pickup_address = po_dict.get("pickup_address")
        customer_name = po_dict.get("customer_name", "Customer")
        nav_link = po_dict.get("nav_link", "https://maps.google.com")

        sms_msg = (
            f"📦 WILL-CALL READY: PO #{po_number} at {supplier_name} ({pickup_address}). "
            f"Parts boxed for {customer_name} job. Tap for GPS: {nav_link}"
        )

        from_phone = tenant.settings.get("twilio_phone_number") or settings.TWILIO_FROM_NUMBER
        await self._send_sms(to_phone=tech_phone, message_body=sms_msg, from_number=from_phone)

        return PurchaseOrder.model_validate(lead_action.material_po)


material_service = MaterialPOService()
generate_material_purchase_order = material_service.generate_material_purchase_order
dispatch_po_to_supplier = material_service.dispatch_po_to_supplier
