# Kokoro TTS 中文版重构计划

> 作者：安歌  
> 日期：2026-05-02  
> 状态：草案

---

## 1. 当前问题

### 1.1 大量代码重复
- `tts-project-cpu/app/main.py`（422行）和 `tts-project-gpu/app/main.py`（428行）**几乎是完全相同的代码**，仅有 device 设置和 GPU 检测信息的差异
- 两个 `requirements.txt` 也几乎一样，只有 torch 安装源不同
- 两个 `templates/index.html` 也完全重复

### 1.2 模型路径查找逻辑混乱
- 使用5级路径回退机制（`potential_paths`），从 CWD → `__file__` 上溯3层 → 硬编码 `/app/models`
- 这种"猜路径"的方式脆弱且不可预测，调试困难
- 一旦路径找不到就默认用 `Path.cwd() / "models"`，可能指向错误位置

### 1.3 Monkey Patch KModel
```python
KModel.MODEL_NAMES[MODEL_DIR] = 'kokoro-v1_1-zh.pth'
```
- 直接修改第三方库的类属性，非常脆弱
- 升级 kokoro 库时可能随时失效
- 这是为了绕过 HuggingFace Hub 下载机制的 hack

### 1.4 没有日志系统
- 全部使用 `print()` + `flush=True` 输出调试信息
- 大量 `try/except` 中捕获 `UnicodeEncodeError` 只是为了防止 print 崩溃
- 没有日志级别区分（debug/info/warn/error）
- 生产环境无法有效排查问题

### 1.5 错误处理过度防御
- `process_tts` 函数内嵌套了 4-5 层 try/except
- 每个 except 块又重新 import `JSONResponse`（文件内多处重复 import）
- 同样的 tensor → numpy 转换逻辑重复了 5+ 次

### 1.6 单文件巨型函数
- `process_tts` 一个函数 200 行，混合了：文本清理、语言检测、文本分割、TTS 推理、音频拼接、格式转换
- 无法单独测试任何一部分

### 1.7 缺少包管理
- 没有 `setup.py` / `pyproject.toml`
- 没有 `__init__.py`
- 不能通过 `pip install` 安装
- 不能作为库 import 使用

### 1.8 配置硬编码
- `SAMPLE_RATE = 24000` 硬编码
- 端口 `8000`/`8001` 硬编码
- CORS 全开 `allow_origins=["*"]`
- 速度函数 `speed_callable` 参数写死
- `max_segment_length = 100` 硬编码

### 1.9 `run-tts.py` 的问题
- 是一个交互式启动器 + 依赖安装器，职责混杂
- 会自动 `pip uninstall` 并重装 torch（危险操作）
- 硬编码清华镜像源
- 和主服务代码完全分离，维护两套逻辑

### 1.10 API 设计不一致
- `/api/tts` 支持 POST（Form + JSON）和 GET
- `/api/tts/tts` 还有一个 `character` 参数用 URL 编码的键值对传参
- 参数别名太多：`text`/`input`/`prompt`、`voice`/`speaker`/`character`、`speed`/`rate`

---

## 2. 目标架构

### 2.1 核心设计原则
- **一个代码库**，通过配置切换 CPU/GPU
- **关注点分离**：模型、推理、API、配置各自独立
- **可作为库使用**，也能独立运行服务
- **零 monkey patch**

### 2.2 模块划分

```
kokoro_tts_zh/
├── __init__.py          # 公开 API：TTSClient, synthesize()
├── config.py            # 配置管理（YAML + 环境变量 + defaults）
├── engine.py            # TTS 引擎核心（模型加载、推理、文本处理）
├── server.py            # FastAPI 路由（可选，serve 模式才用）
├── utils.py             # 文本清理、语言检测、音频处理工具函数
├── text_processing.py   # 文本分割、标点处理
└── errors.py            # 自定义异常
```

### 2.3 配置管理方案

使用 **YAML 文件 + 环境变量覆盖** 的方式：

```python
# config.py
from dataclasses import dataclass, field
from pathlib import Path
import os
import yaml

@dataclass
class TTSConfig:
    # 模型配置
    model_path: str = ""           # 模型目录路径（必填）
    model_name: str = "kokoro-v1_1-zh.pth"
    
    # 推理配置
    device: str = "auto"           # auto / cpu / cuda
    sample_rate: int = 24000
    num_threads: int = 0           # 0 = auto
    
    # 文本处理
    max_segment_length: int = 100
    default_speed: float = 1.0
    english_threshold: float = 0.6  # 英文字符占比阈值
    
    # 服务配置（仅 server 模式）
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list = field(default_factory=lambda: ["*"])

    @classmethod
    def from_yaml(cls, path: str) -> "TTSConfig":
        """从 YAML 文件加载配置"""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    @classmethod
    def from_env(cls) -> "TTSConfig":
        """从环境变量加载（前缀 KOKORO_）"""
        config = cls()
        if v := os.environ.get("KOKORO_MODEL_PATH"):
            config.model_path = v
        if v := os.environ.get("KOKORO_DEVICE"):
            config.device = v
        # ... 其他字段
        return config
    
    def resolve(self) -> "TTSConfig":
        """合并环境变量覆盖 + 验证"""
        if not self.model_path:
            raise ValueError("model_path 必须指定，或设置 KOKORO_MODEL_PATH 环境变量")
        if self.device == "auto":
            import torch
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        return self
```

使用示例：

```yaml
# config.yaml
model_path: /path/to/models
device: auto
sample_rate: 24000
host: 0.0.0.0
port: 8000
```

```bash
# 环境变量覆盖
KOKORO_MODEL_PATH=/data/models KOKORO_DEVICE=cpu python -m kokoro_tts_zh.server
```

### 2.4 TTS 引擎核心

```python
# engine.py
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Generator
import numpy as np
import torch
from kokoro import KModel, KPipeline

from .config import TTSConfig
from .text_processing import split_text, detect_language
from .errors import ModelNotFoundError, SynthesisError

logger = logging.getLogger(__name__)

@dataclass
class SynthesisResult:
    audio: np.ndarray       # shape: (samples,) or (samples, 1)
    sample_rate: int
    duration_seconds: float

class TTSEngine:
    """Kokoro TTS 中文引擎"""
    
    def __init__(self, config: TTSConfig):
        self.config = config.resolve()
        self._model = None
        self._zh_pipeline = None
        self._en_pipeline = None
    
    def load(self) -> "TTSEngine":
        """加载模型（延迟初始化也可）"""
        cfg = self.config
        model_path = cfg.model_path
        
        logger.info(f"加载模型: {model_path}, device={cfg.device}")
        
        # 设置线程数
        if cfg.num_threads > 0:
            torch.set_num_threads(cfg.num_threads)
        
        # 加载模型
        self._model = KModel(repo_id=model_path).to(cfg.device).eval()
        
        # 英文 pipeline（不需要模型，只做 G2P）
        self._en_pipeline = KPipeline(lang_code='a', repo_id=model_path, model=False)
        
        # 中文 pipeline
        self._zh_pipeline = KPipeline(
            lang_code='z',
            repo_id=model_path,
            model=self._model,
            en_callable=self._en_callable,
        )
        
        logger.info("模型加载完成")
        return self
    
    def _en_callable(self, text: str) -> str:
        """英文发音处理"""
        if text == 'Kokoro':
            return 'kˈOkəɹO'
        elif text == 'Sol':
            return 'sˈOl'
        try:
            return next(self._en_pipeline(text)).phonemes
        except Exception as e:
            logger.warning(f"英文 G2P 失败: {e}")
            return text
    
    def _make_speed_callable(self, speed: float):
        """创建速度回调函数"""
        def speed_fn(len_ps):
            if speed != 1.0:
                return speed
            s = 0.8
            if len_ps <= 83:
                s = 1
            elif len_ps < 183:
                s = 1 - (len_ps - 83) / 500
            return s * 1.1
        return speed_fn
    
    def synthesize(
        self, 
        text: str, 
        voice: str = "zf_001", 
        speed: float = 1.0,
    ) -> SynthesisResult:
        """合成语音"""
        cfg = self.config
        
        # 文本预处理
        text = self._clean_text(text)
        is_english = detect_language(text, cfg.english_threshold)
        
        # 分段
        segments = split_text(text, cfg.max_segment_length)
        logger.debug(f"文本分段: {len(segments)} 段, language={'en' if is_english else 'zh'}")
        
        # 逐段合成
        all_wavs = []
        speed_fn = self._make_speed_callable(speed)
        pipeline = self._en_pipeline if is_english else self._zh_pipeline
        
        for i, segment in enumerate(segments):
            try:
                result = next(pipeline(segment, voice=voice, speed=speed_fn))
                wav = self._to_numpy(result.audio)
                if wav is not None:
                    all_wavs.append(wav)
            except Exception as e:
                logger.warning(f"第 {i+1} 段合成失败，尝试中文 pipeline: {e}")
                try:
                    result = next(self._zh_pipeline(segment, voice=voice, speed=speed_fn))
                    wav = self._to_numpy(result.audio)
                    if wav is not None:
                        all_wavs.append(wav)
                except Exception as e2:
                    logger.error(f"第 {i+1} 段中文合成也失败: {e2}")
        
        if not all_wavs:
            raise SynthesisError("所有文本段合成失败，未生成有效音频")
        
        # 拼接
        audio = np.concatenate(all_wavs)
        duration = len(audio) / cfg.sample_rate
        
        return SynthesisResult(
            audio=audio,
            sample_rate=cfg.sample_rate,
            duration_seconds=duration,
        )
    
    def get_available_voices(self) -> list[str]:
        """获取可用声音列表"""
        voices_dir = Path(self.config.model_path) / "voices"
        if voices_dir.exists():
            return [f.stem for f in voices_dir.glob("*.pt")]
        return []
    
    @staticmethod
    def _clean_text(text: str) -> str:
        """清理文本"""
        text = ''.join(c if c.isprintable() or c.isspace() else ' ' for c in text)
        return text.strip().replace('\n', ' ').replace('\r', ' ').replace('  ', ' ')
    
    @staticmethod
    def _to_numpy(audio) -> np.ndarray | None:
        """将音频数据统一转为 numpy"""
        if audio is None:
            return None
        if isinstance(audio, torch.Tensor):
            audio = audio.cpu().numpy()
        if isinstance(audio, np.ndarray):
            if audio.ndim == 1:
                audio = audio.reshape(-1, 1)
            return audio
        return None
```

### 2.5 简化的 API 层

```python
# server.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from io import BytesIO
import soundfile as sf
import logging

from .config import TTSConfig
from .engine import TTSEngine, SynthesisError

logger = logging.getLogger(__name__)

class TTSRequest(BaseModel):
    text: str
    voice: str = "zf_001"
    speed: float = Field(default=1.0, ge=0.1, le=3.0)

class TTSResponse(BaseModel):
    duration: float
    sample_rate: int

def create_app(config: TTSConfig | None = None) -> FastAPI:
    """创建 FastAPI 应用"""
    if config is None:
        config = TTSConfig.from_env().resolve()
    
    app = FastAPI(title="Kokoro TTS 中文版", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    engine = TTSEngine(config).load()
    
    @app.post("/api/tts", response_class=StreamingResponse)
    async def tts(req: TTSRequest):
        try:
            result = engine.synthesize(req.text, req.voice, req.speed)
            buffer = BytesIO()
            sf.write(buffer, result.audio, result.sample_rate, format='WAV')
            buffer.seek(0)
            return StreamingResponse(buffer, media_type="audio/wav")
        except SynthesisError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @app.get("/api/tts/voices")
    async def list_voices():
        return {"voices": engine.get_available_voices()}
    
    return app
```

### 2.6 公开 API（库模式）

```python
# __init__.py
from .config import TTSConfig
from .engine import TTSEngine, SynthesisResult
from .errors import SynthesisError, ModelNotFoundError

__all__ = ["TTSConfig", "TTSEngine", "SynthesisResult", "synthesize"]

def synthesize(
    text: str,
    voice: str = "zf_001",
    speed: float = 1.0,
    model_path: str | None = None,
    device: str = "auto",
    output: str | None = None,  # 输出文件路径
) -> SynthesisResult:
    """一行调用合成语音"""
    config = TTSConfig(
        model_path=model_path or "",
        device=device,
    )
    engine = TTSEngine(config).load()
    result = engine.synthesize(text, voice, speed)
    
    if output:
        import soundfile as sf
        sf.write(output, result.audio, result.sample_rate)
    
    return result
```

使用方式：

```python
# 作为库直接调用
from kokoro_tts_zh import synthesize

result = synthesize("你好世界", voice="zf_001", output="hello.wav")

# 或者高级用法
from kokoro_tts_zh import TTSEngine, TTSConfig

config = TTSConfig(model_path="/data/models", device="cuda")
engine = TTSEngine(config).load()

for text in paragraphs:
    result = engine.synthesize(text)
    play_audio(result.audio)
```

---

## 3. 阅读器集成方案

### 3.1 方案对比

#### 方案 A：Python 包 import（pip install kokoro-tts-zh）

**优点：**
- 最简单的集成方式，一行 `pip install`
- 直接 `from kokoro_tts_zh import synthesize` 调用
- 不需要额外进程
- 可以细粒度控制（逐句合成、取消、进度回调）

**缺点：**
- 阅读器如果是 Python 写的才能用
- 模型依赖较重（~160MB 模型文件 + PyTorch）
- 首次加载模型需要 2-5 秒

**适合场景：** Python 桌面应用（PyQt/Tkinter）、Jupyter 环境、自动化脚本

#### 方案 B：独立服务模式（当前方式，但更干净）

**优点：**
- 语言无关，任何能发 HTTP 请求的客户端都能用
- 模型只加载一次，服务复用
- 可以独立部署和更新
- 多客户端共享

**缺点：**
- 需要管理一个额外进程
- 网络延迟（局域网内几乎可忽略）
- 部署复杂度增加

**适合场景：** 多设备共享 TTS、服务器部署、已有微服务架构

#### 方案 C：进程内模式（不启服务器，直接 Python API 调用）

**优点：**
- 无网络开销，延迟最低
- 进程内直接调用，最简单的部署
- 可以在应用启动时预加载模型

**缺点：**
- 模型占用应用进程的内存
- 如果是移动 App（iOS/Android），需要用 Python 桥接（Chaquopy/pybind11）

**适合场景：** 桌面阅读器应用（Electron + Python 后端、Python 原生应用）

### 3.2 推荐方案：方案 A + C 结合

**对于桌面阅读器（Electron/Qt/Tkinter）：**

推荐 **方案 A**（pip install 包 + 进程内调用），原因：

1. **桌面应用完全可以嵌入 Python**：Electron 可以 spawn Python 进程，Qt/Tkinter 本身就是 Python
2. **延迟敏感**：阅读器需要逐句或逐段朗读，每次 HTTP 请求的开销不划算
3. **用户体验**：模型预加载后，后续合成几乎即时响应
4. **独立性**：不需要用户手动启动 TTS 服务

**具体集成方式：**

```python
# 阅读器的 TTS 管理器
from kokoro_tts_zh import TTSEngine, TTSConfig

class ReaderTTSManager:
    def __init__(self, model_path: str):
        config = TTSConfig(model_path=model_path, device="auto")
        self.engine = TTSEngine(config).load()
        self.current_paragraph = 0
    
    def speak_paragraph(self, text: str, voice: str = "zf_001"):
        """朗读一个段落"""
        result = self.engine.synthesize(text, voice=voice)
        return result.audio, result.sample_rate
    
    def speak_paragraph_streaming(self, text: str, voice: str = "zf_001"):
        """流式朗读（每句回调）"""
        # 按句子分割，逐句返回音频
        for sentence in self._split_sentences(text):
            result = self.engine.synthesize(sentence, voice=voice)
            yield result.audio, result.sample_rate
```

**对于移动端（iOS/Android）：**

推荐 **方案 B**（独立服务），因为：
- 移动端无法直接运行 Python
- 需要通过 HTTP 与 TTS 服务通信
- 服务可以部署在局域网内的 NAS 或路由器上

```dart
// Flutter 示例
class TTSService {
  final String baseUrl;
  
  Future<Uint8List> synthesize(String text, String voice) async {
    final response = await http.post(
      Uri.parse('$baseUrl/api/tts'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'text': text, 'voice': voice}),
    );
    return response.bodyBytes;
  }
}
```

---

## 4. 新目录结构

```
kokoro-tts-zh/
├── pyproject.toml              # 包配置（pip install 可用）
├── README.md
├── CHANGELOG.md
├── LICENSE
│
├── config.yaml.example         # 配置模板
├── .env.example                # 环境变量模板
│
├── src/
│   └── kokoro_tts_zh/
│       ├── __init__.py         # 公开 API
│       ├── config.py           # 配置管理
│       ├── engine.py           # TTS 引擎核心
│       ├── text_processing.py  # 文本处理工具
│       ├── utils.py            # 通用工具函数
│       ├── errors.py           # 自定义异常
│       └── server.py           # FastAPI 服务（可选依赖）
│
├── models/                     # 模型文件（gitignore，不入库）
│   ├── kokoro-v1_1-zh.pth
│   └── voices/
│       ├── zf_001.pt
│       ├── zm_001.pt
│       └── ...
│
├── examples/
│   ├── basic_usage.py          # 基础用法示例
│   ├── reader_integration.py   # 阅读器集成示例
│   └── batch_synthesis.py      # 批量合成示例
│
├── tests/
│   ├── test_engine.py
│   ├── test_text_processing.py
│   └── test_server.py
│
├── docker/
│   ├── Dockerfile.cpu
│   ├── Dockerfile.gpu
│   └── docker-compose.yaml
│
└── scripts/
    ├── download_model.py       # 下载模型脚本
    └── benchmark.py            # 性能测试
```

**关键变化：**
- 使用 `src/` layout（Python 社区最佳实践）
- `pyproject.toml` 取代 `setup.py`
- CPU/GPU 不再分离，通过 `device` 配置切换
- 模型文件单独管理，不进入 git
- 有示例代码和测试

---

## 5. 迁移步骤

### 阶段一：基础重构（1-2天）

**步骤 1：创建包结构**
```bash
# 创建目录
mkdir -p src/kokoro_tts_zh examples tests

# 创建 pyproject.toml
cat > pyproject.toml << 'EOF'
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "kokoro-tts-zh"
version = "2.0.0"
description = "Kokoro TTS 中文语音合成引擎"
requires-python = ">=3.10"
dependencies = [
    "kokoro>=0.8.1",
    "misaki[zh]>=0.8.1",
    "numpy",
    "soundfile",
    "torch",
]

[project.optional-dependencies]
server = ["fastapi", "uvicorn[standard]"]
dev = ["pytest", "pytest-asyncio", "httpx"]

[project.scripts]
kokoro-tts = "kokoro_tts_zh.server:main"
EOF
```

**步骤 2：提取配置管理** → `config.py`
- 从 main.py 中提取所有硬编码值
- 实现 `TTSConfig` dataclass
- 支持 YAML 和环境变量

**步骤 3：提取文本处理** → `text_processing.py`
- 从 `process_tts` 中提取：`_clean_text`、`detect_language`、`split_text`
- 写单元测试

**步骤 4：实现 TTS 引擎** → `engine.py`
- 将 `process_tts` 重写为 `TTSEngine.synthesize()`
- 去掉所有重复的 tensor → numpy 转换
- 用 logging 替代所有 print
- 去掉 monkey patch

**步骤 5：实现 API 层** → `server.py`
- 用 Pydantic 定义请求/响应模型
- 统一 API 参数（不再有 `/api/tts/tts` 的冗余路由）
- 用 `create_app()` 工厂模式创建应用

### 阶段二：集成与测试（1天）

**步骤 6：编写示例代码**
- `examples/basic_usage.py`
- `examples/reader_integration.py`
- `examples/batch_synthesis.py`

**步骤 7：编写测试**
- `test_text_processing.py`：测试文本分割、语言检测
- `test_engine.py`：测试合成流程（mock model）
- `test_server.py`：测试 API 端点

**步骤 8：编写 Docker 配置**
- 统一为一个 Dockerfile，通过 `--build-arg DEVICE=cpu|gpu` 切换
- docker-compose 支持 CPU 和 GPU 两种部署

### 阶段三：清理与文档（0.5天）

**步骤 9：清理旧文件**
- 删除 `tts-project-cpu/` 和 `tts-project-gpu/`
- 删除 `run-tts.py`
- 更新 `.gitignore`（排除 models/、*.pyc 等）

**步骤 10：更新文档**
- README.md：新用法、安装方式、配置说明
- CHANGELOG.md：记录 v2.0.0 变更

---

## 6. 注意事项与风险

### 6.1 向后兼容
- 新 API 参数格式变化（去掉 `character` 等非标准参数）
- 建议在 server.py 中保留一个兼容层，打印 deprecation warning

### 6.2 模型加载时间
- TTSEngine.load() 需要 2-5 秒，应该在应用启动时预加载
- 建议提供 `TTSEngine.load_async()` 异步加载版本

### 6.3 线程安全
- kokoro 的 pipeline 不一定是线程安全的
- 需要在文档中说明：不要在多线程中共享同一个 engine 实例
- 可以用 `threading.Lock` 或每个线程一个 engine

### 6.4 内存管理
- 模型常驻内存约 200-400MB（取决于 device）
- 提供 `engine.unload()` 方法释放显存/内存

---

## 7. 总结

| 项目 | 当前 | 重构后 |
|------|------|--------|
| 代码行数 | ~850行（两个重复文件） | ~500行（单一代码库） |
| 文件数 | 2个 main.py + run-tts.py | 6个模块 |
| 配置方式 | 硬编码 + 环境变量 | YAML + 环境变量 + dataclass |
| 日志 | print() | logging 模块 |
| 安装方式 | 手动 clone + pip install -r | pip install kokoro-tts-zh |
| API | 3个路由，参数混乱 | 2个路由，Pydantic 校验 |
| 可测试性 | 无法单独测试 | 每个模块可独立测试 |
| CPU/GPU | 两个目录 | 一个配置切换 |
