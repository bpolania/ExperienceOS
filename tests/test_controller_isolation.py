"""Phase 11 Prompt 6: mutation isolation, no-integration, and import
safety for the specialized controller contracts."""

import inspect
import os
import subprocess
import sys

from experienceos.controllers import (
    AbstainingAdmissionController,
    AbstainingTransitionVerifier,
    AbstainingUpdateController,
    AdmissionEvidence,
    ExtractionEvidence,
    ForgetIntentEvidence,
    MemorySnapshot,
    NoForgetIntentController,
    NoOpExtractionController,
    ProposedMemoryCandidate,
    TransitionEvidence,
    UpdateEvidence,
)
from experienceos.events.bus import EventBus
from experienceos.memory.schema import ExperienceEntry
from experienceos.memory.sqlite_store import SQLiteMemoryStore
from experienceos.memory.store import InMemoryMemoryStore

DEFAULT_CONTROLLERS = (
    AbstainingAdmissionController,
    NoOpExtractionController,
    AbstainingUpdateController,
    NoForgetIntentController,
    AbstainingTransitionVerifier,
)


def _snapshot_from(entry):
    return MemorySnapshot(
        memory_id=entry.id, kind=entry.kind, text=entry.text,
        status=entry.status,
    )


def _invoke_all_defaults(snapshot):
    candidate = ProposedMemoryCandidate(kind="fact", text="new fact")
    AbstainingAdmissionController().evaluate(
        AdmissionEvidence(user_message="hello")
    )
    NoOpExtractionController().extract(
        ExtractionEvidence(user_text="hello")
    )
    AbstainingUpdateController().evaluate(
        UpdateEvidence(candidate=candidate, existing=snapshot)
    )
    NoForgetIntentController().evaluate(
        ForgetIntentEvidence(
            user_message="forget that", candidate_memories=(snapshot,)
        )
    )
    AbstainingTransitionVerifier().verify(
        TransitionEvidence(
            transition_type="forget", target_state="forgotten",
            memory=snapshot,
        )
    )


def test_constructors_accept_no_authority_handles():
    for cls in DEFAULT_CONTROLLERS:
        parameters = inspect.signature(cls).parameters
        assert not any(
            token in name
            for name in parameters
            for token in ("store", "engine", "manager", "bus",
                          "callback", "session")
        ), cls.__name__


def test_controller_modules_import_no_memory_or_store_modules():
    module_names = (
        "experienceos.controllers.base",
        "experienceos.controllers.admission",
        "experienceos.controllers.extraction",
        "experienceos.controllers.update",
        "experienceos.controllers.forget",
        "experienceos.controllers.transition",
        "experienceos.controllers.gate",
    )
    for module_name in module_names:
        module = sys.modules[module_name]
        referenced = {
            value.__module__
            for value in vars(module).values()
            if hasattr(value, "__module__")
        }
        assert not any(
            "experienceos.memory" in ref or "experienceos.engine" in ref
            or "experienceos.events" in ref
            for ref in referenced
        ), module_name


def test_in_memory_store_and_events_unchanged_by_all_defaults():
    store = InMemoryMemoryStore()
    bus = EventBus()
    entry = ExperienceEntry(user_id="u1", text="lives in Porto",
                            kind="fact")
    store.add(entry)
    before = [
        (m.id, m.status, m.text, m.updated_at, dict(m.metadata))
        for m in store.list_memories("u1")
    ]
    _invoke_all_defaults(_snapshot_from(entry))
    assert [
        (m.id, m.status, m.text, m.updated_at, dict(m.metadata))
        for m in store.list_memories("u1")
    ] == before
    assert bus.history() == []
    for memory in store.list_memories("u1"):
        text = str(memory.metadata)
        assert "proposal" not in text and "controller" not in text


def test_sqlite_store_unchanged_by_all_defaults(tmp_path):
    db = SQLiteMemoryStore(tmp_path / "controllers.sqlite3")
    entry = ExperienceEntry(user_id="u1", text="lives in Porto",
                            kind="fact")
    db.add(entry)
    before = [
        (m.id, m.status, m.text, dict(m.metadata))
        for m in db.list_memories("u1")
    ]
    _invoke_all_defaults(_snapshot_from(entry))
    assert [
        (m.id, m.status, m.text, dict(m.metadata))
        for m in db.list_memories("u1")
    ] == before


def test_evidence_snapshots_do_not_alias_live_records():
    entry = ExperienceEntry(user_id="u1", text="lives in Porto",
                            kind="fact")
    snapshot = _snapshot_from(entry)
    entry.text = "mutated after snapshot"
    assert snapshot.text == "lives in Porto"  # copy, not alias


def test_no_controller_constructed_by_default_experienceos():
    """`ExperienceOS` never builds the new controllers: constructing an
    agent leaves the controller default classes uninstantiated."""
    probe = (
        "import sys\n"
        "from experienceos import ExperienceOS\n"
        "from experienceos.providers.mock import MockProvider\n"
        "agent = ExperienceOS(model=MockProvider())\n"
        "import experienceos.controllers as c\n"
        "print('constructed-ok')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        env=dict(os.environ, PYTHONPATH="."),
    )
    assert completed.returncode == 0, completed.stderr
    assert "constructed-ok" in completed.stdout
    # And nothing in the core packages references the new defaults.
    import pathlib

    core = pathlib.Path("experienceos")
    for path in core.rglob("*.py"):
        if "controllers" in path.parts:
            continue
        text = path.read_text()
        for name in ("AbstainingAdmissionController",
                     "NoOpExtractionController",
                     "AbstainingUpdateController",
                     "NoForgetIntentController",
                     "AbstainingTransitionVerifier"):
            assert name not in text, f"{name} referenced in {path}"


def test_controllers_package_import_loads_no_heavy_libraries():
    probe = (
        "import sys\n"
        "import experienceos.controllers\n"
        "flagged = [m for m in sys.modules if m in ("
        "'sentence_transformers', 'torch', 'onnxruntime', "
        "'transformers', 'llama_cpp')]\n"
        "print('\\n'.join(flagged) or 'clean')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        check=True, env=dict(os.environ, PYTHONPATH="."),
    )
    assert completed.stdout.strip() == "clean"


def test_no_activation_environment_variable_exists():
    import pathlib

    text = "\n".join(
        path.read_text()
        for path in pathlib.Path("experienceos/controllers").glob("*.py")
    )
    assert "os.environ" not in text
    assert "getenv" not in text
