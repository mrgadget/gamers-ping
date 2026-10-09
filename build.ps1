# Builds a single portable exe: dist\GamersPing.exe
python -m pip install -r requirements-dev.txt
python -m PyInstaller --onefile --windowed --name GamersPing --clean --noconfirm launcher.py
Write-Host "Built: $(Resolve-Path dist\GamersPing.exe)"
