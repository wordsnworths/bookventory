@echo off
echo Starting Bookstore App...
cd /d "%~dp0"
python -m streamlit run bookstore_app.py
pause