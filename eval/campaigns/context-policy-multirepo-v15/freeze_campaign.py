"""Public V15 freeze entry point.

V15 has a dedicated freeze implementation because the exact Codex snapshot is
an archived artifact, not a mutable provider-home path. The operation refuses
to overwrite an existing freeze directory and performs no provider inference.
"""

from freeze_v15 import freeze

if __name__ == "__main__":
    freeze()
