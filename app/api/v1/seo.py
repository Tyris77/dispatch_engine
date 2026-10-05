import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse, Response as FastAPIResponse
from fastapi.templating import Jinja2Templates
from app.services.seo import SEOService, TRADES, HUBS

router = APIRouter(tags=["Programmatic SEO & Local Organic Lead-Capture Engine"])

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get(
    "/solutions",
    response_class=HTMLResponse,
    summary="Solutions Directory Hub",
    description="Index directory linking all 48 localized trade x metropolitan hub landing pages for contractor search equity.",
)
async def get_solutions_directory(request: Request) -> FastAPIResponse:
    matrix = SEOService.get_matrix_by_category()
    return templates.TemplateResponse(
        request=request,
        name="solutions_hub.html",
        context={"matrix": matrix},
    )


@router.get(
    "/solutions/{slug}",
    response_class=HTMLResponse,
    summary="Programmatic Trade x City Landing Page",
    description="Render optimized programmatic landing page with localized metrics, voice demo widget, and revenue leak calculator.",
)
async def get_solution_landing_page(slug: str, request: Request) -> FastAPIResponse:
    base_url = str(request.base_url).rstrip("/")
    page_data = SEOService.get_page_data(slug, base_url=base_url)
    if not page_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Solution page '{slug}' not found in the 48-page DMV matrix.",
        )

    return templates.TemplateResponse(
        request=request,
        name="seo_landing.html",
        context={"page": page_data},
    )


@router.get(
    "/sitemap.xml",
    summary="RFC-Compliant XML Sitemap",
    description="Dynamically generates search-engine sitemap with all 48 localized solution pages, core conversion tools, and root pages.",
)
async def get_sitemap_xml(request: Request) -> FastAPIResponse:
    base_url = str(request.base_url).rstrip("/")
    xml_content = SEOService.generate_sitemap_xml(base_url=base_url)
    return FastAPIResponse(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Type": "application/xml; charset=utf-8"},
    )


@router.get(
    "/robots.txt",
    response_class=PlainTextResponse,
    summary="Robots.txt Directive File",
    description="Standard crawler directives indexing sitemap.xml and shielding internal API endpoints.",
)
async def get_robots_txt(request: Request) -> PlainTextResponse:
    base_url = str(request.base_url).rstrip("/")
    txt_content = SEOService.generate_robots_txt(base_url=base_url)
    return PlainTextResponse(
        content=txt_content,
        media_type="text/plain",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )


@router.get(
    "/api/v1/seo/matrix",
    summary="SEO Matrix Schema & Stats",
    description="Returns programmatic SEO coverage statistics and categorized matrix breakdown.",
)
async def get_seo_matrix() -> Dict[str, Any]:
    return SEOService.get_matrix_by_category()
