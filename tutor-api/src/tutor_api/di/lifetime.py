"""How long a provided object lives, and what it means to get that wrong."""

from enum import Enum


class Lifetime(Enum):
    """The two spans an injected object may have.

    ``SINGLETON`` lives for the process; ``REQUEST`` lives for one HTTP
    request and may hold data belonging to one learner. The distinction is the
    whole point of the check in :mod:`tutor_api.di.container`.
    """

    SINGLETON = "singleton"
    REQUEST = "request"


class ScopeLeak(Exception):
    """A singleton depends on something that lives for one request.

    The defect this names is the highest-severity plausible one in this system
    (DEC-0013, superseding DEC-0003): a singleton that retains a learner-bound
    collaborator serves one minor's history to the next request. Raised at
    startup so the application refuses to boot rather than leaking at runtime.
    """

    def __init__(self, holder: type, captured: type) -> None:
        super().__init__(
            f"{holder.__name__} is a singleton but requires {captured.__name__}, "
            "which lives for one request. A singleton that captures "
            "request-scoped state serves one learner's data to the next."
        )


class UnregisteredDependency(Exception):
    """A provider requires something no provider supplies.

    Caught at startup for the same reason: an unresolvable graph must not
    become a 500 on the first request that touches it.
    """

    def __init__(self, holder: type, missing: type) -> None:
        super().__init__(
            f"{holder.__name__} requires {missing.__name__}, "
            "which no provider registers."
        )
