"""Server-rendered job-board workflows."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.dependencies.auth import AuthDep
from app.services import applications, board_auth, listings
from app.utilities.flash import flash

from . import templates

router = APIRouter()


def _not_allowed(request: Request) -> RedirectResponse:
    flash(request, "Not allowed", "danger")
    return RedirectResponse("/app", status_code=303)


def _flash_result(
    request: Request, result: dict, success_message: str
) -> None:
    if result.get("ok"):
        flash(request, success_message)
    else:
        flash(request, result.get("error", "Request failed"), "danger")


@router.post("/jobs/{listing_id}/apply")
def apply_to_job(
    listing_id: int,
    request: Request,
    user: AuthDep,
    cover_letter: str = Form(),
):
    if user.role != "graduate":
        return _not_allowed(request)

    result = applications.apply(user.id, listing_id, cover_letter)
    _flash_result(request, result, "Application submitted.")
    return RedirectResponse("/jobs", status_code=303)


@router.post("/subscribe")
def subscribe_to_alerts(request: Request, user: AuthDep):
    if user.role != "graduate":
        return _not_allowed(request)

    result = listings.subscribe(user.id)
    _flash_result(request, result, "Subscribed to job alerts.")
    return RedirectResponse("/jobs", status_code=303)


@router.get("/applications")
def graduate_applications(request: Request, user: AuthDep):
    if user.role != "graduate":
        return _not_allowed(request)

    jobs_by_id = {
        job["id"]: job for job in listings.list_jobs_for_graduates()
    }
    submitted_applications = []
    for application in applications.my_applications(user.id):
        job = jobs_by_id.get(application["listing_id"])
        submitted_applications.append(
            {
                **application,
                "job_title": job["title"] if job else f"Listing #{application['listing_id']}",
                "company": job["company"] if job else "No longer listed",
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="applications.html",
        context={"user": user, "applications": submitted_applications},
    )


@router.get("/listings")
def employer_listings(request: Request, user: AuthDep):
    if user.role != "employer":
        return _not_allowed(request)

    return templates.TemplateResponse(
        request=request,
        name="listings.html",
        context={
            "user": user,
            "listings": listings.list_employer_listings(user.id),
        },
    )


@router.post("/listings")
def submit_employer_listing(
    request: Request,
    user: AuthDep,
    title: str = Form(),
    company: str = Form(),
    description: str = Form(),
    apply_mode: str = Form(),
    deadline: str = Form(),
    external_url: str = Form(default=""),
):
    if user.role != "employer":
        return _not_allowed(request)

    result = listings.submit_listing(
        user.id,
        title,
        company,
        description,
        apply_mode,
        deadline,
        external_url or None,
    )
    _flash_result(request, result, "Listing submitted for admin approval.")
    return RedirectResponse("/listings", status_code=303)


@router.get("/listings/{listing_id}/applicants")
def employer_listing_applicants(
    listing_id: int,
    request: Request,
    user: AuthDep,
):
    if user.role != "employer":
        return _not_allowed(request)

    result = applications.listing_applicants(user.id, listing_id)
    if not result.get("ok"):
        flash(request, result.get("error", "Unable to load applicants"), "danger")
        return RedirectResponse("/listings", status_code=303)

    owned_listing = next(
        (
            listing
            for listing in listings.list_employer_listings(user.id)
            if listing["id"] == listing_id
        ),
        None,
    )
    applicants_with_users = []
    for application in result["applicants"]:
        graduate = board_auth.get_user(application["graduate_id"])
        applicants_with_users.append(
            {
                **application,
                "graduate": graduate,
                "graduate_name": (
                    graduate["username"]
                    if graduate
                    else f"Graduate #{application['graduate_id']}"
                ),
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="applicants.html",
        context={
            "user": user,
            "listing": owned_listing,
            "applicants": applicants_with_users,
        },
    )


@router.post("/applications/{application_id}/transition")
def transition_application(
    application_id: int,
    request: Request,
    user: AuthDep,
    action: str = Form(),
    listing_id: int = Form(),
):
    if user.role != "employer":
        return _not_allowed(request)

    result = applications.transition_application(user.id, application_id, action)
    if result.get("ok"):
        status = result["application"]["status"]
        flash(request, f"Status changed to {status}")
    else:
        flash(request, result.get("error", "Unable to change application status"), "danger")
    return RedirectResponse(
        f"/listings/{listing_id}/applicants",
        status_code=303,
    )


@router.post("/admin/listings/{listing_id}/publish")
def publish_admin_listing(
    listing_id: int,
    request: Request,
    user: AuthDep,
):
    if user.role != "admin":
        return _not_allowed(request)

    result = listings.publish_listing(user.id, listing_id)
    if result.get("ok"):
        flash(request, f"Published – {result['notified']} subscribers notified")
    else:
        flash(request, result.get("error", "Unable to publish listing"), "danger")
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin/listings/{listing_id}/export")
def export_admin_listing(
    listing_id: int,
    request: Request,
    user: AuthDep,
):
    if user.role != "admin":
        return _not_allowed(request)

    result = applications.export_applicants(user.id, listing_id)
    if not result.get("ok"):
        flash(request, result.get("error", "Unable to export applicants"), "danger")
        return RedirectResponse("/admin", status_code=303)

    return JSONResponse(
        content=result,
        headers={
            "Content-Disposition": f'attachment; filename="applicants-{listing_id}.json"'
        },
    )
