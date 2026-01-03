@echo off
echo Installing dependencies...
pip install -r requirements.txt

echo Starting App...
python "run_local_app -2.py"
pause
