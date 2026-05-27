$ErrorActionPreference = "Stop"
$Repo = "git+https://github.com/hnytgl/deepseek-cli.git"
python -m pip install --upgrade $Repo
deepseek --doctor
