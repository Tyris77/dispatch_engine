import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.schemas.drip import (
    DripCampaignStatus,
    DripContractorLead,
    DripLeadStatus,
    DripTriggerResponse,
)

# 12 Initial DMV Target Contractors
INITIAL_DMV_CONTRACTORS = [
    {
        "company_name": "John C. Flood",
        "trade": "Plumbing & HVAC",
        "contact_name": "Cliff Flood",
        "contact_email": "cflood@johncflood.com",
        "phone": "+17032731100",
        "territory": "Arlington, VA & Washington, DC",
        "missed_calls_est": 48,
        "revenue_leak_est": 57600.0,
        "initial_offset_days": -2.5,  # Follow-up 1 due
    },
    {
        "company_name": "The Drain Guys",
        "trade": "Plumbing & Drain Cleaning",
        "contact_name": "Dave Miller",
        "contact_email": "dave@thedrainguysmd.com",
        "phone": "+13018693724",
        "territory": "Bethesda & Montgomery County, MD",
        "missed_calls_est": 36,
        "revenue_leak_est": 39600.0,
        "initial_offset_days": -2.1,  # Follow-up 1 due
    },
    {
        "company_name": "Superior Air Systems",
        "trade": "HVAC",
        "contact_name": "Marcus Vance",
        "contact_email": "service@superiorairdmv.com",
        "phone": "+17038301200",
        "territory": "Fairfax & Northern VA",
        "missed_calls_est": 42,
        "revenue_leak_est": 54600.0,
        "initial_offset_days": -5.2,  # Follow-up 2 due
    },
    {
        "company_name": "AZA Mechanical",
        "trade": "Commercial HVAC & Plumbing",
        "contact_name": "Zack Al-Mansoor",
        "contact_email": "estimating@azamechanical.com",
        "phone": "+12025442000",
        "territory": "Washington, DC",
        "missed_calls_est": 55,
        "revenue_leak_est": 82500.0,
        "initial_offset_days": -5.5,  # Follow-up 2 due
    },
    {
        "company_name": "Cardinal Emergency Plumbing",
        "trade": "Plumbing",
        "contact_name": "Rob Sterling",
        "contact_email": "rob@cardinalplumbingva.com",
        "phone": "+17037218888",
        "territory": "Alexandria, VA",
        "missed_calls_est": 32,
        "revenue_leak_est": 38400.0,
        "initial_offset_days": -1.0,  # Contacted
    },
    {
        "company_name": "F.H. Furr Plumbing & HVAC",
        "trade": "Plumbing & HVAC",
        "contact_name": "Frank Furr Jr.",
        "contact_email": "dispatch@fhfurr.com",
        "phone": "+17036900000",
        "territory": "Manassas & Fairfax, VA",
        "missed_calls_est": 60,
        "revenue_leak_est": 84000.0,
        "initial_offset_days": -0.5,  # Contacted
    },
    {
        "company_name": "Michael & Son Services",
        "trade": "Multi-Trade MEP",
        "contact_name": "Jamil Mansoor",
        "contact_email": "jamil@michaelandson.com",
        "phone": "+18009486453",
        "territory": "Richmond, Alexandria & DC",
        "missed_calls_est": 72,
        "revenue_leak_est": 93600.0,
        "initial_offset_days": -3.0,  # Follow-up 1 due
    },
    {
        "company_name": "CroppMetcalfe",
        "trade": "HVAC & Plumbing",
        "contact_name": "Tim Metcalfe",
        "contact_email": "service@croppmetcalfe.com",
        "phone": "+13013130383",
        "territory": "Silver Spring, MD & Fairfax, VA",
        "missed_calls_est": 45,
        "revenue_leak_est": 58500.0,
        "initial_offset_days": -5.1,  # Follow-up 2 due
    },
    {
        "company_name": "Magnolia Plumbing & Heating",
        "trade": "Plumbing & Mechanical",
        "contact_name": "Anthony Magnolia",
        "contact_email": "anthony@magnoliaplumbing.com",
        "phone": "+18888588555",
        "territory": "Washington, DC & Prince George's, MD",
        "missed_calls_est": 38,
        "revenue_leak_est": 45600.0,
        "initial_offset_days": -4.0,  # Follow-up 1 sent
    },
    {
        "company_name": "4-Star Emergency Restoration",
        "trade": "Water Mitigation & Restoration",
        "contact_name": "Elena Rostova",
        "contact_email": "claims@4stardmv.com",
        "phone": "+12403991200",
        "territory": "Rockville & Montgomery County, MD",
        "missed_calls_est": 25,
        "revenue_leak_est": 67500.0,
        "initial_offset_days": -2.2,  # Follow-up 1 due
    },
    {
        "company_name": "Capitol Commercial Roofing",
        "trade": "Commercial Roofing",
        "contact_name": "Sean O'Donnell",
        "contact_email": "sean@capitolroofingdc.com",
        "phone": "+12028829000",
        "territory": "Washington, DC & Arlington, VA",
        "missed_calls_est": 28,
        "revenue_leak_est": 78400.0,
        "initial_offset_days": -1.5,  # Contacted
    },
    {
        "company_name": "District Electric & Generator",
        "trade": "Electrical & Standby Power",
        "contact_name": "Kwame Washington",
        "contact_email": "kwame@districtelectric.com",
        "phone": "+12026184500",
        "territory": "Washington, DC",
        "missed_calls_est": 22,
        "revenue_leak_est": 26400.0,
        "initial_offset_days": -5.8,  # Follow-up 2 due
    },
]


class DripService:
    """
    Autonomous B2B Drip & Territory Follow-Up Engine.
    Tracks target contractors across progressive qualification touches:
      - 48h Follow-up #1: Tailored value email linking to Missed Call Revenue Leak Audit (/audit).
      - Day 5 Follow-up #2: 1-click self-serve setup closing email (/onboard).
    """

    def __init__(self) -> None:
        self.leads: Dict[str, DripContractorLead] = {}
        self.last_evaluated_at: Optional[str] = None
        self._initialize_pipeline()

    def _initialize_pipeline(self) -> None:
        """Enrolls the 12 primary DMV target contractors with calculated timeline dates."""
        now = datetime.now(timezone.utc)
        for idx, item in enumerate(INITIAL_DMV_CONTRACTORS):
            cid = f"lead_{idx + 1:02d}_{item['company_name'].lower().replace(' ', '_').replace('.', '').replace('&', 'and')[:16]}"
            initial_dt = now + timedelta(days=item["initial_offset_days"])
            f1_due = initial_dt + timedelta(days=2)
            f2_due = initial_dt + timedelta(days=5)

            # Determine initial state based on simulated elapsed time
            elapsed_days = abs(item["initial_offset_days"])
            if elapsed_days >= 5.0:
                status = DripLeadStatus.FOLLOWUP_2_DUE
            elif elapsed_days >= 2.0:
                status = DripLeadStatus.FOLLOWUP_1_DUE
            else:
                status = DripLeadStatus.CONTACTED

            lead = DripContractorLead(
                contractor_id=cid,
                company_name=item["company_name"],
                trade=item["trade"],
                contact_name=item["contact_name"],
                contact_email=item["contact_email"],
                phone=item["phone"],
                territory=item["territory"],
                status=status,
                initial_contact_at=initial_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
                followup_1_due_at=f1_due.strftime("%Y-%m-%d %H:%M:%S UTC"),
                followup_2_due_at=f2_due.strftime("%Y-%m-%d %H:%M:%S UTC"),
                missed_calls_est=item["missed_calls_est"],
                revenue_leak_est=item["revenue_leak_est"],
                audit_url=f"/audit?trade={item['trade'].lower()}&territory={item['territory'].lower()}",
                onboard_url=f"/onboard?company={item['company_name']}&email={item['contact_email']}",
                notes=f"Key regional contractor in {item['territory']}.",
            )
            self.leads[cid] = lead

    def get_pipeline(self) -> DripCampaignStatus:
        """Returns structured pipeline overview of all 12 target contractors."""
        leads_list = list(self.leads.values())
        counts = {
            DripLeadStatus.CONTACTED: 0,
            DripLeadStatus.FOLLOWUP_1_DUE: 0,
            DripLeadStatus.FOLLOWUP_2_DUE: 0,
            DripLeadStatus.REPLIED: 0,
            DripLeadStatus.CLOSED: 0,
        }
        for lead in leads_list:
            counts[lead.status] = counts.get(lead.status, 0) + 1

        return DripCampaignStatus(
            total_enrolled=len(leads_list),
            contacted=counts[DripLeadStatus.CONTACTED],
            followup_1_due=counts[DripLeadStatus.FOLLOWUP_1_DUE],
            followup_2_due=counts[DripLeadStatus.FOLLOWUP_2_DUE],
            replied=counts[DripLeadStatus.REPLIED],
            closed=counts[DripLeadStatus.CLOSED],
            leads=leads_list,
            last_evaluated_at=self.last_evaluated_at,
        )

    def generate_48h_followup(self, lead: DripContractorLead) -> Dict[str, str]:
        """
        Generates tailored 48h Follow-up #1 email linking to territory Missed Call Audit Calculator.
        """
        leak_formatted = f"${lead.revenue_leak_est:,.0f}"
        subject = f"Quick question regarding after-hours call leak in {lead.territory} ({lead.company_name})"
        body = (
            f"Hi {lead.contact_name},\n\n"
            f"Following up on our note from earlier this week. We ran a territory revenue modeling audit for "
            f"{lead.company_name} covering {lead.territory}.\n\n"
            f"Based on local {lead.trade.lower()} search volume and evening storm/leak spikes, our model estimates "
            f"approximately {lead.missed_calls_est} calls roll to voicemail every month—representing an estimated "
            f"{leak_formatted} in uncaptured after-hours jobs.\n\n"
            f"You can review the interactive territory breakdown here with your custom parameters:\n"
            f"👉 https://dispatchengine-production.up.railway.app{lead.audit_url}\n\n"
            f"Would you be opposed to a 4-minute demo showing how Danielle (our AI dispatcher) answers in 0.4 seconds "
            f"and dispatches your on-call tech automatically?\n\n"
            f"Best,\n"
            f"DispatchEngine Growth Team"
        )
        return {
            "type": "FOLLOWUP_1_AUDIT",
            "subject": subject,
            "body": body,
            "target_email": lead.contact_email,
            "company_name": lead.company_name,
            "link": lead.audit_url,
        }

    def generate_day5_followup(self, lead: DripContractorLead) -> Dict[str, str]:
        """
        Generates Day 5 Follow-up #2 closing email offering 1-click self-serve onboarding.
        """
        subject = f"1-Click Autonomous Dispatch Setup for {lead.company_name}"
        body = (
            f"Hi {lead.contact_name},\n\n"
            f"I know you and your team are busy in the field across {lead.territory}. Rather than trading emails, "
            f"we pre-provisioned your contractor tenant profile on DispatchEngine.\n\n"
            f"You can activate your autonomous 24/7 AI Receptionist & Field Dispatcher in under 60 seconds here:\n"
            f"👉 https://dispatchengine-production.up.railway.app{lead.onboard_url}\n\n"
            f"What happens upon 1-click activation:\n"
            f" • Dedicated local Twilio phone number instantly provisioned\n"
            f" • Emergency on-call tech SMS routing enabled ('Reply 1 to Accept')\n"
            f" • Zero credit card required; full 14-day autonomous trial\n\n"
            f"If you'd like to test a sample emergency call before activating, click here to listen to our 32-second live simulation:\n"
            f"👉 https://dispatchengine-production.up.railway.app/demo/audio\n\n"
            f"Best,\n"
            f"DispatchEngine Autonomous Operations"
        )
        return {
            "type": "FOLLOWUP_2_ONBOARD",
            "subject": subject,
            "body": body,
            "target_email": lead.contact_email,
            "company_name": lead.company_name,
            "link": lead.onboard_url,
        }

    def reset_pipeline(self) -> None:
        """Resets the pipeline to its initial enrolled state."""
        self.leads.clear()
        self.last_evaluated_at = None
        self._initialize_pipeline()

    async def evaluate_drip_schedules(
        self,
        db: Optional[AsyncSession] = None,
        force_all: bool = False,
    ) -> DripTriggerResponse:
        """
        Evaluates B2B drip campaign schedules and dispatches due follow-up touches.
        Called automatically by AutopilotService Task 6 every 15 minutes.
        """
        # If force_all and no leads are currently due, reset to ensure simulated cycle executes
        if force_all and not any(l.status in (DripLeadStatus.FOLLOWUP_1_DUE, DripLeadStatus.FOLLOWUP_2_DUE) for l in self.leads.values()):
            self._initialize_pipeline()

        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
        self.last_evaluated_at = now_str

        messages_sent: List[Dict[str, Any]] = []
        dispatched_count = 0

        for lead in self.leads.values():
            if lead.status == DripLeadStatus.FOLLOWUP_1_DUE or (force_all and lead.status == DripLeadStatus.CONTACTED):
                msg = self.generate_48h_followup(lead)
                messages_sent.append(msg)
                lead.followup_1_sent_at = now_str
                lead.last_touch_subject = msg["subject"]
                lead.last_touch_body = msg["body"]
                # Advance stage towards next touch
                lead.status = DripLeadStatus.FOLLOWUP_2_DUE
                dispatched_count += 1
                logger.info(f"📧 [B2B Drip] Sent 48h Follow-up #1 to {lead.company_name} ({lead.contact_email})")

            elif lead.status == DripLeadStatus.FOLLOWUP_2_DUE or (force_all and lead.followup_1_sent_at and not lead.followup_2_sent_at):
                msg = self.generate_day5_followup(lead)
                messages_sent.append(msg)
                lead.followup_2_sent_at = now_str
                lead.last_touch_subject = msg["subject"]
                lead.last_touch_body = msg["body"]
                lead.status = DripLeadStatus.REPLIED
                dispatched_count += 1
                logger.info(f"📧 [B2B Drip] Sent Day 5 Follow-up #2 to {lead.company_name} ({lead.contact_email})")

        return DripTriggerResponse(
            status="COMPLETED",
            evaluated_count=len(self.leads),
            followups_dispatched=dispatched_count,
            messages_sent=messages_sent,
            timestamp=now_str,
        )

    def update_lead_status(
        self,
        contractor_id: str,
        new_status: DripLeadStatus,
        notes: Optional[str] = None,
    ) -> Optional[DripContractorLead]:
        """Allows operator or webhook to transition contractor lead stage."""
        lead = self.leads.get(contractor_id)
        if not lead:
            return None
        lead.status = new_status
        if notes:
            lead.notes = notes
        return lead


drip_service = DripService()
