"""Public names of the step 5 modules (docs/modules.md section 4, frozen for step 5)."""

from __future__ import annotations

import dataclasses

import j1939logger.identify as identify
from j1939logger.identify import Identification


def test_SC_6_identify_public_names() -> None:
    assert {"Identification", "classify", "reclassify", "identify", "identification_record"} <= set(
        identify.__all__
    )
    fields = [f.name for f in dataclasses.fields(Identification)]
    assert fields[:9] == [
        "category", "sev", "classification_rule", "type_guess", "make", "model", "make_source",
        "confidence", "id_source",
    ]  # fmt: skip
    assert {"profile_match", "disagreements", "candidates", "reclassified"} <= set(fields)
