#!/usr/bin/env sh
set -eu
python -m pip install --upgrade git+https://github.com/hnytgl/deepseek-cli.git
deepseek --doctor
