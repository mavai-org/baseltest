"""Defect diagnosis: the enriched, actionable stop a transform defect earns.

A transform (or a postcondition) signals an *unusable response* by raising
:class:`~baseltest.contract.model.TransformError` — an anticipated, in-band
failed trial. Any *other* exception escaping a transform or a postcondition
is a **defect**: a bug in the testing machinery, not a countable outcome and
not a sample. A defect must still stop, but it must stop with a diagnosis, not
a bare traceback: the sampling loop catches the lightweight
:class:`~baseltest.contract.evaluation.TrialDefectError` carrier and enriches it,
here, with the driving input's structural context into a
:class:`DefectDiagnosisError` the orchestration layer's per-configuration boundary
records and reports.

This module owns only the *diagnosis*, never the *accounting*: a defect is
never converted into a trial failure, never counted toward any denominator.
"""

# The contract a defect diagnosis always cites — the single line that told the
# field, too late, where the boundary between a failed trial and a defect sits.
TRANSFORM_CONTRACT_NOTE = (
    "transforms signal an unusable response by raising TransformError; any "
    "other exception is treated as a defect in the transform"
)


class DefectDiagnosisError(Exception):
    """A transform/postcondition defect, diagnosed with its driving context.

    Carries the offending transform/view, the criterion and postcondition
    under evaluation, the escaped exception's type and text, and a bounded
    excerpt of the driving input (its structural index plus a length-capped
    quote). Its message is the actionable stop the orchestration layer records
    for the configuration a defect ended.

    Attributes:
        view: The transform/view whose evaluation raised the defect.
        criterion: The criterion under evaluation.
        postcondition: The postcondition under evaluation.
        exception_type: The escaped exception's type name.
        exception_text: The escaped exception's ``str()``.
        input_index: The driving input's position in the plan's input list.
        input_excerpt: A bounded excerpt of the driving input's text.
    """

    def __init__(
        self,
        *,
        view: str,
        criterion: str,
        postcondition: str,
        exception_type: str,
        exception_text: str,
        input_index: int,
        input_excerpt: str,
    ) -> None:
        self.view = view
        self.criterion = criterion
        self.postcondition = postcondition
        self.exception_type = exception_type
        self.exception_text = exception_text
        self.input_index = input_index
        self.input_excerpt = input_excerpt
        super().__init__(
            f"defect in transform/view {view!r} while evaluating criterion "
            f"{criterion!r}, postcondition {postcondition!r} on input "
            f"{input_index} ({input_excerpt!r}): {exception_type}: "
            f"{exception_text}. {TRANSFORM_CONTRACT_NOTE}."
        )
