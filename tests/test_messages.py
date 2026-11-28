"""Browser and service tests for application and listing conversations."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.dependencies.auth import get_current_user
from app.main import app
from app.models.application import Application
from app.models.listing import Listing
from app.models.user import User

ADMIN, GRADUATE, EMPLOYER, EMPLOYER2 = 1, 2, 3, 4
LISTING_ID = 1


@pytest.fixture
def messages_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    for module in ("applications", "board_auth", "messages"):
        monkeypatch.setattr(f"app.services.{module}.engine", engine)

    with Session(engine) as session:
        session.add_all(
            [
                User(username="admin", email="admin@example.com", password="x", role="admin"),
                User(username="graduate", email="graduate@example.com", password="x", role="graduate"),
                User(username="employer", email="employer@example.com", password="x", role="employer"),
                User(username="employer2", email="employer2@example.com", password="x", role="employer"),
            ]
        )
        session.commit()
        session.add(
            Listing(
                employer_id=EMPLOYER,
                title="Software Engineer",
                company="Acme",
                description="Build software.",
                apply_mode="collect",
                deadline="2099-12-31",
                status="published",
            )
        )
        session.commit()
        application = Application(
            listing_id=LISTING_ID,
            graduate_id=GRADUATE,
            cover_letter="Interested.",
            resume_text="Experience.",
            status="submitted",
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        application_id = application.id

    yield engine, application_id

    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def client(messages_db):
    return TestClient(app)


@pytest.fixture
def login_as(messages_db):
    engine, _ = messages_db

    def override(user_id: int) -> None:
        with Session(engine) as session:
            user = session.get(User, user_id)
        app.dependency_overrides[get_current_user] = lambda: user

    return override


def thread_form_action(page_text: str) -> str:
    thread_id = page_text.split('action="/messages/')[1].split('"')[0]
    return f"/messages/{thread_id}"


def test_graduate_and_listing_employer_exchange_application_messages(
    client, login_as, messages_db
):
    _, application_id = messages_db
    login_as(GRADUATE)
    graduate_page = client.get(f"/messages/application/{application_id}")
    assert graduate_page.status_code == 200
    assert "Software Engineer" in graduate_page.text
    sent = client.post(
        thread_form_action(graduate_page.text),
        data={"body": "Could you share more details?"},
        follow_redirects=False,
    )
    assert sent.status_code == 303
    assert sent.headers["location"] == f"application/{application_id}"

    login_as(EMPLOYER)
    employer_page = client.get(f"/messages/application/{application_id}")
    assert "graduate" in employer_page.text
    assert "Could you share more details?" in employer_page.text
    response = client.post(
        thread_form_action(employer_page.text),
        data={"body": "Please describe your experience."},
    )
    assert response.status_code == 200

    login_as(GRADUATE)
    conversation = client.get(f"/messages/application/{application_id}")
    assert "Please describe your experience." in conversation.text
    assert "employer" in conversation.text


@pytest.mark.parametrize("user_id", [EMPLOYER2, ADMIN])
def test_other_employer_and_admin_cannot_open_application_thread(
    client, login_as, messages_db, user_id
):
    _, application_id = messages_db
    login_as(GRADUATE)
    client.get(f"/messages/application/{application_id}")

    login_as(user_id)
    response = client.get(f"/messages/application/{application_id}")
    assert response.status_code == 200
    assert str(response.url).endswith("/app")
    assert "forbidden" in response.text


def test_listing_employer_and_admin_exchange_messages_but_other_employer_cannot(
    client, login_as
):
    login_as(EMPLOYER2)
    denied = client.get(f"/messages/listing/{LISTING_ID}")
    assert str(denied.url).endswith("/app")
    assert "forbidden" in denied.text

    login_as(EMPLOYER)
    employer_page = client.get(f"/messages/listing/{LISTING_ID}")
    assert employer_page.status_code == 200
    sent = client.post(
        thread_form_action(employer_page.text),
        data={"body": "Please review this listing."},
        follow_redirects=False,
    )
    assert sent.status_code == 303
    assert sent.headers["location"] == f"listing/{LISTING_ID}"

    login_as(ADMIN)
    admin_page = client.get(f"/messages/listing/{LISTING_ID}")
    assert "Please review this listing." in admin_page.text
    sent = client.post(
        thread_form_action(admin_page.text),
        data={"body": "Please clarify the pay range."},
    )
    assert sent.status_code == 200

    login_as(EMPLOYER)
    assert "Please clarify the pay range." in client.get(
        f"/messages/listing/{LISTING_ID}"
    ).text


def test_empty_message_is_refused_and_graduate_sees_application_in_inbox(
    client, login_as, messages_db
):
    _, application_id = messages_db
    login_as(GRADUATE)
    page = client.get(f"/messages/application/{application_id}")
    response = client.post(
        thread_form_action(page.text), data={"body": " \n "}
    )
    assert "message cannot be empty" in response.text
    response = client.post(
        thread_form_action(page.text), data={"body": "x" * 2001}
    )
    assert "message must be 2000 characters or fewer" in response.text

    response = client.get("/messages")
    assert response.status_code == 200
    assert f"/messages/application/{application_id}" in response.text
