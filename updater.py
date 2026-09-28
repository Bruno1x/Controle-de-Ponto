"""Securely download and apply the latest public GitHub release on Windows."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from version import APP_VERSION, GITHUB_REPOSITORY, RELEASE_ASSET_NAME

API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
TIMEOUT_SECONDS = 8
VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = VERSION_PATTERN.fullmatch(value)
    return tuple(map(int, match.groups())) if match else None


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ControleDePonto-Miranda-Updater",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise OSError(f"GitHub retornou HTTP {response.status}")
        return json.loads(response.read(2 * 1024 * 1024))


def _download(url: str, destination: Path, expected_hash: str) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "ControleDePonto-Miranda-Updater"}
    )
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise OSError(f"Download retornou HTTP {response.status}")
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_DOWNLOAD_BYTES:
            raise OSError("O arquivo da atualização excede o limite permitido")
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise OSError("O arquivo da atualização excede o limite permitido")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    if digest.hexdigest().lower() != expected_hash.lower():
        destination.unlink(missing_ok=True)
        raise OSError("A verificação SHA-256 da atualização falhou")


def _apply_from_helper(staged_exe: Path, target_exe: Path) -> None:
    """Use the Windows inbox PowerShell to replace the running executable."""
    process_id = os.getpid()
    staged = str(staged_exe).replace("'", "''")
    target = str(target_exe).replace("'", "''")
    backup = str(target_exe.with_suffix(".previous.exe")).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
$pidToWait = {process_id}
$staged = '{staged}'
$target = '{target}'
$backup = '{backup}'
try {{
  while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 250 }}
  if (-not (Test-Path -LiteralPath $staged)) {{ throw 'Arquivo baixado não encontrado' }}
  if (Test-Path -LiteralPath $backup) {{ Remove-Item -LiteralPath $backup -Force }}
  Move-Item -LiteralPath $target -Destination $backup -Force
  try {{
    Move-Item -LiteralPath $staged -Destination $target -Force
    Start-Process -FilePath $target
    Start-Sleep -Seconds 5
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
  }} catch {{
    Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $backup -Destination $target -Force -ErrorAction SilentlyContinue
    throw
  }}
}} catch {{
  Write-Error $_
  if (Test-Path -LiteralPath $staged) {{ Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue }}
}}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        creationflags=flags,
        close_fds=True,
    )


def check_and_apply_update() -> bool:
    """Return True when an update has been staged and app should exit."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return False

    current_version = _version_tuple(APP_VERSION)
    if current_version is None:
        print("Versão local inválida; atualização automática ignorada.")
        return False

    print("Conferindo atualizações...")
    staged: Path | None = None
    try:
        release = _fetch_json(API_URL)
        if release.get("draft") or release.get("prerelease"):
            return False
        latest_version = _version_tuple(str(release.get("tag_name", "")))
        if latest_version is None or latest_version <= current_version:
            return False

        assets = release.get("assets", [])
        asset = next(
            (item for item in assets if item.get("name") == RELEASE_ASSET_NAME), None
        )
        if not asset or not asset.get("browser_download_url"):
            print("Atualização indisponível: executável não encontrado na versão publicada.")
            return False
        digest = asset.get("digest", "")
        if not isinstance(digest, str) or not digest.startswith("sha256:") or not SHA256_PATTERN.fullmatch(digest[7:]):
            print("Atualização ignorada: o GitHub não forneceu o hash SHA-256 do executável.")
            return False
        download_url = asset["browser_download_url"]
        if not download_url.startswith("https://github.com/"):
            print("Atualização ignorada: endereço do executável não confiável.")
            return False

        target = Path(sys.executable).resolve()
        descriptor, staged_name = tempfile.mkstemp(
            prefix="ControleDePonto-atualizacao-", suffix=".exe", dir=target.parent
        )
        os.close(descriptor)
        staged = Path(staged_name)
        _download(download_url, staged, digest.removeprefix("sha256:"))
        print(f"Atualização {release['tag_name']} verificada; reiniciando o aplicativo...")
        _apply_from_helper(staged, target)
        return True
    except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as exc:
        if staged is not None:
            staged.unlink(missing_ok=True)
        print(f"Não foi possível verificar atualizações; iniciando a versão atual. ({exc})")
        return False
