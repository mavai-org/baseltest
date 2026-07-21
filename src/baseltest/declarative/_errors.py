"""Reader-side refusals: configuration defects surfaced before any invocation."""

from baseltest.contract import BaseltestError


class ContractConfigurationError(BaseltestError):
    """The contract file (or the registrations it relies on) is not runnable as declared.

    Raised at load time, before any service invocation, with a message in
    the contract format's own vocabulary — never a framework internal. Covers
    malformed files, unknown or reserved keys, contradictions, unresolvable
    names, and invalid selection expressions.
    """
