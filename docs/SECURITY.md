# AngeVoice 安全说明 / Security Notes

AngeVoice 默认面向本地、内网或可信环境部署。若要公网暴露，请先完成管理员改密、API Key 配置、反向代理与证据脱敏验证。接口位置见 [API 参考](API_REFERENCE.md)。

## 首次进入与管理员凭据

为避免用户首次拉取镜像后无法进入控制台或取得 API Key，Docker 部署保留开箱首次登录：

```text
用户名：admin
密码：admin123
```

管理后台会在默认凭据仍有效时显示显著风险提示。**公网暴露前必须修改**；管理页支持中文管理员用户名。修改完成后，应用只将 PBKDF2-HMAC-SHA256 哈希凭据写入：

```text
/app/credentials/admin-credentials.json
```

磁盘不会写入修改后的明文密码。`credentials/` 必须作为持久化卷随重启、镜像更新和 profile 切换保留。

需要首次启动前即使用自定义凭据时，可以建立不提交仓库的本地覆盖文件：

```bash
cp docker/angevoice.local.env.example docker/angevoice.local.env
# 修改本地文件中的管理员用户名和强密码；不得提交版本库或装入公开证据包。
```

## API Key

推荐 Docker 配置：

```bash
KOKORO_API_KEY=auto
ANGEVOICE_API_KEY_FILE=/app/credentials/.angevoice-api-key
```

首次启动自动生成随机 API Key；管理员登录后台后可查看/轮换。不得把完整 API Key 放入日志、截图、GitHub Issue、测试报告或公开交付包。

## 持久化目录

CPU、标准 GPU 与 Legacy GPU 兼容画像统一保留：

```text
/app/credentials  管理员哈希凭据和 API Key
/app/config       后台 runtime-config
/app/models       模型资产与下载缓存
/app/prompts      Voice Profiles 和参考 WAV
/app/outputs      输出音频
/app/logs         日志/诊断资料
```

## 诊断与证据脱敏

共享诊断资料或提交问题报告前，应运行敏感信息扫描器：

```bash
python3 scripts/evidence_secret_scan.py <证据目录或归档包>
```

扫描失败时不得发送或上传该证据包。至少不得包含：

```text
管理员明文密码
完整 API Key / Token
Authorization: Basic ...
Authorization: Bearer ...
本地 docker/angevoice.local.env
```

## 上传与模型资产

- Voice Profile / 浏览器录音仅保存用户提供的参考 WAV 与文本；公网部署应限制访问者。
- Kokoro `.pt` 音色上传仅允许完全可信来源；不可信 PyTorch 权重可能存在代码执行风险。
- 模型资产修复/下载接口必须受管理鉴权保护，下载源应由管理员选择并在诊断中可见。

## 更新提示

管理后台提供轻量版本检查与发布说明链接，只用于提示新版本；本版不做自动拉取镜像或自动升级。升级仍应先阅读发布说明、备份持久目录并在版本化镜像或测试部署中验证。
