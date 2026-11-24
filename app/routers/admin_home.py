from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies.auth import AuthDep
from app.services.listings import list_jobs_for_graduates, list_pending_for_admin
from app.utilities.flash import flash

from . import router, templates


@router.get("/admin", response_class=HTMLResponse)
async def admin_home_view(
    request: Request,
    user: AuthDep,
):
    if user.role != "admin":
        flash(request, "Not allowed", "danger")
        return RedirectResponse("/app", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "user": user,
            "pending_listings": list_pending_for_admin(),
            "published_listings": list_jobs_for_graduates(),
        }
    )
