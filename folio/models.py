from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine,
)
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import DB_PATH, database_url, uses_postgres


class Base(DeclarativeBase):
    pass


class Author(Base):
    __tablename__ = "authors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    localized_name: Mapped[str] = mapped_column(String(200), default="")
    biography_zh: Mapped[str] = mapped_column(Text, default="")
    nationality: Mapped[str] = mapped_column(String(120), default="")
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Issue(Base):
    __tablename__ = "issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    cover_theme: Mapped[str] = mapped_column(String(80), default="")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("year", "month", name="uq_issue_ym"),)


class Book(Base):
    __tablename__ = "books"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    original_title: Mapped[str] = mapped_column(String(400), default="", index=True)
    chinese_title: Mapped[str] = mapped_column(String(400), default="")
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("authors.id"), nullable=True)
    language_code: Mapped[str] = mapped_column(String(8), default="", index=True)
    language_name: Mapped[str] = mapped_column(String(40), default="")
    publisher: Mapped[str] = mapped_column(String(200), default="")
    publication_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True, index=True)
    publication_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    isbn10: Mapped[str] = mapped_column(String(16), default="", index=True)
    isbn13: Mapped[str] = mapped_column(String(20), default="", index=True)
    primary_genre: Mapped[str] = mapped_column(String(40), default="其他", index=True)
    genres: Mapped[str] = mapped_column(String(400), default="")
    tags: Mapped[str] = mapped_column(String(400), default="")
    short_description_zh: Mapped[str] = mapped_column(Text, default="")
    full_description_zh: Mapped[str] = mapped_column(Text, default="")
    recommendation_zh: Mapped[str] = mapped_column(Text, default="")
    audience_zh: Mapped[str] = mapped_column(Text, default="")
    reading_mood_zh: Mapped[str] = mapped_column(String(200), default="")
    editor_quote_zh: Mapped[str] = mapped_column(String(200), default="")
    cover_image: Mapped[str] = mapped_column(String(300), default="/covers/placeholder.svg")
    cover_thumbnail_url: Mapped[str] = mapped_column(String(300), default="")
    cover_full_url: Mapped[str] = mapped_column(String(300), default="")
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    issue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("issues.id"), nullable=True)
    featured_rank: Mapped[int] = mapped_column(Integer, default=0)
    verification_status: Mapped[str] = mapped_column(String(20), default="pending")
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source_name: Mapped[str] = mapped_column(String(200), default="")
    source_url: Mapped[str] = mapped_column(String(400), default="")
    selection_reason: Mapped[str] = mapped_column(Text, default="")
    source_file: Mapped[str] = mapped_column(String(200), default="")
    source_row: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    author: Mapped[Optional["Author"]] = relationship()
    issue: Mapped[Optional["Issue"]] = relationship()

    def genre_list(self):
        return [g for g in (self.genres or self.primary_genre).split(",") if g]

    def tag_list(self):
        return [t for t in (self.tags or "").split(",") if t]


class Rating(Base):
    __tablename__ = "ratings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("book_id", "visitor_id", name="uq_rating_book_visitor"),)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    guest_identity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    nickname: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("comments.id"), nullable=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CommentLike(Base):
    __tablename__ = "comment_likes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("comment_id", "visitor_id", name="uq_like_comment_visitor"),)


class CommentReport(Base):
    __tablename__ = "comment_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    visitor_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BookSubmission(Base):
    __tablename__ = "book_submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, default="")
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    nickname: Mapped[str] = mapped_column(String(40), default="")
    contact_email: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(160), default="")
    original_title: Mapped[str] = mapped_column(String(400), default="")
    chinese_title: Mapped[str] = mapped_column(String(400), default="")
    chinese_title_is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    authors: Mapped[str] = mapped_column(String(300), default="")
    cover_url: Mapped[str] = mapped_column(String(400), default="")
    introduction: Mapped[str] = mapped_column(Text, default="")
    recommendation_reason: Mapped[str] = mapped_column(Text, default="")
    suitable_readers: Mapped[str] = mapped_column(Text, default="")
    author_biography: Mapped[str] = mapped_column(Text, default="")
    publication_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    publication_date: Mapped[str] = mapped_column(String(20), default="")
    publisher: Mapped[str] = mapped_column(String(200), default="")
    isbn: Mapped[str] = mapped_column(String(32), default="", index=True)
    language_code: Mapped[str] = mapped_column(String(16), default="")
    language_other: Mapped[str] = mapped_column(String(80), default="")
    region: Mapped[str] = mapped_column(String(80), default="")
    genres: Mapped[str] = mapped_column(String(400), default="")
    tags: Mapped[str] = mapped_column(String(240), default="")
    information_source: Mapped[str] = mapped_column(String(80), default="")
    information_source_note: Mapped[str] = mapped_column(String(400), default="")
    fuzzy: Mapped[bool] = mapped_column(Boolean, default=False)
    origin: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    assigned_editor: Mapped[str] = mapped_column(String(80), default="")
    assigned_editor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    assign_reason: Mapped[str] = mapped_column(String(400), default="")
    editor_task_status: Mapped[str] = mapped_column(String(20), default="")
    public_feedback: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    checklist: Mapped[str] = mapped_column(Text, default="")
    duplicate_flag: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    completeness: Mapped[int] = mapped_column(Integer, default=0)
    approved_book_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    candidate_pool: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SubmissionAuditLog(Base):
    __tablename__ = "submission_audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("book_submissions.id"), index=True)
    operator_id: Mapped[str] = mapped_column(String(80), default="")
    action: Mapped[str] = mapped_column(String(40), index=True)
    previous_status: Mapped[str] = mapped_column(String(24), default="")
    next_status: Mapped[str] = mapped_column(String(24), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SiteNotice(Base):
    __tablename__ = "site_notices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    submission_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(40), default="info")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    nickname: Mapped[str] = mapped_column(String(30), default="")
    avatar_url: Mapped[str] = mapped_column(String(400), default="")
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    editor_languages: Mapped[str] = mapped_column(String(80), default="")
    editor_genres: Mapped[str] = mapped_column(String(400), default="")
    trust_level: Mapped[int] = mapped_column(Integer, default=0)  # >=1 may publish UGC places directly
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuthDevice(Base):
    __tablename__ = "auth_devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "token_hash", name="uq_device_user_token"),)


class DeviceChallenge(Base):
    __tablename__ = "device_challenges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class EditorApplication(Base):
    __tablename__ = "editor_applications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class GuestIdentity(Base):
    __tablename__ = "guest_identities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(40), default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    visitor_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BookFavorite(Base):
    __tablename__ = "book_favorites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "book_id", name="uq_fav_user_book"),)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(40), default="reply")
    actor_name: Mapped[str] = mapped_column(String(40), default="")
    book_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TourMap(Base):
    """User-created literary pilgrimage map (地图巡礼)."""

    __tablename__ = "tour_maps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    author_name: Mapped[str] = mapped_column(String(60), default="")
    subtitle: Mapped[str] = mapped_column(String(240), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String(16), default="world", index=True)
    kind: Mapped[str] = mapped_column(String(16), default="custom", index=True)  # author | book | genre | custom
    ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    base_style: Mapped[str] = mapped_column(String(24), default="paper")
    center_lat: Mapped[float] = mapped_column(Float, default=20.0)
    center_lon: Mapped[float] = mapped_column(Float, default=10.0)
    zoom: Mapped[int] = mapped_column(Integer, default=2)
    visibility: Mapped[str] = mapped_column(String(16), default="private", index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    cover_url: Mapped[str] = mapped_column(String(400), default="")
    tags: Mapped[str] = mapped_column(String(240), default="")
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    stop_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)


class TourStopCategory(Base):
    __tablename__ = "tour_stop_categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("tour_maps.id"), index=True)
    label: Mapped[str] = mapped_column(String(40), default="")
    color: Mapped[str] = mapped_column(String(16), default="#9BB3C9")
    kind: Mapped[str] = mapped_column(String(16), default="auto", index=True)  # auto | custom
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class TourStop(Base):
    __tablename__ = "tour_stops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    map_id: Mapped[int] = mapped_column(ForeignKey("tour_maps.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)  # contributor
    place_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    author_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    category_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    tag_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lon: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[str] = mapped_column(String(12), default="city")  # country | region | city
    place_name: Mapped[str] = mapped_column(String(120), default="")
    country: Mapped[str] = mapped_column(String(80), default="")
    admin1: Mapped[str] = mapped_column(String(80), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    period: Mapped[str] = mapped_column(String(40), default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    book_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    book_ids: Mapped[str] = mapped_column(Text, default="")  # JSON array of book ids
    media_url: Mapped[str] = mapped_column(String(400), default="")
    photos: Mapped[str] = mapped_column(Text, default="")  # JSON array of URLs
    draft: Mapped[str] = mapped_column(Text, default="")  # JSON draft fields
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)


class TourPlace(Base):
    """A shared place (city/region): one literary footnote + photos for everyone."""

    __tablename__ = "tour_places"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    name_en: Mapped[str] = mapped_column(String(160), default="")
    level: Mapped[str] = mapped_column(String(12), default="city")
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lon: Mapped[float] = mapped_column(Float, default=0.0)
    country: Mapped[str] = mapped_column(String(80), default="")
    admin1: Mapped[str] = mapped_column(String(80), default="")
    footnote: Mapped[str] = mapped_column(Text, default="")
    photos: Mapped[str] = mapped_column(Text, default="")  # JSON array, max 3
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    # UGC: a user-added specific place under a preset city, reviewed before public
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)  # pending|published|disputed|rejected
    city_key: Mapped[str] = mapped_column(String(200), default="", index=True)  # parent city (gazetteer key)
    address: Mapped[str] = mapped_column(String(240), default="")
    source_url: Mapped[str] = mapped_column(String(400), default="")
    reviewed_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reject_reason: Mapped[str] = mapped_column(String(400), default="")
    delete_requested: Mapped[bool] = mapped_column(Boolean, default=False)  # owner asked to delete a published place
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)  # auto-published by the auto-reviewer (staff may re-check)
    merged_into_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TourPlaceBook(Base):
    """Many-to-many: a specific place can relate to several books."""
    __tablename__ = "tour_place_books"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("tour_places.id"), index=True)
    book_id: Mapped[int] = mapped_column(Integer, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("place_id", "book_id", name="uq_place_book"),)


class TourPlaceReport(Base):
    """Users can report a wrong/duplicate place for staff to handle."""
    __tablename__ = "tour_place_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("tour_places.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|resolved|dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TourPlaceReview(Base):
    """Audit log of place review actions."""
    __tablename__ = "tour_place_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("tour_places.id"), index=True)
    reviewer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(16), default="")  # approve|reject|dispute|merge
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TourStopRevision(Base):
    __tablename__ = "tour_stop_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stop_id: Mapped[int] = mapped_column(ForeignKey("tour_stops.id"), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    book_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    book_ids: Mapped[str] = mapped_column(Text, default="")  # JSON array of book ids
    photos: Mapped[str] = mapped_column(Text, default="")
    editor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TourMedia(Base):
    """Uploaded media with a lifecycle: temp -> attached -> published / deleted."""

    __tablename__ = "tour_media"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    stop_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(400), default="")
    status: Mapped[str] = mapped_column(String(16), default="temp", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TourStopNote(Base):
    """A reader's note on a stop (like a comment under a place)."""

    __tablename__ = "tour_stop_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stop_id: Mapped[int] = mapped_column(ForeignKey("tour_stops.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    author_name: Mapped[str] = mapped_column(String(40), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TourStopNoteLike(Base):
    __tablename__ = "tour_stop_note_likes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("tour_stop_notes.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("note_id", "user_id", name="uq_stop_note_like"),)


class TourPlaceLike(Base):
    __tablename__ = "tour_place_likes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("tour_places.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("place_id", "user_id", name="uq_place_like_user"),)


_url = database_url()
_engine_kwargs: dict = {"pool_pre_ping": True}
if _url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
elif _url.startswith("postgresql"):
    # Small pool: reuse TLS connections to Neon across navigations (faster than NullPool).
    _engine_kwargs.update({
        "pool_size": 3,
        "max_overflow": 2,
        "pool_recycle": 280,
    })
engine = create_engine(_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


_BOOL_DDL = "BOOLEAN DEFAULT false" if uses_postgres() else "BOOLEAN DEFAULT 0"


def _add_column(table: str, column: str, ddl: str) -> None:
    with engine.begin() as conn:
        if uses_postgres():
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            ).scalar()
            if not exists:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            return
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {row[1] for row in rows}
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def init_db() -> None:
    if not uses_postgres():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        Base.metadata.create_all(engine)
    except (OperationalError, ProgrammingError) as exc:
        msg = str(exc.orig if getattr(exc, "orig", None) else exc)
        if "already exists" in msg.lower():
            pass
        else:
            raise RuntimeError(f"建表失败: {msg}") from exc
    try:
        _add_column("comments", "user_id", "INTEGER")
        _add_column("comments", "guest_identity_id", "INTEGER")
        _add_column("book_submissions", "user_id", "INTEGER")
        _add_column("site_notices", "user_id", "INTEGER")
        _add_column("auth_sessions", "device_id", "INTEGER")
        _add_column("book_submissions", "assigned_editor_id", "INTEGER")
        _add_column("book_submissions", "assigned_at", "DATETIME" if not uses_postgres() else "TIMESTAMP")
        _add_column("book_submissions", "assign_reason", "VARCHAR(400)")
        _add_column("book_submissions", "editor_task_status", "VARCHAR(20)")
        _add_column("users", "editor_languages", "VARCHAR(80)")
        _add_column("users", "editor_genres", "VARCHAR(400)")
        _add_column("users", "trust_level", "INTEGER DEFAULT 0")
        _add_column("books", "cover_thumbnail_url", "VARCHAR(300) DEFAULT ''")
        _add_column("books", "cover_full_url", "VARCHAR(300) DEFAULT ''")
        _add_column("tour_stop_categories", "kind", "VARCHAR(16) DEFAULT 'auto'")
        _add_column("tour_stops", "tag_id", "INTEGER")
        _add_column("tour_stops", "level", "VARCHAR(12) DEFAULT 'city'")
        _add_column("tour_stops", "photos", "TEXT")
        _add_column("tour_maps", "kind", "VARCHAR(16) DEFAULT 'custom'")
        _add_column("tour_maps", "ref_id", "INTEGER")
        _add_column("tour_maps", "author_name", "VARCHAR(60)")
        _add_column("tour_stops", "user_id", "INTEGER")
        _add_column("tour_stops", "place_id", "INTEGER")
        _add_column("tour_stops", "author_id", "INTEGER")
        _add_column("book_submissions", "fuzzy", _BOOL_DDL)
        _add_column("book_submissions", "origin", "VARCHAR(120)")
        _add_column("tour_stop_notes", "is_private", _BOOL_DDL)
        _add_column("tour_stops", "draft", "TEXT")
        _add_column("tour_stops", "book_ids", "TEXT")
        _add_column("tour_stop_revisions", "book_ids", "TEXT")
        _add_column("tour_places", "status", "VARCHAR(16) DEFAULT 'published'")
        _add_column("tour_places", "city_key", "VARCHAR(200) DEFAULT ''")
        _add_column("tour_places", "address", "VARCHAR(240) DEFAULT ''")
        _add_column("tour_places", "source_url", "VARCHAR(400) DEFAULT ''")
        _add_column("tour_places", "reviewed_by", "INTEGER")
        _add_column("tour_places", "reviewed_at", "TIMESTAMP" if uses_postgres() else "DATETIME")
        _add_column("tour_places", "reject_reason", "VARCHAR(400) DEFAULT ''")
        _add_column("tour_places", "delete_requested", _BOOL_DDL)
        _add_column("tour_places", "auto_approved", _BOOL_DDL)
        _add_column("tour_places", "merged_into_id", "INTEGER")
        _add_column("tour_places", "deleted_at", "TIMESTAMP" if uses_postgres() else "DATETIME")
        _add_column("tour_maps", "deleted_at", "TIMESTAMP")
        _add_column("tour_stops", "deleted_at", "TIMESTAMP")
    except OperationalError:
        pass


Index("ix_books_search", Book.original_title, Book.chinese_title, Book.isbn13)
