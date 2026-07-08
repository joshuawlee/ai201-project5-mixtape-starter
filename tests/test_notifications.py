"""
tests/test_notifications.py — Mixtape

Tests for notification creation. Regression test for Issue #4:
rating a shared song never created a notification for the sharer.
"""

import pytest
from app import create_app, db
from models import User, Song
from services.notification_service import rate_song, add_to_playlist, get_notifications


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def sharer_and_rater(app):
    """A song shared by one user, to be rated by a friend."""
    with app.app_context():
        sharer = User(username="aaliya", email="aaliya@example.com")
        rater = User(username="kenji", email="kenji@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="My Shared Song", artist="Someone", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        yield {"sharer": sharer, "rater": rater, "song": song}


def test_rating_a_song_notifies_the_sharer(app, sharer_and_rater):
    """Rating a friend's shared song should notify the original sharer."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        rater = sharer_and_rater["rater"]
        song = sharer_and_rater["song"]

        rate_song(rater.id, song.id, 5)

        notifs = get_notifications(sharer.id)
        assert len(notifs) == 1  # Bug: rate_song never called create_notification
        assert notifs[0]["type"] == "song_rated"
        assert rater.username in notifs[0]["body"]


def test_rating_your_own_song_does_not_notify_you(app, sharer_and_rater):
    """A user rating their own shared song should not generate a self-notification."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        song = sharer_and_rater["song"]

        rate_song(sharer.id, song.id, 4)

        notifs = get_notifications(sharer.id)
        assert notifs == []


def test_updating_an_existing_rating_still_notifies(app, sharer_and_rater):
    """Re-rating a song (updating the existing Rating row) should still notify the sharer."""
    with app.app_context():
        sharer = sharer_and_rater["sharer"]
        rater = sharer_and_rater["rater"]
        song = sharer_and_rater["song"]

        rate_song(rater.id, song.id, 3)
        rate_song(rater.id, song.id, 5)  # update, not insert

        notifs = get_notifications(sharer.id)
        assert len(notifs) == 2


def test_adding_to_playlist_still_notifies_as_before(app, sharer_and_rater):
    """
    Sanity check that the working playlist-add notification path is untouched
    by the rate_song() change.

    The song is pre-inserted into playlist_entries directly (rather than via
    add_to_playlist()'s own playlist.songs.append(), which has a separate,
    pre-existing bug: it doesn't populate the NOT NULL position/added_by
    columns on the association table and raises IntegrityError for a song
    that isn't already in the playlist). That bug is outside the scope of
    the 5 tracked issues, so this test only exercises the
    "song already in playlist -> does it still notify" branch of
    add_to_playlist(), which is enough to confirm the notification pattern
    itself is unaffected by this fix.
    """
    with app.app_context():
        from models import Playlist, playlist_entries

        sharer = sharer_and_rater["sharer"]
        rater = sharer_and_rater["rater"]
        song = sharer_and_rater["song"]

        playlist = Playlist(name="Friday Energy", created_by=rater.id)
        db.session.add(playlist)
        db.session.flush()
        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=playlist.id, song_id=song.id, position=1, added_by=rater.id
            )
        )
        db.session.commit()

        add_to_playlist(playlist.id, song.id, rater.id)

        notifs = get_notifications(sharer.id)
        assert len(notifs) == 1
        assert notifs[0]["type"] == "song_added_to_playlist"
