from __future__ import annotations

import unittest
from pathlib import Path

from integrations.harbor.statem_codex_thin_family_v4p62_exp import (
    select_thin_family_practice,
)
from integrations.harbor.statem_codex_thin_family_v4p76_exp import (
    build_solver_projection,
    build_thin_reviewer_projection,
)
from integrations.harbor.statem_codex_thin_family_v4p77_exp import (
    ThinFamilyV4p77ExperimentalStatemCodex,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v5.json"


class ThinFamilyV4p77Test(unittest.TestCase):
    def test_audio_practice_is_unadmitted_and_role_scoped(self) -> None:
        instruction = (
            "Transcribe a mixed SATB chorale audio recording into a complete "
            "MusicXML score with exact pitch, rhythm, barlines, and voice layout."
        )
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="active",
        )
        self.assertEqual(
            selection["practice_id"], "audio_symbolic_transcription_compact"
        )
        self.assertFalse(selection["activated"])
        self.assertFalse(selection["admitted"])
        selection["activated"] = True
        pre_solve = build_solver_projection(selection, "pre_solve", CATALOG)
        verify = build_solver_projection(selection, "verify", CATALOG)
        reviewer = build_thin_reviewer_projection(selection, CATALOG)
        self.assertTrue(
            any("separate hypotheses" in item for item in pre_solve["obligations"])
        )
        self.assertFalse(
            any("per-measure duration closure" in item for item in pre_solve["obligations"])
        )
        self.assertTrue(
            any("per-measure duration closure" in item for item in verify["obligations"])
        )
        self.assertIn(
            "voice_separation_range_and_crossing",
            reviewer["detailed"]["prioritized_checks"],
        )

    def test_adapter_identity_is_versioned(self) -> None:
        self.assertEqual(
            ThinFamilyV4p77ExperimentalStatemCodex.name(),
            "ziheng-yaxin-statem-codex-thin-family-v4p77-exp",
        )


if __name__ == "__main__":
    unittest.main()
