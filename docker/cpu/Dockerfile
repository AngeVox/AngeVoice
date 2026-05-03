FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# 先安装 CPU 版 PyTorch
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 复制项目文件
COPY pyproject.toml README.md ./
COPY src/ src/
COPY models/ models/
COPY tests/ tests/

# 安装项目 + 测试依赖
RUN pip install --no-cache-dir -e ".[dev]"
RUN pip install --no-cache-dir httpx pytest-asyncio starlette

EXPOSE 8000

# 默认运行测试
CMD ["python", "-m", "pytest", "tests/test_docker_integration.py", "-v", "--tb=short"]
