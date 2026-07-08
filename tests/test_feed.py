"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed. Regression test for Issue #2:
a friend's listen from yesterday evening kept showing up as "listening now"
the next morning because the filter used a rolling 24-hour window instead
of a calendar-day boundary.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def friends(app):
    with app.app_context():
        me = User(username="nova", email="nova@example.com")
        friend = User(username="darius", email="darius@example.com")
        db.session.add_all([me, friend])
        db.session.flush()
        db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))
        db.session.execute(friendships.insert().values(user_id=friend.id, friend_id=me.id))

        song = Song(title="Late Night Track", artist="Someone", shared_by=me.id)
        db.session.add(song)
        db.session.commit()

        yield {"me": me, "friend": friend, "song": song}


def _yesterday_at(hour: int) -> datetime:
    now = datetime.now(timezone.utc)
    return datetime.combine((now - timedelta(days=1)).date(), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=hour)


def test_yesterday_evening_listen_does_not_appear_today(app, friends):
    """A listen from yesterday evening should not show up as 'listening now' today."""
    with app.app_context():
        event = ListeningEvent(
            user_id=friends["friend"].id,
            song_id=friends["song"].id,
            listened_at=_yesterday_at(23),  # 11pm yesterday
        )
        db.session.add(event)
        db.session.commit()

        feed = get_friends_listening_now(friends["me"].id)
        assert feed == []


def test_todays_listen_appears(app, friends):
    """A listen from earlier today should still show up as 'listening now'."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        start_of_today = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
        event = ListeningEvent(
            user_id=friends["friend"].id,
            song_id=friends["song"].id,
            listened_at=start_of_today + timedelta(minutes=1),
        )
        db.session.add(event)
        db.session.commit()

        feed = get_friends_listening_now(friends["me"].id)
        assert len(feed) == 1
        assert feed[0]["friend"]["username"] == "darius"
