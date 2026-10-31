"""State transitions for bookings.

HTTP handlers delegate here so cancellation, archiving and status changes keep
the same validation and audit behaviour regardless of the entry point.
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session, joinedload

from ..models import Booking, BookingAttachment, BookingDeletion, User
from ..timeutils import local_now, utc_now
from .bookings import find_conflict, record_event, reject_competing_requests
from .booking_locks import lock_booking_record, lock_booking_rows
from .approval_validation import validate_approval_conditions
from .work_calendar import review_info


CLOSED_BOOKING_STATUSES = frozenset({
    "cancelled", "cancelled_by_user", "cancelled_by_admin",
    "rejected", "completed", "no_show", "transferred",
})


def expire_pending_requests(db: Session) -> int:
    """Bring records in line with the clock in a dedicated worker transaction.

    Unreviewed requests expire after seven working days (or event start).
    Confirmed bookings whose time has passed are
    marked as completed, so the lists do not keep stale "confirmed" records.
    """
    local = local_now()
    today, current = local.date(), local.time()
    now = utc_now()
    finished = or_(Booking.date < today, and_(Booking.date == today, Booking.time_end <= current))
    expired = list(db.scalars(select(Booking).options(joinedload(Booking.owner)).where(
        Booking.status == "pending",
    ).with_for_update(of=Booking, skip_locked=True).execution_options(populate_existing=True)))
    for booking in expired:
        deadline = review_info(booking.created_at, local)
        if not deadline.get("review_overdue") and not event_started(booking):
            continue
        booking.status = "rejected"
        booking.archived_at = now
        booking.archived_by_id = None
        booking.updated_at = now
        booking.decision_at = now
        booking.decision_reason = "Не подтверждена: истёк срок рассмотрения заявки"
        booking.hold_expires_at = None
        record_event(
            db, booking, booking.owner, "expired", booking.decision_reason,
            {"system": True, "previous_status": "pending"},
        )
    completed = list(db.scalars(select(Booking).options(joinedload(Booking.owner)).where(
        Booking.status == "approved", Booking.record_kind == "booking", finished,
    ).with_for_update(of=Booking, skip_locked=True).execution_options(populate_existing=True)))
    for booking in completed:
        booking.status = "completed"
        booking.updated_at = now
        record_event(
            db, booking, booking.owner, "completed", "Мероприятие завершено",
            {"system": True, "previous_status": "approved"},
        )
    if any(booking.status == "rejected" for booking in expired) or completed:
        db.commit()
    return sum(booking.status == "rejected" for booking in expired)

STATUS_SUMMARIES = {
    "approved": "Бронирование подтверждено",
    "rejected": "Заявка отклонена",
    "completed": "Мероприятие состоялось",
    "no_show": "Заказчик не пришёл",
}

ALLOWED_STATUS_TRANSITIONS = {
    "pending": {"approved", "rejected"},
    "approved": {"completed", "no_show"},
    # Past bookings are completed automatically; the administrator can still correct the outcome.
    "completed": {"no_show"},
    "no_show": {"completed"},
}


def event_started(booking: Booking) -> bool:
    now = local_now()
    return booking.date < now.date() or (booking.date == now.date() and booking.time_start <= now.time())


def event_finished(booking: Booking) -> bool:
    now = local_now()
    return booking.date < now.date() or (booking.date == now.date() and booking.time_end <= now.time())


def get_booking_or_404(db: Session, booking_id: int) -> Booking:
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Бронирование не найдено")
    return booking


def ensure_booking_open(booking: Booking) -> None:
    if booking.status in CLOSED_BOOKING_STATUSES:
        raise HTTPException(409, "Бронирование уже закрыто")


def cancel_booking_record(
    db: Session,
    booking: Booking,
    actor: User,
    *,
    reason: str,
    comment: str,
    replacement_offered: bool,
    notify_customer: bool,
) -> None:
    booking = lock_booking_record(db, booking)
    ensure_booking_open(booking)
    if actor.role != "admin" and event_started(booking):
        raise HTTPException(409, "Мероприятие уже началось — отменить его нельзя")
    _apply_cancellation(db, booking, actor, reason=reason, comment=comment,
                        replacement_offered=replacement_offered, notify_customer=notify_customer)
    # Cancelling the main room cancels the whole set; an extra room can be cancelled alone.
    if not booking.parent_booking_id:
        from .room_sets import extra_rooms_of
        for extra in extra_rooms_of(db, booking, open_only=True):
            if actor.role == "admin" or not event_started(extra):
                _apply_cancellation(db, extra, actor, reason=reason, comment=comment,
                                    replacement_offered=replacement_offered, notify_customer=notify_customer)
    db.commit()


def _apply_cancellation(
    db: Session, booking: Booking, actor: User, *, reason: str, comment: str,
    replacement_offered: bool, notify_customer: bool,
) -> None:
    booking.status = "cancelled_by_admin" if actor.role == "admin" else "cancelled_by_user"
    booking.cancelled_at = utc_now()
    booking.cancelled_by_id = actor.id
    booking.cancellation_reason = reason.strip()
    booking.cancellation_comment = comment.strip()
    booking.replacement_offered = replacement_offered
    booking.notify_customer = notify_customer
    record_event(
        db, booking, actor, booking.status, "Бронирование отменено",
        {
            "reason": booking.cancellation_reason,
            "comment": booking.cancellation_comment,
            "replacement_offered": replacement_offered,
            "notify_customer": notify_customer,
        },
    )


def cancel_series_records(
    db: Session,
    series_id: str,
    actor: User,
    *,
    reason: str,
    comment: str,
    replacement_offered: bool,
    notify_customer: bool,
) -> int:
    """Cancel every open date of a series in one transaction.

    Dates that are already closed are skipped, so a repeated request does not
    fail halfway. A user cannot cancel dates that have already started.
    """
    stmt = select(Booking).where(Booking.series_id == series_id, Booking.status.not_in(CLOSED_BOOKING_STATUSES))
    if actor.role != "admin":
        stmt = stmt.where(Booking.owner_id == actor.id)
    items = [item for item in lock_booking_rows(db, stmt.order_by(Booking.id))
             if actor.role == "admin" or not event_started(item)]
    if not items:
        raise HTTPException(409, "В серии не осталось дат, которые можно отменить")
    for item in items:
        _apply_cancellation(db, item, actor, reason=reason, comment=comment,
                            replacement_offered=replacement_offered, notify_customer=notify_customer)
    db.commit()
    return len(items)


def set_booking_archived(db: Session, booking: Booking, actor: User, archived: bool, *, commit: bool = True) -> None:
    now = local_now()
    event_finished = booking.date < now.date() or (booking.date == now.date() and booking.time_end <= now.time())
    if archived and booking.status not in CLOSED_BOOKING_STATUSES and not event_finished:
        raise HTTPException(409, "В архив можно переносить только завершённые, отменённые или прошедшие бронирования")
    booking.archived_at = utc_now() if archived else None
    booking.archived_by_id = actor.id if archived else None
    event_type = "archived" if archived else "restored_from_archive"
    summary = "Бронирование перенесено в архив" if archived else "Бронирование восстановлено из архива"
    record_event(db, booking, actor, event_type, summary)
    if commit:
        db.commit()


def set_bookings_archived(db: Session, booking_ids: list[int], actor: User, archived: bool) -> int:
    """Archive or restore several records (the dates of a series card) at once: all change or none."""
    items = list(db.scalars(select(Booking).where(Booking.id.in_(booking_ids)).order_by(Booking.date, Booking.time_start)))
    if len(items) != len(set(booking_ids)):
        raise HTTPException(404, "Часть бронирований не найдена — обновите страницу")
    changed = 0
    for item in items:
        if (item.archived_at is not None) == archived:
            continue
        set_booking_archived(db, item, actor, archived, commit=False)
        changed += 1
    db.commit()
    return changed


def _deletion_snapshot(item: Booking) -> dict:
    """Plain copy of the record and its history, readable without the deleted rows."""
    def plain(value):
        return value.isoformat() if hasattr(value, "isoformat") else value
    data = {column.name: plain(getattr(item, column.key)) for column in Booking.__table__.columns
            if hasattr(item, column.key)}
    data["events"] = [{"type": event.event_type, "summary": event.summary, "actor_id": event.actor_id,
                       "created_at": plain(event.created_at), "data": event.data} for event in item.events]
    data["comments"] = [{"author_id": comment.author_id, "text": comment.text, "created_at": plain(comment.created_at)}
                        for comment in item.comments]
    return data


def delete_booking_records(db: Session, booking_ids: list[int], actor: User | None = None) -> list[str]:
    """Delete several erroneous records (for example all dates of a series) in one transaction.

    Returns the stored names of their files so the caller can remove files nobody
    references any more. Files attached to a whole series go only when no date of
    that series is left.
    """
    items = list(db.scalars(select(Booking).where(Booking.id.in_(booking_ids))))
    if len(items) != len(set(booking_ids)):
        raise HTTPException(404, "Часть бронирований не найдена — обновите страницу")
    ids = {item.id for item in items}
    extras = list(db.scalars(select(Booking).where(Booking.parent_booking_id.in_(ids), Booking.id.not_in(ids))))
    ids |= {item.id for item in extras}
    # Links between the deleted records are fine; a record that stays and depends on one blocks the deletion.
    if db.scalar(select(Booking.id).where(Booking.previous_booking_id.in_(ids), Booking.id.not_in(ids)).limit(1)):
        raise HTTPException(409, "Удалить нельзя: с одной из записей связана перенесённая бронь")
    outside_previous = [item.previous_booking_id for item in items if item.previous_booking_id and item.previous_booking_id not in ids]
    if outside_previous and db.scalar(select(Booking.id).where(Booking.id.in_(outside_previous), Booking.status == "transferred").limit(1)):
        raise HTTPException(409, "Одна из записей создана переносом — её нельзя удалить, её можно отменить")
    series_ids = {item.series_id for item in items if item.series_id}
    emptied = {series_id for series_id in series_ids if not db.scalar(select(Booking.id).where(
        Booking.series_id == series_id, Booking.id.not_in(ids)).limit(1))}
    attachment_scope = BookingAttachment.booking_id.in_(ids)
    if emptied:
        attachment_scope = or_(attachment_scope, and_(BookingAttachment.series_id.in_(emptied), BookingAttachment.booking_id.is_(None)))
    stored = list(db.scalars(select(BookingAttachment.stored_name).where(attachment_scope)))
    if emptied:
        db.execute(BookingAttachment.__table__.delete().where(
            BookingAttachment.series_id.in_(emptied), BookingAttachment.booking_id.is_(None)))
    for item in [*items, *extras]:
        db.add(BookingDeletion(booking_id=item.id, deleted_by_id=actor.id if actor else None,
                               snapshot=_deletion_snapshot(item)))
    for item in [*items, *extras]:
        item.previous_booking_id = None
        item.parent_booking_id = None
    db.flush()
    for item in [*extras, *items]:
        db.delete(item)
    db.commit()
    return stored


def delete_booking_record(db: Session, booking: Booking) -> None:
    """Permanently remove an erroneous standalone record.

    Records referenced by a transfer must remain available as part of the
    transfer history. Related comments and audit rows are removed by cascade.
    """
    dependent_id = db.scalar(select(Booking.id).where(Booking.previous_booking_id == booking.id).limit(1))
    if dependent_id:
        raise HTTPException(409, "Эту запись нельзя удалить: с ней связана перенесённая бронь")
    # The replacement of a transfer is what the original "transferred" record points people to;
    # removing it would leave the original claiming a move that no longer exists.
    if getattr(booking, "previous_booking_id", None):
        previous = db.get(Booking, booking.previous_booking_id)
        if previous and previous.status == "transferred":
            raise HTTPException(409, "Эту бронь создал перенос — её нельзя удалить. Отмените её, если мероприятие не состоится")
    # Extra rooms exist only as part of the set, so they are removed with the main record.
    if db.scalar(select(Booking.id).where(Booking.parent_booking_id == booking.id).limit(1)):
        for extra in db.scalars(select(Booking).where(Booking.parent_booking_id == booking.id)):
            db.delete(extra)
        db.flush()
    db.delete(booking)
    db.commit()


def transition_booking_status(
    db: Session, booking: Booking, actor: User, status: str, reason: str | None = None,
) -> None:
    booking = lock_booking_record(db, booking)
    if status not in ALLOWED_STATUS_TRANSITIONS.get(booking.status, set()):
        raise HTTPException(409, "Недопустимый переход статуса бронирования")
    if booking.status == "pending" and review_info(booking.created_at, local_now()).get("review_overdue"):
        raise HTTPException(409, "Срок рассмотрения заявки истёк. Заявка будет перенесена в архив")
    if status == "completed" and not event_finished(booking):
        raise HTTPException(409, "Отметить «Состоялось» можно только после планового окончания мероприятия")
    if status == "no_show" and not event_started(booking):
        raise HTTPException(409, "Отметить «Неявка» можно только после начала мероприятия")
    if status == "rejected":
        reason = (reason or "").strip()
    if status == "approved":
        lock_key = booking.date.toordinal() * 100000 + booking.room_id
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        conflict = find_conflict(
            db, booking.room_id, booking.date, booking.time_start, booking.time_end, booking.id,
        )
        if conflict:
            raise HTTPException(409, "Подтверждение невозможно: аудитория уже занята")
    if status == "rejected" and not reason:
        raise HTTPException(400, "Укажите причину отказа")
    from .room_sets import decide_extra_rooms, ensure_extra_can_be_approved_alone, ensure_set_can_be_approved, extra_rooms_of
    set_extras = []
    if previous_is_pending := booking.status == "pending":
        if status == "approved" and booking.parent_booking_id:
            ensure_extra_can_be_approved_alone(db, booking)
        if not booking.parent_booking_id and status == "approved":
            set_extras = ensure_set_can_be_approved(db, booking)
        elif not booking.parent_booking_id and status == "rejected":
            set_extras = [item for item in extra_rooms_of(db, booking) if item.status == "pending"]
    if status == "approved":
        validate_approval_conditions(db, [booking, *set_extras])
    previous = booking.status
    booking.status = status
    booking.updated_at = utc_now()
    if status in {"approved", "rejected"}:
        booking.decision_at = utc_now()
        booking.decided_by_id = actor.id
        booking.decision_reason = reason.strip() if reason else None
        booking.hold_expires_at = None
    record_event(
        db, booking, actor, status, STATUS_SUMMARIES[status],
        {"previous_status": previous, "reason": reason, **({"set_id": booking.id} if set_extras else {})},
    )
    if status == "approved":
        reject_competing_requests(db, booking, actor)
    if previous_is_pending and set_extras:
        decide_extra_rooms(db, set_extras, actor, status, reason, booking)
    db.commit()


SERIES_DATE_BUSY_REASON = "Аудитория в эту дату уже занята"


def transition_series_status(
    db: Session, series_id: str, actor: User, status: str, reason: str | None = None,
    skip_conflicts: bool = False,
) -> int:
    """Approve or reject every pending request of a series in one transaction.

    With `skip_conflicts` the free dates are approved and the busy ones are
    rejected, so one taken date does not block the whole series.
    """
    if status not in {"approved", "rejected"}:
        raise HTTPException(400, "Для серии доступно только подтверждение или отказ")
    if status == "rejected" and not (reason and reason.strip()):
        raise HTTPException(400, "Укажите причину отказа")
    items = lock_booking_rows(db, select(Booking).options(joinedload(Booking.room)).where(
        Booking.series_id == series_id, Booking.status == "pending",
    ).order_by(Booking.date, Booking.time_start, Booking.id))
    if not items:
        raise HTTPException(404, "В серии нет заявок, ожидающих решения")
    if any(review_info(item.created_at, local_now()).get("review_overdue") for item in items):
        raise HTTPException(409, "Срок рассмотрения серии истёк. Заявки будут перенесены в архив")
    if status == "approved":
        # The periodic worker owns automatic expiry. Decide only future dates;
        # do not change unrelated/past requests as a side effect of this command.
        items = [item for item in items if not event_started(item)]
        if not items:
            raise HTTPException(409, "Время всех мероприятий серии уже наступило — подтвердить их нельзя")
    busy: list[Booking] = []
    if status == "approved":
        problems = []
        for booking in items:
            lock_key = booking.date.toordinal() * 100000 + booking.room_id
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
            if find_conflict(db, booking.room_id, booking.date, booking.time_start, booking.time_end, booking.id):
                busy.append(booking)
                problems.append(f"{booking.date.strftime('%d.%m.%Y')}, ауд. {booking.room.number}")
        # Skipping occupied dates never bypasses current room/time/capacity rules.
        validate_approval_conditions(db, items)
        if busy and skip_conflicts and len(busy) < len(items):
            problems = []
        if problems:
            more = f" и ещё {len(problems) - 8}" if len(problems) > 8 else ""
            raise HTTPException(409, "Серию нельзя подтвердить целиком — аудитория уже занята: " + "; ".join(problems[:8]) + more)
    now = utc_now()
    busy_ids = {booking.id for booking in busy}
    for booking in items:
        item_status = "rejected" if booking.id in busy_ids else status
        item_reason = SERIES_DATE_BUSY_REASON if booking.id in busy_ids else reason
        booking.status = item_status
        booking.updated_at = now
        booking.decision_at = now
        booking.decided_by_id = actor.id
        booking.decision_reason = item_reason.strip() if item_reason else None
        booking.hold_expires_at = None
        record_event(
            db, booking, actor, item_status, STATUS_SUMMARIES[item_status],
            {"previous_status": "pending", "reason": item_reason, "series_id": series_id},
        )
    if status == "approved":
        db.flush()
        for booking in items:
            if booking.id not in busy_ids:
                reject_competing_requests(db, booking, actor)
    db.commit()
    return len(items)
