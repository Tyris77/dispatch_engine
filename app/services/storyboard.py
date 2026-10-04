import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.lead_action import LeadAction
from app.models.tenant import Tenant
from app.schemas.storyboard import (
    DailyProgressMilestone,
    JobStoryboardData,
    StoryboardVisionAssessment,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
STORYBOARD_UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads", "storyboard")
PHOTO_NAME_RE = re.compile(r"^day\d{1,3}_\d{1,2}\.(jpg|png)$")
MAX_PHOTOS_PER_DAY = 12

STORYBOARD_PROMPT = """You are a construction project inspector reviewing end-of-day jobsite photos for a homeowner progress report.
Assess: (1) overall job completion percentage (0-100) given the work visible and the previous reported progress,
(2) whether the structure is weather-tight (roof/openings/envelope protected from rain, wind and intrusion) at the end of the day,
(3) a plain-English 1-2 sentence summary for the homeowner. Be conservative: only mark weather_tight true if protection is visible."""

NOT_TIGHT_HINTS = ("no tarp", "exposed", "open roof", "uncovered", "not covered", "left open", "not weather")


async def send_storyboard_sms(to_phone: str, message_body: str) -> bool:
    """Send the daily progress SMS (simulated when Twilio is not configured)."""
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
            logger.error(f"Failed to send storyboard SMS to {to_phone}: {exc}")
            return False
    logger.info(f"[Simulation] Storyboard SMS to {to_phone}: {message_body}")
    return True


def _sniff_ext(data: bytes) -> str:
    return "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"


def _mime_for(ext: str) -> str:
    return "image/png" if ext == "png" else "image/jpeg"


def get_photo_path(action_id: uuid.UUID, filename: str) -> Optional[str]:
    """Resolve a stored photo path. Returns None for invalid names or missing files."""
    if not PHOTO_NAME_RE.match(filename):
        return None
    path = os.path.join(STORYBOARD_UPLOAD_DIR, str(action_id), filename)
    return path if os.path.isfile(path) else None


class StoryboardService:
    """Multi-day jobsite progress storyboard with Gemini Vision assessment."""

    _send_sms = staticmethod(send_storyboard_sms)

    @staticmethod
    def _project_title(lead: LeadAction) -> str:
        diag = lead.diagnostic_data or {}
        contract = lead.signed_contract or {}
        return (
            diag.get("equipment_type")
            or contract.get("tier_title")
            or (lead.qualification_summary or "")[:60]
            or "Home Service Project"
        )

    def build_empty_storyboard(self, lead: LeadAction) -> JobStoryboardData:
        meta = lead.metadata_payload or {}
        days = int(meta.get("estimated_days") or 3)
        return JobStoryboardData(
            action_id=str(lead.id),
            project_title=self._project_title(lead),
            total_days_estimated=max(1, days),
        )

    async def get_storyboard(self, action_id: uuid.UUID, db: AsyncSession) -> Optional[JobStoryboardData]:
        lead = (await db.execute(select(LeadAction).where(LeadAction.id == action_id))).scalar_one_or_none()
        if not lead:
            return None
        if lead.storyboard_data:
            try:
                return JobStoryboardData.model_validate(lead.storyboard_data)
            except Exception as exc:
                logger.warning(f"Invalid storyboard_data for {action_id}: {exc}")
        return self.build_empty_storyboard(lead)

    def _fallback_assessment(
        self, notes: str, prev_pct: int, day_number: int, total_days: int
    ) -> StoryboardVisionAssessment:
        m = re.search(r"(\d{1,3})\s*%", notes or "")
        if m:
            pct = min(100, int(m.group(1)))
        elif day_number >= total_days:
            pct = 100
        else:
            pct = min(100, prev_pct + math.ceil(100 / total_days))
        pct = max(prev_pct, pct)
        lowered = (notes or "").lower()
        tight = not any(h in lowered for h in NOT_TIGHT_HINTS)
        summary = f"Day {day_number}: crew completed the scheduled work ({pct}% complete)."
        if notes:
            summary += f" Foreman: {notes.strip()}"
        return StoryboardVisionAssessment(progress_percentage=pct, weather_tight=tight, summary=summary)

    async def _assess(
        self,
        images: List[bytes],
        notes: str,
        prev_pct: int,
        day_number: int,
        total_days: int,
    ) -> StoryboardVisionAssessment:
        if settings.GEMINI_API_KEY:
            try:
                client = genai.Client(api_key=settings.GEMINI_API_KEY)
                prompt = (
                    f"{STORYBOARD_PROMPT}\n\nDay {day_number} of an estimated {total_days}. "
                    f"Previously reported completion: {prev_pct}%.\nForeman notes: {notes or 'none'}"
                )
                parts = [
                    types.Part.from_bytes(data=b, mime_type=_mime_for(_sniff_ext(b)))
                    for b in images
                ]
                response = await client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[prompt, *parts],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=StoryboardVisionAssessment,
                        temperature=0.1,
                    ),
                )
                if response.text:
                    result = StoryboardVisionAssessment.model_validate_json(response.text)
                    result.progress_percentage = max(prev_pct, result.progress_percentage)
                    return result
            except Exception as exc:
                logger.warning(f"Gemini storyboard vision failed ({exc}); using deterministic fallback.")
        return self._fallback_assessment(notes, prev_pct, day_number, total_days)

    async def add_daily_milestone(
        self,
        action_id: uuid.UUID,
        image_bytes_list: List[bytes],
        notes: str,
        db: AsyncSession,
    ) -> JobStoryboardData:
        """Store the day's photos, assess progress/weather-tightness, and text the homeowner."""
        lead = (await db.execute(select(LeadAction).where(LeadAction.id == action_id))).scalar_one_or_none()
        if not lead:
            raise ValueError(f"LeadAction '{action_id}' not found")

        images = [b for b in (image_bytes_list or []) if b]
        if not images:
            raise ValueError("At least one non-empty photo is required")
        images = images[:MAX_PHOTOS_PER_DAY]

        board = (
            JobStoryboardData.model_validate(lead.storyboard_data)
            if lead.storyboard_data
            else self.build_empty_storyboard(lead)
        )
        day_number = len(board.milestones) + 1
        notes = (notes or "").strip()

        assessment = await self._assess(
            images, notes, board.current_completion_pct, day_number, board.total_days_estimated
        )

        # Persist photos to disk (served by /storyboard/{id}/photo/{filename})
        dest_dir = os.path.join(STORYBOARD_UPLOAD_DIR, str(lead.id))
        os.makedirs(dest_dir, exist_ok=True)
        urls: List[str] = []
        for idx, data in enumerate(images):
            name = f"day{day_number}_{idx}.{_sniff_ext(data)}"
            with open(os.path.join(dest_dir, name), "wb") as fh:
                fh.write(data)
            urls.append(f"/storyboard/{lead.id}/photo/{name}")

        board.milestones.append(
            DailyProgressMilestone(
                day_number=day_number,
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                photo_urls=urls,
                summary=assessment.summary,
                completion_percentage=assessment.progress_percentage,
                weather_tight_verified=assessment.weather_tight,
                customer_notes=notes,
            )
        )
        board.current_completion_pct = assessment.progress_percentage
        board.is_weather_tight = assessment.weather_tight
        if day_number > board.total_days_estimated and board.current_completion_pct < 100:
            board.total_days_estimated = day_number

        lead.storyboard_data = board.model_dump()
        await db.commit()

        await self._notify_homeowner(lead, board, day_number, db)
        return board

    async def _notify_homeowner(
        self, lead: LeadAction, board: JobStoryboardData, day_number: int, db: AsyncSession
    ) -> bool:
        meta = lead.metadata_payload or {}
        phone = meta.get("phone") or meta.get("customer_phone")
        if not phone and (lead.lead_external_id or "").startswith("+"):
            phone = lead.lead_external_id
        if not phone:
            return False
        tenant = (await db.execute(select(Tenant).where(Tenant.id == lead.tenant_id))).scalar_one_or_none()
        base = ((tenant.settings or {}).get("base_url") if tenant else None) or "http://localhost:8000"
        name = tenant.name if tenant else "Your contractor"
        body = (
            f"📸 {name}: Day {day_number} update on your project — {board.current_completion_pct}% complete"
            f"{' and weather-tight' if board.is_weather_tight else ''}. "
            f"See today's photos: {base.rstrip('/')}/storyboard/{lead.id}"
        )
        return await self._send_sms(phone, body)


storyboard_service = StoryboardService()
