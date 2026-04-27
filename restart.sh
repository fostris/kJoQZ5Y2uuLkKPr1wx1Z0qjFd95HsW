#!/bin/bash
pkill -f streamlit
sleep 1
cd /Users/nikita/Desktop/projects/broker-dashboard
nohup /Users/nikita/Desktop/projects/broker-dashboard/venv/bin/python3 -m streamlit run app.py --server.port=8501 --server.headless=true --server.address=0.0.0.0 > streamlit.log 2>&1 &
echo "✅ Streamlit перезапущен → http://192.168.0.16:8501"
