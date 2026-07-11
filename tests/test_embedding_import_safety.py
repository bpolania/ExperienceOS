"""Phase 11 Prompt 2: import-safety and store-isolation tests.

Root and embeddings imports must stay lightweight and offline; the
embedding layer must be structurally incapable of touching memory.
"""

import inspect
import os
import subprocess
import sys

HEAVY_MODULES = (
    "sentence_transformers",
    "torch",
    "onnxruntime",
    "transformers",
    "llama_cpp",
)


def _run_import_probe(statement: str) -> list[str]:
    """Import in a clean subprocess; return loaded heavy modules.

    Importing any ``experienceos.*`` module executes the root package
    ``__init__`` (which loads core modules like the store by design),
    so store isolation is proven structurally below via module
    references and behaviorally via the no-mutation test — not here.
    """
    probe = (
        "import sys\n"
        f"{statement}\n"
        f"flagged = [m for m in sys.modules if m in {HEAVY_MODULES!r}]\n"
        "print('\\n'.join(flagged))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, check=True,
        env=dict(os.environ, PYTHONPATH="."),
    )
    return [line for line in completed.stdout.split("\n") if line]


def test_root_import_loads_no_heavy_or_embedding_libraries():
    assert _run_import_probe("import experienceos") == []


def test_embeddings_package_import_stays_lightweight():
    assert _run_import_probe("import experienceos.embeddings") == []


def test_optional_provider_module_import_loads_nothing_heavy():
    # Importing the optional module itself is safe; only an actual
    # embedding call may import the library or load a model.
    assert _run_import_probe("import experienceos.embeddings.local") == []


def test_factory_and_availability_inspection_load_nothing_heavy():
    assert _run_import_probe(
        "from experienceos.embeddings import create_embedding_provider\n"
        "p = create_embedding_provider('local')\n"
        "p.availability()\n"
        "q = create_embedding_provider('deterministic')\n"
        "q.embed_query('hello world')"
    ) == []


def test_embeddings_modules_never_import_store_modules():
    import experienceos.embeddings.base
    import experienceos.embeddings.deterministic
    import experienceos.embeddings.factory
    import experienceos.embeddings.local

    for module_name in (
        "experienceos.embeddings.base",
        "experienceos.embeddings.deterministic",
        "experienceos.embeddings.factory",
        "experienceos.embeddings.local",
    ):
        module = sys.modules[module_name]
        referenced = {
            value.__module__
            for value in vars(module).values()
            if hasattr(value, "__module__")
        }
        assert not any("memory" in ref for ref in referenced), module_name


def test_provider_constructors_accept_no_store_or_callbacks():
    from experienceos.embeddings import DeterministicEmbeddingProvider
    from experienceos.embeddings.local import (
        SentenceTransformerEmbeddingProvider,
    )

    for cls in (DeterministicEmbeddingProvider,
                SentenceTransformerEmbeddingProvider):
        parameters = inspect.signature(cls).parameters
        assert not any(
            "store" in name or "callback" in name or "bus" in name
            for name in parameters
        ), cls.__name__


def test_embedding_calls_touch_no_memory_and_emit_no_events():
    from experienceos.embeddings import DeterministicEmbeddingProvider
    from experienceos.events.bus import EventBus
    from experienceos.memory.store import InMemoryMemoryStore
    from experienceos.memory.schema import ExperienceEntry

    store = InMemoryMemoryStore()
    bus = EventBus()
    entry = ExperienceEntry(
        user_id="u1", kind="preference", text="prefers green tea"
    )
    store.add(entry)
    snapshot = [
        (m.id, m.status, m.text) for m in store.list_memories("u1")
    ]

    provider = DeterministicEmbeddingProvider()
    provider.embed_query("prefers green tea")
    provider.embed_memories([m.text for m in store.list_memories("u1")])

    assert [
        (m.id, m.status, m.text) for m in store.list_memories("u1")
    ] == snapshot
    assert bus.history() == []


def test_results_carry_no_memory_actions_or_objects():
    from dataclasses import fields

    from experienceos.embeddings import (
        DeterministicEmbeddingProvider,
        EmbeddingResult,
    )

    field_names = {f.name for f in fields(EmbeddingResult)}
    assert field_names == {
        "vector", "dimensions", "provider_id", "model_id",
        "deterministic", "elapsed_ms",
    }
    result = DeterministicEmbeddingProvider().embed_query("text only")
    assert isinstance(result.vector, tuple)
