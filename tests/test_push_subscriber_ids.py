"""
Tests du renvoi de la table d'identifiants vers le dépôt de données (#55).

Un nouvel abonné reçoit son identifiant au moment de l'envoi, dans un runner
éphémère. Sans ce renvoi, il est perdu et la personne en reçoit un autre le
lendemain — son historique se fragmente en silence.

Reprend la leçon de #52 : ne pas écrire quand rien n'a changé, sinon chaque
envoi produit un commit vide.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.push_subscriber_ids import push_subscriber_ids

LOCAL = '[subscriber_ids]\nemails = ["a@example.com", "b@example.com"]\nids    = ["id-a", "id-b"]\n'
REMOTE_SAME = LOCAL
REMOTE_OLD = '[subscriber_ids]\nemails = ["a@example.com"]\nids    = ["id-a"]\n'


class FakeRemote:
    def __init__(self, content: str | None):
        self.content = content
        self.writes: list[str] = []

    def read(self, path):
        return self.content

    def write(self, path, content, message):
        self.content = content
        self.writes.append(message)


@pytest.fixture
def local_file(tmp_path) -> Path:
    p = tmp_path / "subscriber_ids.toml"
    p.write_text(LOCAL, encoding="utf-8")
    return p


def test_a_new_identifier_is_pushed(local_file):
    remote = FakeRemote(REMOTE_OLD)

    pushed = push_subscriber_ids(local_file, remote.read, remote.write)

    assert pushed is True
    assert remote.content == LOCAL
    assert len(remote.writes) == 1


def test_nothing_is_pushed_when_unchanged(local_file):
    """Le défaut de #52 : un PUT à contenu identique crée un commit vide."""
    remote = FakeRemote(REMOTE_SAME)

    pushed = push_subscriber_ids(local_file, remote.read, remote.write)

    assert pushed is False
    assert remote.writes == []


def test_an_absent_remote_file_is_created(local_file):
    remote = FakeRemote(None)

    assert push_subscriber_ids(local_file, remote.read, remote.write) is True
    assert remote.content == LOCAL


def test_a_missing_local_file_is_refused(tmp_path):
    remote = FakeRemote(REMOTE_OLD)

    with pytest.raises(FileNotFoundError):
        push_subscriber_ids(tmp_path / "absent.toml", remote.read, remote.write)

    assert remote.writes == []


def test_a_local_file_with_fewer_entries_is_refused(tmp_path):
    """
    Garde-fou : la table ne devrait que grandir. Moins d'entrées en local
    signale une récupération ratée — écraser effacerait des identifiants et
    orphelinerait l'historique de mesures de ces lecteurs.
    """
    shrunk = tmp_path / "subscriber_ids.toml"
    shrunk.write_text(REMOTE_OLD, encoding="utf-8")
    remote = FakeRemote(LOCAL)

    with pytest.raises(RuntimeError, match="moins d'entrées"):
        push_subscriber_ids(shrunk, remote.read, remote.write)

    assert remote.writes == []


def test_an_unparsable_local_file_is_refused(tmp_path):
    bad = tmp_path / "subscriber_ids.toml"
    bad.write_text("pas du TOML [", encoding="utf-8")
    remote = FakeRemote(REMOTE_OLD)

    with pytest.raises(RuntimeError, match="illisible"):
        push_subscriber_ids(bad, remote.read, remote.write)
