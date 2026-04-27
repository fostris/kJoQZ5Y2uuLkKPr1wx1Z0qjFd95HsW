#!/bin/bash
export HOME=/Users/nikita
export PATH="/opt/homebrew/bin:$PATH"
cd /Users/nikita/Desktop/projects/broker-dashboard
source venv/bin/activate
exec streamlit run app.py --server.port=8501 --server.headless=true --server.address=0.0.0.0
