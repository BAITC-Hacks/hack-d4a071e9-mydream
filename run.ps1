# Запуск на Windows: .\run.ps1 install | run | check | test | app
param([string]$cmd = "run")
switch ($cmd) {
  "install" { pip install -r requirements.txt }
  "run"     { python -m moneygraph run --data data --out output }
  "check"   { python -m moneygraph check --out output }
  "test"    { pytest -q tests }
  "app"     { streamlit run app/streamlit_app.py }
  default   { Write-Host "install | run | check | test | app" }
}
