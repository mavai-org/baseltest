"""The wheel installs the renderer under the name its platform uses.

The build hook and ``baseltest.declarative._report.bundled_renderer`` are two
halves of one decision: what the bundled renderer is called once installed.
The consumer asks the scripts directory for ``mavai.exe`` on Windows and
``mavai`` everywhere else; these tests hold the producer to the same rule, so
the two cannot disagree again. It is a naming rule, not a Windows behaviour,
and needs no Windows machine to check.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hatch_build.py"


def _hatch_build() -> Any:
    """The build hook module, loaded from the repository root by path.

    It is not part of the installed package — the build backend loads it out
    of the project directory — so a test reaches it the same way.
    """
    spec = importlib.util.spec_from_file_location("hatch_build", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: Every platform the release workflow builds a wheel for, and the name the
#: renderer must carry in each.
PLATFORMS = [
    ("manylinux_2_17_x86_64", "mavai"),
    ("manylinux_2_17_aarch64", "mavai"),
    ("macosx_11_0_arm64", "mavai"),
    ("macosx_10_12_x86_64", "mavai"),
    ("win_amd64", "mavai.exe"),
]


@pytest.mark.parametrize(("platform", "expected"), PLATFORMS)
def test_script_name_follows_the_platform(platform: str, expected: str) -> None:
    assert _hatch_build().script_name(platform) == expected


@pytest.mark.parametrize(("platform", "expected"), PLATFORMS)
def test_wheel_installs_the_renderer_under_that_name(
    platform: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _hatch_build()
    binary = tmp_path / "mavai"
    binary.write_bytes(b"")
    monkeypatch.setenv(module.BINARY, str(binary))
    monkeypatch.setenv(module.PLATFORM, platform)

    build_data: dict[str, Any] = {}
    hook = object.__new__(module.RendererBundleHook)
    hook.initialize("standard", build_data)

    assert build_data["shared_scripts"] == {str(binary): expected}
    assert build_data["tag"] == f"py3-none-{platform}"
    assert build_data["pure_python"] is False


def test_a_wheel_with_no_renderer_carries_no_script(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pure wheel and the sdist: nothing to name, nothing to tag."""
    module = _hatch_build()
    monkeypatch.delenv(module.BINARY, raising=False)
    monkeypatch.delenv(module.PLATFORM, raising=False)

    build_data: dict[str, Any] = {}
    object.__new__(module.RendererBundleHook).initialize("standard", build_data)

    assert build_data == {}
