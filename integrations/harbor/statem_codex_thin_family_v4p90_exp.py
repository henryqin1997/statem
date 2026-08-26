from __future__ import annotations

from pathlib import Path
from typing import Any

from integrations.harbor.statem_codex_thin_family_v4p88_exp import (
    ThinFamilyV4p88ExperimentalStatemCodex,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CATALOG_V7 = _REPO_ROOT / "examples" / "tb3-thin-family-practices-v7.json"


class ThinFamilyV4p90ExperimentalStatemCodex(
    ThinFamilyV4p88ExperimentalStatemCodex
):
    """Use the frozen scoped-control validation catalog."""

    def __init__(
        self,
        *args: Any,
        practice_catalog_path: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            *args,
            practice_catalog_path=str(
                practice_catalog_path or _DEFAULT_CATALOG_V7
            ),
            **kwargs,
        )

    @staticmethod
    def name() -> str:
        return "ziheng-yaxin-statem-codex-thin-family-v4p90-exp"
