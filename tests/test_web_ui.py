"""Browser workflow tests for the server-rendered job-board interface."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.dependencies.auth import get_current_user
from app.main import app
from app.models.application import Application
from app.models.listing import Listing
from app.models.subscription import Subscription
from app.models.user import User

ADMIN, GRAD_DCIT, GRAD_OTHER, EMPLOYER, EMPLOYER2 = 1, 2, 3, 4, 5
OPEN_LISTING, PENDING_LISTING = 1, 2


@pytest.fixture
def web_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    for module in ("applications", "listings", "board_auth"):
        monkeypatch.setattr(f"app.services.{module}.engine", engine)

    with Session(engine) as session:
        session.add_all(
            [
                User(username="admin", email="admin@example.com", password="x", role="admin"),
                User(
                    username="grad.dcit",
                    email="grad.dcit@example.com",
                    password="x",
                    role="graduate",
                    programme="DCIT",
                ),
                User(
                    username="grad.other",
                    email="grad.other@example.com",
                    password="x",
                    role="graduate",
                    programme="OTHER",
                ),
                User(
                    username="employer",
                    email="employer@example.com",
                    password="x",
                    role="employer",
                ),
                User(
                    username="employer2",
                    email="employer2@example.com",
                    password="x",
                    role="employer",
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                Listing(
                    employer_id=EMPLOYER,
                    title="Junior Software Engineer",
                    company="Acme Soft",
                    description="Build APIs and small UIs.",
                    apply_mode="collect",
                    deadline="2099-12-31",
                    status="published",
                ),
                Listing(
                    employer_id=EMPLOYER,
                    title="QA Intern",
                    company="Acme Soft",
                    description="Test web applications.",
                    apply_mode="collect",
                    deadline="2099-06-30",
                    status="pending",
                ),
            ]
        )
        session.commit()

    yield engine

    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def client(web_db):
    return TestClient(app)


@pytest.fixture
def login_as(web_db):
    def override(user_id: int) -> None:
        with Session(web_db) as session:
            user = session.get(User, user_id)
        app.dependency_overrides[get_current_user] = lambda: user

    return override


def create_submitted_application(engine) -> int:
    with Session(engine) as session:
        application = Application(
            listing_id=OPEN_LISTING,
            graduate_id=GRAD_DCIT,
            cover_letter="I am interested in this role.",
            resume_text="Graduate resume",
            status="submitted",
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        return application.id


def test_graduate_can_apply_and_view_the_application(client, login_as):
    login_as(GRAD_DCIT)

    jobs_page = client.get("/jobs")
    assert 'action="/subscribe"' in jobs_page.text
    assert f'action="/jobs/{OPEN_LISTING}/apply"' in jobs_page.text

    response = client.post(
        f"/jobs/{OPEN_LISTING}/apply",
        data={"cover_letter": "I am excited to apply."},
    )
    assert response.status_code == 200
    assert str(response.url).endswith("/jobs")

    applications_page = client.get("/applications")
    assert applications_page.status_code == 200
    assert "Junior Software Engineer" in applications_page.text
    assert "Acme Soft" in applications_page.text
    assert "Submitted" in applications_page.text


def test_graduate_can_subscribe_to_job_alerts(client, login_as, web_db):
    login_as(GRAD_DCIT)

    response = client.post("/subscribe")

    assert response.status_code == 200
    assert "Subscribed to job alerts." in response.text
    with Session(web_db) as session:
        assert session.exec(
            select(Subscription).where(Subscription.graduate_id == GRAD_DCIT)
        ).one_or_none()


def test_ineligible_graduate_sees_the_service_error(client, login_as):
    login_as(GRAD_OTHER)

    response = client.post(
        f"/jobs/{OPEN_LISTING}/apply",
        data={"cover_letter": "Please consider my application."},
    )

    assert response.status_code == 200
    assert "only eligible programme graduates may apply" in response.text


def test_employer_can_browse_jobs_without_graduate_actions(client, login_as):
    login_as(EMPLOYER)

    response = client.get("/jobs")

    assert response.status_code == 200
    assert "Junior Software Engineer" in response.text
    assert "Subscribe to job alerts" not in response.text
    assert f"/jobs/{OPEN_LISTING}/apply" not in response.text


def test_employer_can_submit_a_listing(client, login_as):
    login_as(EMPLOYER)

    response = client.post(
        "/listings",
        data={
            "title": "Product Designer",
            "company": "Acme Soft",
            "description": "Design accessible products.",
            "apply_mode": "collect",
            "deadline": "2099-12-31",
            "external_url": "",
        },
    )

    assert response.status_code == 200
    assert "Listing submitted for admin approval." in response.text
    assert "Product Designer" in response.text
    assert "Pending" in response.text


def test_employer_sees_illegal_hire_error_for_submitted_application(
    client, login_as, web_db
):
    application_id = create_submitted_application(web_db)
    login_as(EMPLOYER)

    response = client.post(
        f"/applications/{application_id}/transition",
        data={"action": "hire", "listing_id": OPEN_LISTING},
    )

    assert response.status_code == 200
    assert "cannot hire an application in status submitted" in response.text


def test_employer_can_make_a_legal_application_transition(client, login_as, web_db):
    application_id = create_submitted_application(web_db)
    login_as(EMPLOYER)

    response = client.post(
        f"/applications/{application_id}/transition",
        data={"action": "review", "listing_id": OPEN_LISTING},
    )

    assert response.status_code == 200
    assert "Status changed to reviewed" in response.text
    with Session(web_db) as session:
        assert session.get(Application, application_id).status == "reviewed"


def test_employer_cannot_open_another_employers_applicants(client, login_as):
    login_as(EMPLOYER2)

    response = client.get(f"/listings/{OPEN_LISTING}/applicants")

    assert response.status_code == 200
    assert str(response.url).endswith("/listings")
    assert "forbidden" in response.text


def test_admin_can_publish_a_pending_listing(client, login_as, web_db):
    login_as(ADMIN)

    admin_page = client.get("/admin")
    assert "QA Intern" in admin_page.text
    assert "Publish" in admin_page.text

    response = client.post(f"/admin/listings/{PENDING_LISTING}/publish")

    assert response.status_code == 200
    assert "Published – 0 subscribers notified" in response.text
    with Session(web_db) as session:
        assert session.get(Listing, PENDING_LISTING).status == "published"


def test_admin_can_download_published_listing_applicants(client, login_as, web_db):
    create_submitted_application(web_db)
    login_as(ADMIN)

    response = client.get(f"/admin/listings/{OPEN_LISTING}/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="applicants-{OPEN_LISTING}.json"'
    )
    assert response.json()["package"][0]["graduate_id"] == GRAD_DCIT
