# V8 Clean-Base Hidden Harness Limitation

Docker qualification verified all three frozen image identities and all three
visible harnesses. Running the hidden harnesses against the clean base
repositories produced failures for Click, HTTPX, and python-dotenv. This is an
expected qualification limitation: the hidden graders exercise task behavior
that requires candidate changes, so an unmodified base repository is not a
valid scientific candidate.

The hidden tests were not inspected, copied into the review package, or
modified. This result is not treated as a scientific measurement. The
provider-free synthetic hidden-grader success path passed, which verifies the
controlled grader boundary without provider execution.
