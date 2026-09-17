from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import BookSubmission, User

OPEN_STATUSES = ("unassigned", "pending", "reviewing", "needs_changes", "editor_approve", "editor_reject")


def editor_load(db: Session, editor_id: int) -> int:
    return (
        db.query(func.count(BookSubmission.id))
        .filter(
            BookSubmission.assigned_editor_id == editor_id,
            BookSubmission.editor_task_status != "done",
            BookSubmission.status.in_(OPEN_STATUSES),
        )
        .scalar()
        or 0
    )


def assign_submission(db: Session, row: BookSubmission) -> None:
    editors = (
        db.query(User)
        .filter(User.role == "editor", User.status == "active")
        .all()
    )
    candidates = [e for e in editors if e.id != row.user_id]
    if not candidates:
        row.status = "unassigned"
        row.assigned_editor_id = None
        row.assigned_editor = ""
        row.assign_reason = "暂无可用编辑，进入待分配队列。"
        row.assigned_at = datetime.utcnow()
        row.editor_task_status = "open"
        return

    lang = (row.language_code or "").strip()
    genres = {g for g in (row.genres or "").split(",") if g}

    def score(ed: User) -> tuple:
        langs = {x.strip() for x in (ed.editor_languages or "").split(",") if x.strip()}
        prefs = {x.strip() for x in (ed.editor_genres or "").split(",") if x.strip()}
        lang_ok = (not langs) or (lang in langs) or not lang
        genre_ok = (not prefs) or bool(genres & prefs) or not genres
        load = editor_load(db, ed.id)
        return (0 if lang_ok else 1, 0 if genre_ok else 1, load, ed.id)

    pick = sorted(candidates, key=score)[0]
    langs = {x.strip() for x in (pick.editor_languages or "").split(",") if x.strip()}
    prefs = {x.strip() for x in (pick.editor_genres or "").split(",") if x.strip()}
    reasons = []
    if langs and lang in langs:
        reasons.append("语言匹配")
    if prefs and genres & prefs:
        reasons.append("类型匹配")
    reasons.append("当前待审最少")
    row.assigned_editor_id = pick.id
    row.assigned_editor = pick.nickname or pick.username
    row.assigned_at = datetime.utcnow()
    row.assign_reason = "；".join(reasons)
    row.status = "pending"
    row.editor_task_status = "open"


def close_editor_task(row: BookSubmission) -> None:
    row.editor_task_status = "done"
    row.reviewed_at = datetime.utcnow()
