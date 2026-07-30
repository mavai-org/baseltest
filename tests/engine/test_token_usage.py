"""The usage-bearing reply seam: tokens flow from a Reply-returning
service through the engine's fold into the observation's cost lines;
string responses stay token-less and shape-stable."""

from baseltest.contract import Criterion, Reply, ServiceContract, contains
from baseltest.declarative._providers._protocol import openai_compatible_extract
from baseltest.engine import RunKind, RunPlan, execute
from baseltest.observation import RunObservation, observation_lines


def _contract(invoke):
    return ServiceContract(
        contract_id="token-usage-probe",
        invoke=invoke,
        criteria=(Criterion(name="greets", postconditions=(contains("hello"),)),),
    )


def _plan(samples=4):
    return RunPlan(kind=RunKind.MEASURE, samples=samples, inputs=("Alice",))


class TestReplySeam:
    def test_reply_tokens_fold_into_the_run_total(self):
        result = execute(
            _contract(lambda value: Reply("hello " + value, input_tokens=10, output_tokens=5)),
            _plan(),
        )
        assert result.total_tokens == 60  # 4 samples x 15

    def test_reply_text_is_judged_exactly_as_a_string(self):
        result = execute(
            _contract(lambda value: Reply("hello " + value, input_tokens=1, output_tokens=1)),
            _plan(),
        )
        assert result.overall_successes == 4

    def test_string_responses_stay_token_less(self):
        result = execute(_contract(lambda value: "hello " + value), _plan())
        assert result.total_tokens == 0

    def test_partial_usage_counts_nothing(self):
        # A reply reporting only one side has no stateable total.
        result = execute(_contract(lambda value: Reply("hello " + value, input_tokens=10)), _plan())
        assert result.total_tokens == 0


class TestCostLines:
    def test_observation_states_tokens_when_observed(self):
        result = execute(
            _contract(lambda value: Reply("hello " + value, input_tokens=10, output_tokens=5)),
            _plan(),
        )
        lines = observation_lines(RunObservation.from_run_result(result))
        assert "  totalTokens: 60" in lines
        assert "  avgTokensPerSample: 15" in lines

    def test_token_less_runs_keep_the_existing_cost_shape(self):
        result = execute(_contract(lambda value: "hello " + value), _plan())
        lines = observation_lines(RunObservation.from_run_result(result))
        assert not any("totalTokens" in line for line in lines)


class TestProviderExtract:
    def test_openai_compatible_usage_becomes_a_reply(self):
        body = {
            "choices": [{"message": {"content": "forty-two"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }
        reply = openai_compatible_extract(body)
        assert isinstance(reply, Reply)
        assert (reply.text, reply.total_tokens) == ("forty-two", 15)

    def test_absent_usage_stays_a_plain_string(self):
        body = {"choices": [{"message": {"content": "forty-two"}}]}
        assert openai_compatible_extract(body) == "forty-two"
