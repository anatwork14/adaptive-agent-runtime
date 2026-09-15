"""Public V10 freeze entry point.

V10 has a dedicated freeze implementation because the exact Codex snapshot is
an archived artifact, not a mutable provider-home path. The operation refuses
to overwrite an existing freeze directory and performs no provider inference.
"""

from freeze_v10 import freeze


if __name__ == "__main__":
    freeze()
