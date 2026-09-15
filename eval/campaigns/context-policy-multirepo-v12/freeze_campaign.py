"""Public V12 freeze entry point.

V12 has a dedicated freeze implementation because the exact Codex snapshot is
an archived artifact, not a mutable provider-home path. The operation refuses
to overwrite an existing freeze directory and performs no provider inference.
"""

from freeze_v12 import freeze

if __name__ == "__main__":
    freeze()
