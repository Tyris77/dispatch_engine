from fastapi import APIRouter
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.events import router as events_router
from app.api.v1.health import router as health_router
from app.api.v1.insurance import router as insurance_router
from app.api.v1.intake import router as intake_router
from app.api.v1.invoice import router as invoice_router
from app.api.v1.material import router as material_router
from app.api.v1.permits import router as permits_router
from app.api.v1.proposal import router as proposal_router
from app.api.v1.reactivation import router as reactivation_router
from app.api.v1.reputation import router as reputation_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.track import router as track_router
from app.api.v1.weather import router as weather_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.widget import router as widget_router
from app.api.v1.crews import router as crews_router
from app.api.v1.safety import router as safety_router
from app.api.v1.legal import router as legal_router
from app.api.v1.voice_notes import router as voice_notes_router
from app.api.v1.coi import router as coi_router
from app.api.v1.tools import router as tools_router
from app.api.v1.agency import router as agency_router
from app.api.v1.technicians import router as technicians_router
from app.api.v1.lien_notice import router as lien_notice_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.warranty import router as warranty_router
from app.api.v1.mileage import router as mileage_router
from app.api.v1.referral import router as referral_router
from app.api.v1.tax_vault import router as tax_vault_router
from app.api.v1.routes import router as routes_router
from app.api.v1.rebates import router as rebates_router
from app.api.v1.tech_mentor import router as tech_mentor_router
from app.api.v1.commercial import router as commercial_router
from app.api.v1.compliance import router as compliance_router
from app.api.v1.sensors import router as sensors_router
from app.api.v1.mitigation import router as mitigation_router
from app.api.v1.backfill import router as backfill_router
from app.api.v1.supply_compare import router as supply_compare_router
from app.api.v1.storyboard import router as storyboard_router
from app.api.v1.w9 import router as w9_router
from app.api.v1.pay_app import router as pay_app_router
from app.api.v1.partner_exchange import router as partner_exchange_router
from app.api.v1.autopilot import router as autopilot_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router, tags=["Health"])
api_v1_router.include_router(dashboard_router, tags=["Dashboard & Simulator"])
api_v1_router.include_router(tenants_router, prefix="/tenants", tags=["Tenants"])
api_v1_router.include_router(webhooks_router, prefix="/webhooks", tags=["Webhooks"])
api_v1_router.include_router(events_router, prefix="/events", tags=["Events & Dispatch"])
api_v1_router.include_router(intake_router, tags=["Vision Intake"])
api_v1_router.include_router(proposal_router, tags=["Proposal & E-Signature"])
api_v1_router.include_router(invoice_router, tags=["Invoicing & Text-to-Pay"])
api_v1_router.include_router(material_router, tags=["Material & Will-Call PO"])
api_v1_router.include_router(insurance_router, tags=["Insurance Claim Dossier"])
api_v1_router.include_router(crews_router, tags=["Subcontractor Crew Ledger"])
api_v1_router.include_router(safety_router, tags=["AI Jobsite Safety OSHA Auditor"])
api_v1_router.include_router(legal_router, tags=["Statutory Mechanic's Lien Waiver Engine"])
api_v1_router.include_router(voice_notes_router, tags=["Hands-Free Voice-to-Job Notes"])
api_v1_router.include_router(coi_router, tags=["Commercial ACORD Certificate of Insurance (COI) Guard"])
api_v1_router.include_router(tools_router, tags=["Van Tool & Equipment Asset Scanner"])
api_v1_router.include_router(agency_router, tags=["Agency White-Label & Franchise Management Engine"])
api_v1_router.include_router(technicians_router, tags=["Technician Performance Scorecards & Commissions"])
api_v1_router.include_router(lien_notice_router, tags=["Statutory Preliminary Notice & Intent to Lien Guard"])
api_v1_router.include_router(copilot_router, tags=["AI Operations Copilot"])
api_v1_router.include_router(warranty_router, tags=["Autonomous Equipment Warranty Certificate Engine"])
api_v1_router.include_router(mileage_router, tags=["IRS Fleet Mileage Tax Ledger"])
api_v1_router.include_router(referral_router, tags=["Customer Neighbor Referral Engine"])
api_v1_router.include_router(tax_vault_router, tags=["1099-NEC Subcontractor Tax Vault"])
api_v1_router.include_router(weather_router, tags=["Severe Weather Radar"])
api_v1_router.include_router(reputation_router, tags=["Reputation & Reviews"])
api_v1_router.include_router(reactivation_router, tags=["Reactivation Engines"])
api_v1_router.include_router(permits_router, tags=["Municipal Permit Radar"])
api_v1_router.include_router(widget_router, tags=["Widget & Chat"])
api_v1_router.include_router(track_router, tags=["Tech Tracking"])
api_v1_router.include_router(routes_router, tags=["Multi-Vehicle Fleet Route Optimizer"])
api_v1_router.include_router(rebates_router, tags=["Utility Rebate & Federal IRA Tax Credit Engine"])
api_v1_router.include_router(tech_mentor_router, tags=["Field Tech AI Diagnostic Mentor & Fault Code Copilot"])
api_v1_router.include_router(commercial_router, tags=["Commercial Property Manager Multi-Unit Portal"])
api_v1_router.include_router(compliance_router, tags=["Trade License & Regulatory Compliance Vault"])
api_v1_router.include_router(sensors_router, tags=["Smart IoT Sensor Ingestion & Emergency Dispatch"])
api_v1_router.include_router(mitigation_router, tags=["IICRC S500 Water Mitigation & Psychrometric Drying Log Engine"])
api_v1_router.include_router(backfill_router, tags=["Smart Cancellation Slot Backfill Engine"])
api_v1_router.include_router(supply_compare_router, tags=["Multi-Distributor Supply Arbitrage Comparator"])
api_v1_router.include_router(storyboard_router, tags=["Multi-Day Jobsite Progress Storyboard"])
api_v1_router.include_router(w9_router, tags=["Subcontractor Digital W-9 E-Sign Portal"])
api_v1_router.include_router(pay_app_router, tags=["Commercial AIA G702/G703 Progress Billing Engine"])
api_v1_router.include_router(partner_exchange_router, tags=["Cross-Trade B2B Partner Exchange & Finder Fee Splitter"])
api_v1_router.include_router(autopilot_router, tags=["24/7 Autonomous Autopilot Worker"])





