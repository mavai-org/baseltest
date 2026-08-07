"""Emitter conformance: baseline artefacts validate against the family schema.

The pinned copy of the published ``mavai-baseline-1`` JSON schema lives
under ``tests/conformance/interchange/``. It is the family's contract for
the measure artefact, and every baseline this package writes must validate
against it — the emitter and the schema agree here, in this repository's
own suite, rather than at integration time in a consumer.

The artefact is YAML; the schema addresses the parsed data model, which is
why each document is loaded before validation.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator
from ruamel.yaml import YAML

from baseltest.baseline import (
    BaselineRecord,
    CriterionCharacterisation,
    NormativeJudgement,
    write_baseline,
)
from baseltest.contract import DeliveryCause, FailureAxis, PostconditionStanding

_SCHEMA_PATH = Path(__file__).parent.parent / "conformance" / "interchange"
_SCHEMA = json.loads((_SCHEMA_PATH / "mavai-baseline-1.schema.json").read_text(encoding="utf-8"))


def _record(**overrides: object) -> BaselineRecord:
    fields: dict[str, object] = {
        "service_contract_id": "buildings-extractor",
        "service_name": "buildings-extractor-axa",
        "generated_at": datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        "confidence_level": 0.95,
        "inputs_identity": "3fd0a91c4e77b2085a1d",
        "samples_planned": 10,
        "samples_executed": 10,
        "criteria": {
            "extraction-matches-reviewed-values": CriterionCharacterisation(
                successes=2,
                trials=10,
                failure_distribution={"amount matches the reviewed value": 8},
                failure_axes={"amount matches the reviewed value": FailureAxis.CONDITION},
                judgement=NormativeJudgement(
                    state="failed", stipulated_threshold=0.95, confidence=0.95
                ),
                wilson_lower_bound=0.0686,
                optional_slack="1",
                standings=(
                    PostconditionStanding(
                        input_index=0,
                        postcondition="buildingSumInsured matches the reviewed value",
                        passed=0,
                        failed=1,
                        skipped=0,
                        optional=False,
                        path="$.buildingSumInsured.amount",
                        form="equals",
                        expected="1970300.00",
                    ),
                ),
            )
        },
        "covariate_profile": {"model": "mistral-small-4", "temperature": "0.0"},
        "factor_record": {"taskFormat": "mavai-contract/1"},
    }
    fields.update(overrides)
    return BaselineRecord(**fields)  # type: ignore[arg-type]


def _emitted(record: BaselineRecord, directory: Path) -> dict:
    text = write_baseline(record, directory).read_text(encoding="utf-8")
    return YAML(typ="safe", pure=True).load(text)


class TestBaselineInterchangeConformance:
    def test_a_written_baseline_validates_against_the_published_schema(
        self, tmp_path: Path
    ) -> None:
        document = _emitted(_record(), tmp_path)
        Draft202012Validator(_SCHEMA).validate(document)
        assert document["schemaVersion"] == "mavai-baseline-1"

    def test_the_identity_tuple_is_stated_in_full(self, tmp_path: Path) -> None:
        # No element of the tuple keys a record alone, so every element has
        # to survive serialisation (area rule 8).
        document = _emitted(_record(), tmp_path)
        assert document["serviceContractId"] == "buildings-extractor"
        assert document["serviceName"] == "buildings-extractor-axa"
        assert document["inputsIdentity"] == "3fd0a91c4e77b2085a1d"
        assert document["covariateProfile"] == {
            "model": "mistral-small-4",
            "temperature": "0.0",
        }

    def test_the_bound_is_stated_with_the_level_it_was_computed_at(self, tmp_path: Path) -> None:
        document = _emitted(_record(), tmp_path)
        criterion = document["criteria"]["extraction-matches-reviewed-values"]
        assert criterion["wilsonLowerBound"] == 0.0686
        assert document["confidenceLevel"] == 0.95

    def test_a_zero_trial_criterion_states_a_null_bound_and_validates(self, tmp_path: Path) -> None:
        # Null rather than absent: "no evidence" must stay distinguishable
        # from "an artefact that predates the field".
        record = _record(
            samples_executed=0,
            criteria={"unmeasured": CriterionCharacterisation(successes=0, trials=0)},
        )
        document = _emitted(record, tmp_path)
        Draft202012Validator(_SCHEMA).validate(document)
        criterion = document["criteria"]["unmeasured"]
        assert "wilsonLowerBound" in criterion
        assert criterion["wilsonLowerBound"] is None
        # The rate is not stateable at zero trials, and 0.0 would assert one
        # from the same non-evidence that makes the bound null.
        assert "observedPassRate" not in criterion

    def test_the_standings_state_the_family_shape_not_a_dialect_of_it(self, tmp_path: Path) -> None:
        # One standings shape across the family: the block the exploration
        # and optimization artefacts state, so a consumer reads standings
        # once rather than once per artefact.
        document = _emitted(_record(), tmp_path)
        criterion = document["criteria"]["extraction-matches-reviewed-values"]
        assert "postconditionStandings" not in criterion
        standings = criterion["standings"]
        assert standings["optionalSlack"] == "1"
        row = standings["rows"][0]
        assert row["inputIndex"] == 0
        assert row["check"] == "buildingSumInsured matches the reviewed value"
        assert row["optional"] is False
        assert row["path"] == "$.buildingSumInsured.amount"
        assert (row["passed"], row["failed"], row["skipped"]) == (0, 1, 0)

    def test_the_failure_axis_travels_with_each_entry(self, tmp_path: Path) -> None:
        document = _emitted(_record(), tmp_path)
        entries = document["criteria"]["extraction-matches-reviewed-values"]["failureDistribution"]
        assert entries[0]["reason"] == "condition"
        assert entries[0]["count"] == 8


def test_a_delivery_failure_states_its_cause_and_not_its_message(tmp_path: Path) -> None:
    """The baseline path builds entries from reasons, and a delivery reason
    is an interpolated message. The stated cause takes its place as the
    entry's identity — bounded, groupable, and carrying no endpoint."""
    message = (
        "service unreachable at https://secret-gateway.internal/v1/chat/completions: "
        "[Errno 61] Connection refused"
    )
    record = _record(
        criteria={
            "extraction-matches-reviewed-values": CriterionCharacterisation(
                successes=0,
                trials=10,
                failure_distribution={message: 10},
                delivery_causes={message: DeliveryCause.UNREACHABLE},
                wilson_lower_bound=0.0,
            )
        }
    )
    path = write_baseline(record, tmp_path)
    document = YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))
    Draft202012Validator(_SCHEMA).validate(document)

    entries = document["criteria"]["extraction-matches-reviewed-values"]["failureDistribution"]
    assert entries == [{"condition": "unreachable", "count": 10, "kind": "delivery"}]
    assert "secret-gateway.internal" not in path.read_text(encoding="utf-8")
    # No `reason:` beside it: the companion's axis describes trials that
    # were evaluated, and these never were.
    assert "reason" not in entries[0]


def test_an_evaluated_failure_keeps_its_axis_and_gains_the_kind(tmp_path: Path) -> None:
    path = write_baseline(_record(), tmp_path)
    document = YAML(typ="safe", pure=True).load(path.read_text(encoding="utf-8"))
    Draft202012Validator(_SCHEMA).validate(document)

    entries = document["criteria"]["extraction-matches-reviewed-values"]["failureDistribution"]
    assert entries[0]["kind"] == "evaluated"
    assert entries[0]["reason"] == "condition"
