FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY relay_server.py .
EXPOSE 8900
# 公网部署强烈建议加 --auth-token（在 compose/命令行里传）
CMD ["python", "relay_server.py", "--host", "0.0.0.0", "--port", "8900"]
