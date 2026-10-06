import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from app.api.v1.dashboard import router as dashboard_router, templates
from app.api.v1.health import router as health_router
from app.api.v1.crews import router as crews_router
from app.api.v1.insurance import router as insurance_router
from app.api.v1.intake import router as intake_router
from app.api.v1.invoice import router as invoice_router
from app.api.v1.material import router as material_router
from app.api.v1.permits import router as permits_router
from app.api.v1.portal import router as portal_router
from app.api.v1.proposal import router as proposal_router
from app.api.v1.reactivation import router as reactivation_router
from app.api.v1.reputation import router as reputation_router
from app.api.v1.track import router as track_router
from app.api.v1.widget import router as widget_router
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
from app.api.v1.demo_call import router as demo_call_router
from app.api.v1.speed_to_lead import router as speed_to_lead_router
from app.api.v1.audit import router as audit_router
from app.api.v1.onboard import router as onboard_router
from app.api.v1.seo import router as seo_router
from app.api.v1.audio_demo import router as audio_demo_router
from app.api.v1.drip import router as drip_router
from app.api.v1.sms_bridge import router as sms_bridge_router
from app.api.v1.insurance_claim import router as insurance_claim_router
from app.api.v1.lockers import router as lockers_router
from app.api.v1.router import api_v1_router
from app.services.autopilot import autopilot_service

from app.core.config import settings
from app.core.logging import logger
from app.db.base import Base
from app.db.session import async_engine, check_db_connection
from app.schemas.common import HealthResponse


def _sync_sqlite_columns(sync_conn):
    """Ensures all columns defined on LeadAction exist in local SQLite tables."""
    try:
        from sqlalchemy import text
        from app.models.lead_action import LeadAction
        target_cols = {col.name: col for col in LeadAction.__table__.columns}
        res = sync_conn.execute(text("PRAGMA table_info(lead_actions)"))
        existing_cols = {r[1] for r in res.fetchall()}
        res.close()
        for col_name in target_cols:
            if col_name not in existing_cols:
                col_type = "FLOAT" if col_name == "trip_mileage" else "JSON"
                try:
                    sync_conn.execute(text(f"ALTER TABLE lead_actions ADD COLUMN {col_name} {col_type}"))
                except Exception as col_err:
                    logger.warning(f"Column {col_name} sync warning: {col_err}")
    except Exception as exc:
        logger.warning(f"SQLite auto-column sync warning: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifespan handler."""
    logger.info(f"Starting {settings.PROJECT_NAME} in [{settings.ENVIRONMENT}] mode...")

    # Ensure database schema exists without blocking container boot
    try:
        if settings.DATABASE_URL.startswith("sqlite"):
            from sqlalchemy import text
            async with async_engine.begin() as conn:
                try:
                    await conn.execute(text("PRAGMA journal_mode=WAL;"))
                    await conn.execute(text("PRAGMA synchronous=NORMAL;"))
                    await conn.execute(text("PRAGMA busy_timeout=30000;"))
                except Exception as pragma_err:
                    logger.warning(f"SQLite PRAGMA warning: {pragma_err}")
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_sync_sqlite_columns)
            logger.info("Local SQLite database schema initialized with WAL mode.")
        else:
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Production database schema synchronized successfully.")
    except Exception as db_init_exc:
        logger.warning(f"Database schema initialization warning (continuing startup): {db_init_exc}")

    # Verify database connection
    try:
        db_alive = await check_db_connection()
        if db_alive:
            logger.info("Database connection established successfully.")
        else:
            logger.warning("Database connection could not be established at startup.")
    except Exception as exc:
        logger.warning(f"Database connection verification warning: {exc}")


    # Start 24/7 Autonomous Autopilot Worker background loop
    stop_event = asyncio.Event()
    worker_task = None
    if settings.ENVIRONMENT != "test":
        worker_task = asyncio.create_task(
            autopilot_service.start_autopilot_background_loop(app, stop_event=stop_event, interval_seconds=900)
        )
        logger.info("24/7 Autonomous Autopilot Worker background loop started.")
    app.state.autopilot_stop_event = stop_event
    app.state.autopilot_task = worker_task

    yield

    # Shut down 24/7 Autonomous Autopilot Worker
    if worker_task:
        logger.info("Shutting down 24/7 Autonomous Autopilot Worker...")
        stop_event.set()
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("24/7 Autonomous Autopilot Worker terminated.")

    logger.info("Shutting down application...")
    await async_engine.dispose()
    logger.info("Database connection pool disposed.")


def create_application() -> FastAPI:
    """FastAPI application factory."""
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        description="High-throughput Multi-Tenant Operations & Dispatch Engine for Webhook Ingestion, LLM Qualification, and CRM Routing.",
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Set up CORS middleware
    if settings.BACKEND_CORS_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Public High-Converting Landing Page
    @application.get(
        "/",
        response_class=HTMLResponse,
        include_in_schema=False,
        summary="Public Product Landing Page",
        description="Renders high-converting public landing page with interactive call splitter demo, ROI table, and FAQ.",
    )
    async def index_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="landing.html",
            context={"project_name": settings.PROJECT_NAME},
        )

    # Mount root /health probe for infrastructure orchestrators (Kubernetes / ECS / Cloud Run)
    application.include_router(health_router, tags=["Health"])

    # Mount operator dashboard directly at /dashboard and simulator
    application.include_router(dashboard_router)

    # Mount client portal router (/portal/{tenant_slug})
    application.include_router(portal_router)

    # Mount multimodal photo intake router (/intake/{action_id})
    application.include_router(intake_router)

    # Mount Good-Better-Best proposal and mobile e-signature router (/proposal/{action_id})
    application.include_router(proposal_router)

    # Mount post-job invoicing and text-to-pay router (/invoice/{action_id})
    application.include_router(invoice_router)

    # Mount will-call material purchase order and profitability router (/po/{action_id})
    application.include_router(material_router)

    # Mount reputation review engine router (/reputation/trigger/{action_id})
    application.include_router(reputation_router)

    # Mount live technician arrival tracker (/track/{action_id})
    application.include_router(track_router)

    # Mount contractor preview demo and widget (/widget-demo)
    application.include_router(widget_router)

    # Mount municipal permit radar portal (/permits/{tenant_slug})
    application.include_router(permits_router)

    # Mount reactivation engine routes
    application.include_router(reactivation_router)

    # Mount insurance claim support dossier (/insurance/{action_id})
    application.include_router(insurance_router)

    # Mount subcontractor crew & 1099 settlement voucher (/crew-voucher/{action_id})
    application.include_router(crews_router)

    # Mount AI Jobsite Safety OSHA Auditor (/safety/{action_id})
    application.include_router(safety_router)

    # Mount Statutory Mechanic's Lien Waiver Engine (/lien-waiver/{action_id})
    application.include_router(legal_router)

    # Mount Hands-Free Voice-to-Job Notes (/track/{action_id}/voice-notes)
    application.include_router(voice_notes_router)

    # Mount Commercial ACORD Certificate of Insurance Guard (/coi/{tenant_slug})
    application.include_router(coi_router)

    # Mount Van Tool & Equipment Asset Scanner (/tools/{tenant_slug})
    application.include_router(tools_router)

    # Mount Agency White-Label & Franchise Management Engine (/agency)
    application.include_router(agency_router)

    # Mount Technician Performance Scorecards & Commissions (/technicians/{tenant_slug})
    application.include_router(technicians_router)

    # Mount Statutory Preliminary Notice & Intent to Lien Guard (/lien-notice/{action_id})
    application.include_router(lien_notice_router)

    # Mount AI Operations Copilot
    application.include_router(copilot_router)

    # Mount Autonomous Equipment Warranty Certificate Engine (/warranty/{action_id})
    application.include_router(warranty_router)

    # Mount IRS Fleet Mileage Tax Ledger (/fleet/mileage/{tenant_slug})
    application.include_router(mileage_router)

    # Mount Customer Neighbor Referral Machine (/refer/{action_id})
    application.include_router(referral_router)

    # Mount 1099-NEC Subcontractor Tax Vault (/tax-vault/{tenant_slug})
    application.include_router(tax_vault_router)

    # Mount Multi-Vehicle Fleet Route Optimizer (/fleet/routes/{tenant_slug})
    application.include_router(routes_router)

    # Mount Utility Rebate Claim Dossier (/rebate/{action_id})
    application.include_router(rebates_router)

    # Mount Field Tech AI Diagnostic Mentor (/tech-mentor/{tenant_slug})
    application.include_router(tech_mentor_router)

    # Mount Commercial Property Manager Multi-Unit Portal (/commercial/{tenant_slug})
    application.include_router(commercial_router)

    # Mount Trade License & Regulatory Compliance Vault (/compliance/{tenant_slug})
    application.include_router(compliance_router)

    # Mount Smart Property IoT Sensor Console (/sensors/{tenant_slug})
    application.include_router(sensors_router)

    # Mount IICRC S500 Water Mitigation Moisture Logs (/mitigation/{action_id})
    application.include_router(mitigation_router)

    # Mount Smart Cancellation Slot Backfill Engine
    application.include_router(backfill_router)

    # Mount Multi-Distributor Supply Arbitrage Comparator (/supply-compare/{action_id})
    application.include_router(supply_compare_router)

    # Mount Multi-Day Jobsite Progress Storyboard (/storyboard/{action_id})
    application.include_router(storyboard_router)

    # Mount Subcontractor Digital W-9 E-Sign Portal (/w9/{tenant_slug}/{crew_name})
    application.include_router(w9_router)

    # Mount Commercial AIA G702/G703 Progress Billing Engine (/pay-app/{action_id})
    application.include_router(pay_app_router)

    # Mount Cross-Trade B2B Partner Exchange & Finder Fee Splitter (/partner-exchange/{tenant_slug})
    application.include_router(partner_exchange_router)

    # Mount Interactive Live Voice Test Call Demo (/demo/call-me)
    application.include_router(demo_call_router)

    # Mount Autonomous Speed-to-Lead Ingestion Engine (/speed-to-lead/{tenant_slug})
    application.include_router(speed_to_lead_router)

    # Mount Missed Call Revenue Leak Audit Calculator (/audit and /audit/{tenant_slug})
    application.include_router(audit_router)

    # Mount Self-Serve Instant Contractor Onboarding & Activation Engine (/onboard)
    application.include_router(onboard_router)

    # Mount Programmatic SEO & Local Organic Lead-Capture Engine (/solutions, /sitemap.xml, /robots.txt)
    application.include_router(seo_router)

    # Mount In-Browser Live Audio Receptionist Simulator (/demo/audio)
    application.include_router(audio_demo_router)

    # Mount Autonomous Insurance Claim Supplement & Xactimate Line-Item Engine (/claims/{action_id}, /claims-vault/{tenant_slug})
    application.include_router(insurance_claim_router)

    # Mount 24/7 Supply House Emergency Locker & After-Hours Parts Reservation Engine (/lockers/{action_id}, /lockers-vault/{tenant_slug})
    application.include_router(lockers_router)

    # Mount API v1 router under /api/v1
    application.include_router(api_v1_router, prefix=settings.API_V1_STR)

    return application



app = create_application()
