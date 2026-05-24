# 小智智控台模型预设持久化说明

小智全模块部署时，智控台的“模型配置 → 语音合成”通常不是直接读取 `data/.config.yaml`，而是读取 manager-api 使用的数据库。

因此 AngeVoice 小智适配需要同时完成两类持久化：

1. **适配器文件持久化**：通过 compose 的 `volumes` 把 `angevoice-adapter/*.py` 挂载到小智容器内的 `core/providers/tts/`。
2. **智控台模型配置持久化**：写入小智数据库中的 `ai_model_provider` 和 `ai_model_config`。

## Docker 权限要求

脚本会自动执行 Docker / Compose 操作，包括：

```text
patch compose
重建 xiaozhi-esp32-server 容器
必要时 stop/rm 旧的 xiaozhi-esp32-server 容器
重新 up 小智 server 容器
```

因此运行脚本的用户必须有 Docker 权限：

```text
root 用户：可以直接运行
普通用户：需要加入 docker 用户组，或使用 sudo 运行
NAS 面板终端：通常需要切到 root / 管理员终端
```

注意：脚本只会重建 `xiaozhi-esp32-server` 这个 server 容器；不会重建 db/redis，也不会删除 MySQL 数据目录、Redis、`models/`、`uploadfile/` 等持久化数据。

## 为什么只写 .config.yaml 不够？

`data/.config.yaml` 对无智控台或本地运行场景有用，但带智控台的小智全模块通常以数据库配置为主。只写 `.config.yaml` 可能出现：

- 智控台页面不显示 AngeVoice 模型；
- “新增模型”的接口类型下拉没有 `angevoice` / `angevoice_stream` / `angevoice_clone`；
- 手动新增成 `custom` 后不会走 AngeVoice 适配器；
- 重启或刷新后仍以数据库配置为准。

所以新版安装脚本会询问：

```text
是否导入 AngeVoice 智控台模型预设到数据库，重启后仍保留 [Y/n]
是否将当前选择的 AngeVoice 模型设为智控台默认 TTS [Y/n]
```

## 会写入哪些接口类型？

脚本会向 `ai_model_provider` 写入：

```text
angevoice          AngeVoice 非流式
angevoice_stream   AngeVoice 流式
angevoice_clone    AngeVoice 克隆非流式
```

这样智控台“新增模型”的接口类型里就能看到 AngeVoice 相关类型。

## 会写入哪些模型配置？

脚本会向 `ai_model_config` 写入这些 TTS 预设：

```text
AngeVoice Kokoro 非流式
AngeVoice Kokoro 流式
AngeVoice MOSS CPU 非流式
AngeVoice MOSS CUDA 非流式
AngeVoice MOSS CPU 流式
AngeVoice MOSS CUDA 流式
AngeVoice MOSS CPU 克隆非流式
AngeVoice MOSS CUDA 克隆非流式
AngeVoice MOSS CPU 克隆流式
AngeVoice MOSS CUDA 克隆流式
```

其中 `config_json.type` 对应适配器：

```text
angevoice        -> angevoice.py
angevoice_stream -> angevoice_stream.py
angevoice_clone  -> angevoice_clone.py
```

## 为什么要重建容器？

新增 volume 挂载后，只执行 `docker restart xiaozhi-esp32-server` 不会让新挂载生效。脚本会自动执行：

```bash
docker compose -f <compose文件> up -d --no-deps --force-recreate xiaozhi-esp32-server
```

`--no-deps` 的作用是只重建小智 server 容器，不触碰已运行的 `xiaozhi-esp32-server-db` 和 `xiaozhi-esp32-server-redis`，避免 NAS 面板或已有容器名导致 db/redis 冲突。

如果 compose 重建失败，脚本会尝试只删除并重建 `xiaozhi-esp32-server` 容器：

```bash
docker stop xiaozhi-esp32-server
docker rm xiaozhi-esp32-server
docker compose -f <compose文件> up -d --no-deps xiaozhi-esp32-server
```

这一步需要 Docker 权限；普通用户如果没有加入 `docker` 用户组，需要使用 `sudo` 或 root 终端。

## 默认数据库假设

小智官方全模块 Docker 通常使用 MySQL：

```text
容器名：xiaozhi-esp32-server-db
数据库：xiaozhi_esp32_server
账号：root
密码：读取 MYSQL_ROOT_PASSWORD，读取不到时默认 123456
```

脚本会优先从数据库容器环境变量读取：

```text
MYSQL_ROOT_PASSWORD
MYSQL_DATABASE
```

## 验证是否导入成功

```bash
docker exec -it xiaozhi-esp32-server-db mysql -uroot -p123456 xiaozhi_esp32_server -e "select id, model_type, model_code, model_name, is_default, is_enabled from ai_model_config where id like 'TTS_AngeVoice%';"

docker exec -it xiaozhi-esp32-server-db mysql -uroot -p123456 xiaozhi_esp32_server -e "select id, model_type, provider_code, name from ai_model_provider where id like 'SYSTEM_TTS_AngeVoice%';"
```

如果能看到 AngeVoice 记录，说明智控台持久化成功。

## 与小智前端的关系

AngeVoice 不修改小智前端源码，不替换智控台页面，不注入自定义 UI。所有适配都通过小智已有的模型供应器表和模型配置表完成，属于低侵入接入方式。
