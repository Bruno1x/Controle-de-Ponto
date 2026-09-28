"""Versão do aplicativo incorporada durante a compilação do executável."""

import os


APP_VERSION = os.environ.get("CONTROLE_PONTO_VERSION", "1.0.0")
GITHUB_REPOSITORY = "Bruno1x/Controle-de-Ponto"
RELEASE_ASSET_NAME = "ControleDePonto-Miranda-Revisado.exe"
