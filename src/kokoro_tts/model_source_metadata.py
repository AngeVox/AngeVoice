"""Declaration-only transition artifact for the ModelSource configuration surface.

The current runtime owners remain unchanged: ``TTSConfig`` owns normalization
and ``model_sources.resolve_model_source`` owns resolution.  Until consumers
are migrated behind compatibility contracts, this metadata must not be treated
as the sole behavioral source of truth.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSourceMetadata:
    """Immutable description of the existing ModelSource public surface."""

    key: str
    default: str
    accepted_values: frozenset[str]
    canonical_env: str
    country_env_aliases: tuple[str, ...]
    admin_group: str
    admin_choices: tuple[str, ...]
    admin_restart: bool
    admin_rebuild_moss: bool
    normalization: str
    engine_scope: frozenset[str]
    excluded_engine_scope: str
    runtime_normalization_owner: str
    resolver_owner: str


MODEL_SOURCE_METADATA = ModelSourceMetadata(
    key="model_source",
    default="auto",
    accepted_values=frozenset({"auto", "huggingface", "modelscope", "offline"}),
    canonical_env="ANGEVOICE_MODEL_SOURCE",
    country_env_aliases=(
        "ANGEVOICE_MODEL_SOURCE_COUNTRY",
        "MODEL_SOURCE_COUNTRY",
    ),
    admin_group="security",
    admin_choices=("auto", "modelscope", "huggingface", "offline"),
    admin_restart=False,
    admin_rebuild_moss=False,
    normalization="strip_lower",
    engine_scope=frozenset({"kokoro", "moss", "moss_audio_tokenizer"}),
    excluded_engine_scope="zipvoice",
    runtime_normalization_owner="TTSConfig._normalize_model_source",
    resolver_owner="model_sources.resolve_model_source",
)


__all__ = ["MODEL_SOURCE_METADATA"]
