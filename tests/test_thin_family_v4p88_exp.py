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
from integrations.harbor.statem_codex_thin_family_v4p88_exp import (
    ThinFamilyV4p88ExperimentalStatemCodex,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v6.json"


class ThinFamilyV4p88Test(unittest.TestCase):
    def test_biological_practice_is_unadmitted_and_role_scoped(self) -> None:
        instruction = (
            "Annotate a genomic variant with VEP and design a CRISPR "
            "protospacer and PAM for the mutation."
        )
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="active",
        )
        self.assertEqual(
            selection["practice_id"], "bio_variant_design_consistency"
        )
        self.assertFalse(selection["activated"])
        self.assertFalse(selection["admitted"])

        selection["activated"] = True
        pre_solve = build_solver_projection(selection, "pre_solve", CATALOG)
        verify = build_solver_projection(selection, "verify", CATALOG)
        reviewer = build_thin_reviewer_projection(selection, CATALOG)
        self.assertTrue(
            any("evidence-linked stages" in item for item in pre_solve["obligations"])
        )
        self.assertFalse(
            any("fragment span" in item for item in pre_solve["obligations"])
        )
        self.assertTrue(any("fragment span" in item for item in verify["obligations"]))
        self.assertIn(
            "guide_pam_strand_cut_and_distance_geometry",
            reviewer["detailed"]["prioritized_checks"],
        )
        for forbidden in ("expected variant", "expected coordinate", "expected guide"):
            self.assertNotIn(forbidden, " ".join(pre_solve["obligations"]).lower())
            self.assertNotIn(forbidden, " ".join(verify["obligations"]).lower())

    def test_adapter_identity_is_versioned(self) -> None:
        self.assertEqual(
            ThinFamilyV4p88ExperimentalStatemCodex.name(),
            "ziheng-yaxin-statem-codex-thin-family-v4p88-exp",
        )


if __name__ == "__main__":
    unittest.main()
