"""In-platform conversations for applications and listings."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, or_, select

from app.database import engine
from app.models.application import Application
from app.models.listing import Listing
from app.models.message import Message
from app.models.message_thread import MessageThread
from app.models.user import User
from app.services.applications import owns_listing
from app.services.board_auth import get_user


def _failure(code: str, error: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "error": error}


def _thread_data(thread: MessageThread) -> dict[str, Any]:
    return {
        "id": thread.id,
        "kind": thread.kind,
        "application_id": thread.application_id,
        "listing_id": thread.listing_id,
        "created_at": thread.created_at,
    }


def _thread_access(
    session: Session, user: dict[str, Any], thread: MessageThread
) -> tuple[bool, Application | None, Listing | None]:
    if thread.kind == "application":
        if user["role"] == "admin" or thread.application_id is None:
            return False, None, None
        application = session.get(Application, thread.application_id)
        if application is None:
            return False, None, None
        listing = session.get(Listing, application.listing_id)
        if listing is None:
            return False, application, None
        allowed = (
            user["role"] == "graduate"
            and application.graduate_id == user["id"]
        ) or owns_listing(user, listing)
        return allowed, application, listing

    if thread.kind == "listing":
        listing = session.get(Listing, thread.listing_id)
        if listing is None:
            return False, None, None
        allowed = user["role"] == "admin" or owns_listing(user, listing)
        return allowed, None, listing

    return False, None, None


def _message_data(session: Session, message: Message) -> dict[str, Any]:
    sender = session.get(User, message.sender_id)
    return {
        **message.model_dump(),
        "username": sender.username if sender else f"User #{message.sender_id}",
    }


def application_thread(user_id: int, application_id: int) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        return _failure("forbidden", "unknown user")
    if user["role"] not in {"graduate", "employer"}:
        return _failure("forbidden", "forbidden")

    with Session(engine) as session:
        application = session.get(Application, application_id)
        if application is None:
            return _failure("not_found", "application not found")
        listing = session.get(Listing, application.listing_id)
        if listing is None:
            return _failure("not_found", "listing not found")
        if not (
            (user["role"] == "graduate" and application.graduate_id == user_id)
            or owns_listing(user, listing)
        ):
            return _failure("forbidden", "forbidden")

        thread = session.exec(
            select(MessageThread).where(
                MessageThread.kind == "application",
                MessageThread.application_id == application_id,
            )
        ).one_or_none()
        if thread is None:
            thread = MessageThread(
                kind="application",
                application_id=application_id,
                listing_id=listing.id,
            )
            session.add(thread)
            session.commit()
            session.refresh(thread)

        messages = session.exec(
            select(Message)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at, Message.id)
        ).all()
        other_id = (
            listing.employer_id
            if user["role"] == "graduate"
            else application.graduate_id
        )
        other_user = session.get(User, other_id)
        return {
            "ok": True,
            "thread": _thread_data(thread),
            "messages": [_message_data(session, row) for row in messages],
            "listing": listing.model_dump(),
            "application": application.model_dump(),
            "other_party_name": (
                other_user.username if other_user else f"User #{other_id}"
            ),
        }


def listing_thread(user_id: int, listing_id: int) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        return _failure("forbidden", "unknown user")
    if user["role"] not in {"employer", "admin"}:
        return _failure("forbidden", "forbidden")

    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return _failure("not_found", "listing not found")
        if user["role"] != "admin" and not owns_listing(user, listing):
            return _failure("forbidden", "forbidden")

        thread = session.exec(
            select(MessageThread).where(
                MessageThread.kind == "listing",
                MessageThread.listing_id == listing_id,
            )
        ).one_or_none()
        if thread is None:
            thread = MessageThread(kind="listing", listing_id=listing_id)
            session.add(thread)
            session.commit()
            session.refresh(thread)

        rows = session.exec(
            select(Message)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at, Message.id)
        ).all()
        employer = session.get(User, listing.employer_id)
        return {
            "ok": True,
            "thread": _thread_data(thread),
            "messages": [_message_data(session, row) for row in rows],
            "listing": listing.model_dump(),
            "other_party_name": (
                "Admin"
                if user["role"] == "employer"
                else employer.username if employer else f"User #{listing.employer_id}"
            ),
        }


def send_message(user_id: int, thread_id: int, body: str) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        return _failure("forbidden", "unknown user")

    with Session(engine) as session:
        thread = session.get(MessageThread, thread_id)
        if thread is None:
            return _failure("not_found", "thread not found")
        allowed, _, _ = _thread_access(session, user, thread)
        if not allowed:
            return _failure("forbidden", "forbidden")
        if not body or not body.strip():
            return {
                **_failure("invalid_action", "message cannot be empty"),
                "thread": _thread_data(thread),
            }
        if len(body) > 2000:
            return {
                **_failure("invalid_action", "message must be 2000 characters or fewer"),
                "thread": _thread_data(thread),
            }

        message = Message(thread_id=thread_id, sender_id=user_id, body=body)
        session.add(message)
        session.commit()
        session.refresh(message)
        return {
            "ok": True,
            "thread": _thread_data(thread),
            "message": _message_data(session, message),
        }


def my_threads(user_id: int) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        return _failure("forbidden", "unknown user")

    with Session(engine) as session:
        if user["role"] == "graduate":
            applications = session.exec(
                select(Application).where(Application.graduate_id == user_id)
            ).all()
            app_ids = [application.id for application in applications]
            threads = (
                session.exec(
                    select(MessageThread)
                    .where(
                        MessageThread.kind == "application",
                        MessageThread.application_id.in_(app_ids),
                    )
                    .order_by(MessageThread.created_at.desc(), MessageThread.id.desc())
                ).all()
                if app_ids
                else []
            )
        elif user["role"] == "employer":
            listing_ids = session.exec(
                select(Listing.id).where(Listing.employer_id == user_id)
            ).all()
            app_ids = (
                session.exec(
                    select(Application.id).where(Application.listing_id.in_(listing_ids))
                ).all()
                if listing_ids
                else []
            )
            conditions = []
            if listing_ids:
                conditions.append(
                    (MessageThread.kind == "listing")
                    & MessageThread.listing_id.in_(listing_ids)
                )
            if app_ids:
                conditions.append(
                    (MessageThread.kind == "application")
                    & MessageThread.application_id.in_(app_ids)
                )
            threads = (
                session.exec(
                    select(MessageThread)
                    .where(or_(*conditions))
                    .order_by(MessageThread.created_at.desc(), MessageThread.id.desc())
                ).all()
                if conditions
                else []
            )
        elif user["role"] == "admin":
            threads = session.exec(
                select(MessageThread)
                .where(MessageThread.kind == "listing")
                .order_by(MessageThread.created_at.desc(), MessageThread.id.desc())
            ).all()
        else:
            return _failure("forbidden", "forbidden")

        items = []
        for thread in threads:
            allowed, application, listing = _thread_access(session, user, thread)
            if not allowed:
                continue
            last_message = session.exec(
                select(Message)
                .where(Message.thread_id == thread.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            ).first()
            if thread.kind == "application":
                other_id = (
                    listing.employer_id
                    if user["role"] == "graduate"
                    else application.graduate_id
                )
                other_user = session.get(User, other_id)
                other_party_name = other_user.username if other_user else f"User #{other_id}"
                title = listing.title
            else:
                if user["role"] == "admin":
                    other_id = listing.employer_id
                    other_user = session.get(User, other_id)
                    other_party_name = other_user.username if other_user else f"User #{other_id}"
                else:
                    other_party_name = "Admin"
                title = listing.title
            items.append(
                {
                    **_thread_data(thread),
                    "title": title,
                    "other_party_name": other_party_name,
                    "last_message": (
                        _message_data(session, last_message) if last_message else None
                    ),
                }
            )
        return {"ok": True, "threads": items}
