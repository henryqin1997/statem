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
from integrations.harbor.statem_codex_thin_family_v4p90_exp import (
    ThinFamilyV4p90ExperimentalStatemCodex,
)


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "examples" / "tb3-thin-family-practices-v7.json"


class ThinFamilyV4p90Test(unittest.TestCase):
    def _select(self, instruction: str, practice_id: str) -> dict[str, object]:
        selection = select_thin_family_practice(
            instruction,
            CATALOG,
            activation_mode="active",
        )
        self.assertEqual(selection["practice_id"], practice_id)
        self.assertFalse(selection["activated"])
        self.assertFalse(selection["admitted"])
        return selection

    def test_crypto_control_is_fresh_instance_and_candidate_blind(self) -> None:
        selection = self._select(
            "Reconstruct plaintext for a synthetic cipher in the general case "
            "from a known-plaintext pair and freshly generated random keys.",
            "synthetic_crypto_generalization_gate",
        )
        selection["activated"] = True
        pre_solve = build_solver_projection(selection, "pre_solve", CATALOG)
        verify = build_solver_projection(selection, "verify", CATALOG)
        reviewer = build_thin_reviewer_projection(selection, CATALOG)
        self.assertTrue(
            any("format recovery" in item for item in pre_solve["obligations"])
        )
        self.assertTrue(
            any("fresh local instances" in item for item in verify["obligations"])
        )
        self.assertIn(
            "fresh_key_and_plaintext_generalization",
            reviewer["detailed"]["prioritized_checks"],
        )
        rendered = " ".join(pre_solve["obligations"] + verify["obligations"]).lower()
        for forbidden in ("expected key", "expected plaintext", "expected ciphertext"):
            self.assertNotIn(forbidden, rendered)

    def test_bioanalytical_control_binds_cross_field_artifact(self) -> None:
        selection = self._select(
            "Interpret high-resolution MS/MS for a glycan precursor, infer its "
            "adduct, neutral mass, elemental formula, fragments, and canonical name.",
            "bioanalytical_artifact_consistency",
        )
        selection["activated"] = True
        pre_solve = build_solver_projection(selection, "pre_solve", CATALOG)
        verify = build_solver_projection(selection, "verify", CATALOG)
        reviewer = build_thin_reviewer_projection(selection, CATALOG)
        self.assertTrue(
            any("evidence-linked stages" in item for item in pre_solve["obligations"])
        )
        self.assertTrue(
            any("ion-to-neutral mass balance" in item for item in verify["obligations"])
        )
        self.assertIn(
            "neutral_mass_formula_and_adduct_balance",
            reviewer["detailed"]["prioritized_checks"],
        )
        rendered = " ".join(pre_solve["obligations"] + verify["obligations"]).lower()
        for forbidden in ("expected mass", "expected formula", "expected glycan"):
            self.assertNotIn(forbidden, rendered)

    def test_roy_routes_to_existing_numerical_control(self) -> None:
        selection = self._select(
            "Fit a physically appropriate continuous model to a molecular "
            "dihedral angle and spectroscopic wavenumber population, then predict "
            "numeric extrema and values with calibrated precision.",
            "numerical_model_compact",
        )
        selection["activated"] = True
        verify = build_solver_projection(selection, "verify", CATALOG)
        self.assertTrue(
            any("analytic or independent numerical sanity" in item for item in verify["obligations"])
        )

    def test_adapter_identity_is_versioned(self) -> None:
        self.assertEqual(
            ThinFamilyV4p90ExperimentalStatemCodex.name(),
            "ziheng-yaxin-statem-codex-thin-family-v4p90-exp",
        )


if __name__ == "__main__":
    unittest.main()
