from fastapi import Request
from fastapi.responses import HTMLResponse

from app.dependencies.auth import AuthDep
from app.dependencies.session import SessionDep
from app.services.listings import list_jobs_for_graduates

from . import router, templates


@router.get("/jobs", response_class=HTMLResponse, name="jobs_view")
async def jobs_view(
    request: Request,
    user: AuthDep,
):
    jobs = list_jobs_for_graduates()
    for job in jobs:
        external_url = job.get("external_url")
        job["safe_external_url"] = (
            external_url
            if external_url
            and external_url.lower().startswith(("http://", "https://"))
            else None
        )

    return templates.TemplateResponse(
        request=request,
        name="jobs.html",
        context={
            "user": user,
            "jobs": jobs,
        },
    )


@router.get("/app", response_class=HTMLResponse)
async def user_home_view(
    request: Request,
    user: AuthDep,
    db:SessionDep
):
    return templates.TemplateResponse(
        request=request, 
        name="app.html",
        context={
            "user": user
        }
    )