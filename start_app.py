import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
project_python = os.path.join(os.getcwd(), ".venv", "Scripts", "python.exe")
interpreter = project_python if os.path.isfile(project_python) else sys.executable
raise SystemExit(subprocess.run([interpreter, "-m", "streamlit", "run", "apps/gui/app.py"]).returncode)
