# Copyright 2025 Flower Labs GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Flower dependency installation utilities."""


import hashlib
import shutil
import subprocess
import sys
from logging import DEBUG, INFO, WARNING
from pathlib import Path

from flwr.common.config import get_flwr_dir
from flwr.common.constant import DEPS_DIR
from flwr.common.logger import log


def get_deps_dir_hash(dependencies: list[str]) -> str:
    """Compute a deterministic hash for a list of dependency strings.

    Parameters
    ----------
    dependencies : list[str]
        List of PEP 508 dependency strings.

    Returns
    -------
    str
        SHA-256 hex digest of the sorted, newline-joined dependency list.
    """
    canonical = "\n".join(sorted(dependencies))
    return hashlib.sha256(canonical.encode()).hexdigest()


def get_deps_install_path(
    dependencies: list[str],
    flwr_dir: Path | None = None,
) -> Path:
    """Return the content-addressable deps directory path.

    Parameters
    ----------
    dependencies : list[str]
        List of PEP 508 dependency strings.
    flwr_dir : Path | None
        Flower directory. If None, uses the default.

    Returns
    -------
    Path
        Path to the deps directory for the given dependency set.
    """
    if flwr_dir is None:
        flwr_dir = get_flwr_dir()
    deps_hash = get_deps_dir_hash(dependencies)
    return flwr_dir / DEPS_DIR / deps_hash


def install_dependencies(
    dependencies: list[str],
    flwr_dir: Path | None = None,
) -> Path | None:
    """Install dependencies to a content-addressable directory.

    If the directory already exists and is non-empty, installation is skipped
    (idempotent). Different FABs with the same dependency list share the same
    directory.

    Parameters
    ----------
    dependencies : list[str]
        List of PEP 508 dependency strings from ``[project].dependencies``.
    flwr_dir : Path | None
        Flower directory. If None, uses the default.

    Returns
    -------
    Path | None
        Path to the installed deps directory, or None if no dependencies.
    """
    if not dependencies:
        return None

    deps_path = get_deps_install_path(dependencies, flwr_dir)

    # If already installed (content-addressable), skip
    if deps_path.exists() and any(deps_path.iterdir()):
        log(DEBUG, "Dependencies already installed at %s", deps_path)
        return deps_path

    deps_path.mkdir(parents=True, exist_ok=True)

    log(
        INFO,
        "Installing %d dependencies to %s",
        len(dependencies),
        deps_path,
    )

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        str(deps_path),
        "--quiet",
    ] + dependencies

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        log(WARNING, "Failed to install dependencies: %s", exc.stderr)
        shutil.rmtree(deps_path, ignore_errors=True)
        raise RuntimeError(
            f"Failed to install dependencies: {exc.stderr}"
        ) from exc

    log(INFO, "Dependencies installed successfully at %s", deps_path)
    return deps_path


def add_deps_to_sys_path(deps_path: Path) -> None:
    """Add the deps directory to ``sys.path`` if not already present.

    Parameters
    ----------
    deps_path : Path
        Path to the installed deps directory.
    """
    path_str = str(deps_path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
