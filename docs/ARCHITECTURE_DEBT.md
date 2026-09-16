# AngeVoice 架构债务台账

本文件是当前架构债状态的唯一登记入口；设计说明见 [ARCHITECTURE.md](ARCHITECTURE.md)，测试归属见 [TESTING.md](TESTING.md)，兼容移除条件见 [COMPATIBILITY_LEDGER.md](COMPATIBILITY_LEDGER.md)。外部报告保留审计证据，不作为第二份可独立演进的状态台账。

## 基线、状态与历史映射

初始对照：v2.6.616 → `b343554fb98f6cf0585ae5d3915c28e249a96acb`，70 个提交。2026-09-07 首轮基座治理在该 HEAD 的本地工作树继续实施；“本地已验收”不代表已提交、发布或真实模型已通过。

旧《技术债务 v2》日期为 2026-07-01。其 P1=配置、P2=worker、P3=ZipVoice、P4=MOSS、P4.5=Kokoro、P5=Manager，与后续任务编号不同。后续 P1 是前端/i18n，P2 是配置与来源，P3 是引擎协议，P4 是 worker 生命周期，P5 是文本准备。稳定 AV-D ID 不随任务阶段编号变化。

状态：**已闭合**仅指本条声明的边界；**本地已验收**指已验证但尚未发布的本地实现；**部分完成**保留明确残余；**开放**尚未解决；**待环境验证**不能记为通过；**持续治理/设计保留**不是待机械删除的代码。

## 债务清单

| ID / 历史项 | 问题与职责归属 | 状态与证据 | 剩余风险 / 关闭条件 |
| --- | --- | --- | --- |
| AV-D001 / 2.1、旧 P1 | TTSConfig 跨域配置；config 与各 metadata owner | 部分完成：7 个领域默认值 owner 及 ENV/Admin 投影已收敛；metadata 合同 | facade 仍拥有大量字段/校验；按实际变更面拆职责，保持默认值、序列化、优先级兼容 |
| AV-D002 / 2.2、旧 P1 | ENV 编排；config_env | 部分完成：声明、解析和执行职责已分离；2026-09-08 配置 ENV 合同 | apply_env 33→1，移除历史豁免；标量→凭据/CORS→模型路径保持原顺序；领域声明仍混合投影，未来随真实领域变更演进，不造第二套配置框架 |
| AV-D003 / 2.3、旧 P1 | 模型来源探测与下载策略；model_sources | 部分完成：fallback、受管资产校验与 metadata 已改善；来源合同 | 探测传输和日志边界由 AV-D004/005 跟踪；下载/资产结构仍集中，未来按实际变化拆解 |
| AV-D004 / 2.3 | 探测 URL 和重定向输入；model_source_probe | 已补齐 Python 3.10 的 HTTP 308 支持：2026-09-14 本地 3.10 全量及 3.12 定向合同通过；此前 CI 34761088672 暴露两个 308 失败 | 初始及重定向仅 HTTP/HTTPS，非法地址零网络调用；保留 GET/HEAD、循环上限、响应关闭、镜像/内网、默认代理/TLS；308 兼容分支随 Python 3.10 支持结束再评估移除；不保证外部镜像实时可用性 |
| AV-D005 / 2.3 | 第一方模型来源日志携带 URL/异常正文；model_sources 与资产校验 | 已发布（287d3bc）：首轮批次三格式化日志合同 | 固定摘要替代敏感正文/traceback，合成凭据标记不可见且 fallback 语义不变；第三方 SDK 自行输出不在本条保证内 |
| AV-D006 / 2.4、旧 P5 | Manager 生命周期与状态集中；engine_manager | 部分完成：具体引擎依赖已闭合、shutdown 正确性已增强；manager/shutdown 合同 | get_engine 25→15，加载执行与失败清理已分离并移除历史豁免；仍保持单一状态 owner 和原锁范围，路由聚合及其他生命周期职责需另定规格 |
| AV-D007 / 2.5、旧 P4 | MOSS 核心跨职责；MOSS core/runtime helpers | 部分完成：协议/流关闭改善，文本问题见 AV-D009 | runtime、prompt、VRAM、流生命周期仍耦合；只抽有独立责任及验证能力的边界，保留 CPU/CUDA/clone |
| AV-D008 / 2.5b、旧 P4.5 | Kokoro 加载/文本/推理职责；engine.py | 部分完成：延迟 English G2P、资产校验、prepared 路径；Kokoro 合同 | 未整体拆分；不因 MOSS/ZipVoice 更新而忽略默认引擎，但不机械创建四个包装类 |
| AV-D009 / 当前 P5 | service 与引擎重复通用 TN；合成服务及 Kokoro/MOSS | 已发布（287d3bc）：冻结文本合同 15 项；真实 spawn 替身集成 5 项，批次一 | 请求 TN 执行一次、raw 兼容、robust 保留、参数不串状态；真实模型验证独立见 AV-D019 |
| AV-D010 / 2.6 | MOSS streaming mixin；MossStreamingMixin | 部分完成：terminal/iterator close/prepared 保护 | 分支和资源状态仍集中；后续按解码与传输生命周期分界，禁止降级逐帧流式能力 |
| AV-D011 / 2.7、旧 P2 | worker 反向依赖具体引擎；workers/spec + 产品 factory | 已闭合（基础设施依赖边界）：WorkerSpec/manager import 合同 | 保持顶层可信 factory、禁止请求控制 loader；不等于兼容 shim 可删除 |
| AV-D012 / 2.8、旧 P2 | worker stream/main 与加载失败生命周期；process_worker | 已闭合（已验收范围）：stream 35→23、main 27→11、事务式 load；生命周期合同 | orchestration 残余、未知命令准入和 shutdown unload 错误诊断为后续低优先项；不得宣传 worker 零债务 |
| AV-D013 / 2.9、旧 P3 | ZipVoice CPU/CUDA 包装重复；zipvoice runtimes | 部分完成：2026-09-08 共用参考校验、参数投影、指标与临时输出清理；双 runtime 行为回归 | load/unload、设备参数及上游路径读取继续独立；真实 CPU/CUDA 画像未验证，不能关闭整个 runtime 债务 |
| AV-D014 / 2.10 | ZipVoice assets/manifest；ZipVoiceAssetManager | 部分完成、本地未发布：来源身份、状态结构及唯一临时状态写入已验收；2026-09-16 增加同文件系统暂存校验后发布、目标路径级跨进程互斥；Windows/Linux 真实 spawn 验证共享 Vocos、反序清单、超时和进程退出 | 预置 SHA 仍为权威；整批失败不提交新状态但不回滚已发布文件；只约束合作 ensure 写入，status 非整批快照、runtime 不固定文件版本。保留原生文件系统错误，不承诺网络文件系统、断电持久性或强杀暂存清理；真实模型见 AV-D019 |
| AV-D015 / 2.11、旧 P6 | WS 首包、producer/send loop；ws session/streaming | 部分完成：首包编排、参考音频准备、请求投影与单帧发送已分离；2026-09-08 WS 行为回归 | parse/send 已为 6/14，移除历史复杂度豁免；修复首包 HTTPException 缺失导入，保留 finally 清理；2026-09-11 producer 显式关闭服务迭代器后发送结束通知，见 `angevoice-ws-producer-lifecycle`，移除原19复杂度豁免；取消为 best effort，队列不保证端到端背压 |
| AV-D016 / 2.12、旧 P7 | 路由注册依赖过多；service_extras / app assembly | 部分完成：2026-09-10 按批量、管理资源、格式查询显式组装；新旧入口 HTTP 回归 | 主路径不再传引擎/原始缓存/请求表，也不在 handler 从 app.state 取模型管理器；旧签名桥接保留，其他领域路由依赖仍需逐项核对 |
| AV-D017 / 2.13、2.13b | Adapter/参数协议；Registry、Adapter、EngineParameterSchema | 部分完成：capability、错误及构造 owner 已闭合；2026-09-11 参数采集与类型校验分离，容器值及整数溢出返回参数错误 | 参数边界证据 `angevoice-engine-parameter-boundary`（2026-09-10 开始）；2026-09-11 MOSS provider 规则独立，提示→配置→别名优先级保持，见 `angevoice-provider-policy-boundary`；registry/adapter 静态回边仍在，随真实模型扩展收敛，不新增注册中心 |
| AV-D018 / 2.17 | 测试组织与文档漂移；各领域维护者 | 部分完成：首轮批次二校正指南与领域索引 | 既有工单命名/AST 形状锁定尚未全量迁移；触及领域时演进合同、消除重复夹具，保留行为覆盖 |
| AV-D019 / 旧 P0 smoke | 真实模型/WeText/画像验证；模型运行与部署验收 | 待环境验证；批次一 model-environment.json 为历史环境快照 | 尚无三模型真实 HTTP/WS、取消恢复、raw/prepared 和听感完整验收证据；开工重新核对环境，不能把历史依赖缺失当成当前事实，无权重测试不可替代 |
| AV-D020 / 2.14 | SHA1 缓存文件名用途；moss/prompt | 开放、低优先；仅缓存命名 | 明确非安全用途或兼容 helper，保持文件名稳定；不当作密码学 P0 |
| AV-D021 / 2.15、2.16 | 部署监听和依赖审计；部署/依赖维护者 | 0.0.0.0 为设计保留；漏洞状态需按发布时重新审计 | 保持容器/NAS 可达；认证/TLS/代理按部署边界治理，旧 pip-audit 无漏洞结论不可继承；2026-09-13 安全升级及 GPU 残余见 [依赖安全基线](DEPENDENCY_SECURITY.md) |
| AV-D022 / 兼容层 | shim、alias、re-export 的迁移；各兼容维护域 | 持续治理；COMP-001～008 | 逐项满足兼容台账的版本/使用方/公告/smoke 门槛才删除，不因无主路径调用直接判死代码 |

用户词典持久化/CRUD、电子书章节和持久任务系统是功能计划，另行定义产品需求；已有批量 HTTP 接口不代表这些功能已交付。本台账不授权实现新功能。

## 后续工作清单（2026-09-14 校正）

本节与上表共用 AV-D ID，是执行清单，不另建第二份债务台账。旧 P0–P7 只表示历史来源，尤其旧 P5=Manager，与文本准备 P5 不同。每批开工重查调用链、共享状态和现有合同；发现旧方案不再适用时先更新本节，不按文件数或类名验收。

发布快照：基座治理已在 `287d3bc` 发布，依赖升级在 `ccbc498` 发布，Python 3.10 HTTP 308 修复在 `e05d33e` 发布。2026-09-14 ZipVoice 资产来源身份批次尚为本地候选，不能沿用旧提交的远端 CI 结果。后续批次默认本地施工，保留 README、冻结 P5 合同及既有未提交改动；发布单独标记。

| 批次 / 债务 | 要解决的实际问题 | 边界与验收 | 状态 |
| --- | --- | --- | --- |
| A0 / AV-D014，旧 P3 | 资产已学习摘要被跨 repo/revision 复用 | status/ensure 共用来源与 verified 准入；离线拒绝、在线刷新、预置 SHA 优先；同源篡改仍失败 | 本地已验收，未发布；证据 `angevoice-zipvoice-asset-identity` |
| A1 / AV-D014，旧 P3 | 状态 JSON 结构错误导致查询/加载异常；无效摘要被当成校验依据 | 非对象根、错误 files 类型按无记录处理；逐项检查摘要，不牵连其他有效记录；预置 SHA 离线验收保持 | 2026-09-15 本地已验收、未发布；3.10 全量 1640 passed / 4 skipped，3.12 定向 357 passed / 2 skipped；证据 `angevoice-asset-status-schema`（09-14 开始） |
| A2 / AV-D014，旧 P3 | 状态写入共用固定 .tmp，失败残留及并发覆盖 | 同目录唯一临时文件、失败清理、完整旧/新快照可见；双实例并发线程写入测试；保留原生替换错误及清理告警，不合并记录；不等于整批资产事务 | 2026-09-15 本地已验收、未发布；3.10 全量 1646 passed / 4 skipped，3.12 定向 290 passed / 2 skipped；证据 `angevoice-asset-status-write`；本轮 Docker 引擎不可用，未作 Linux 实机验证 |
| A3 / AV-D014，旧 P3 | SDK/复制直接写入资产目标，整批 ensure 无跨进程互斥 | SDK 同文件系统暂存、校验后单文件原子发布；外部缓存仅复制；按实际资产与状态路径排序加锁，涵盖读取记录至最终校验；整批失败可重试，不做整批回滚 | 2026-09-16 本地已验收、未发布；3.10 全量 1656 passed / 5 skipped，覆盖率 80.76%；Linux 容器离线资产/真实 spawn 106 passed，wheel 独立导入通过；证据 `angevoice-asset-transaction`（09-15 开始）。Windows 新增符号链接用例因权限跳过，由 Linux 实测补足；下一批 B1 先复核当前配置调用链 |
| B1 / AV-D001/002，旧 P1 | 配置安全校验和 load_config 的路径归一化仍集中 | 按现有领域 owner 收敛职责；保留 facade、默认值→ENV→runtime→显式覆盖顺序、错误和警告；新函数 ≤15，收紧 ratchet | 待资产边界稳定后施工 |
| B2 / AV-D003，旧 P1 | 来源选择、下载执行和 Kokoro 受管资产策略仍有集中逻辑 | 先辨别普通目录与受管目录；保持 fallback、revision、凭据委托、offline 和日志边界；不统一各模型本来不同的策略 | 待 B1 后复核 |
| C1 / AV-D007/010，旧 P4 | MOSS 显存策略、解码和隔离流编排仍共享较多状态 | 优先拆纯决策与生命周期编排；保留逐帧能力、取消/超时、raw/prepared、robust 与降级规则；替身不能代替 GPU smoke | 待独立规格 |
| C2 / AV-D008/013，旧 P4.5/P3 | Kokoro pipeline 生命周期和三 runtime 的实际重复点 | 按消费方验证是否值得共用；保留设备加载差异和默认引擎行为；不为对称创建 BaseRuntime 或四个同名类 | 待 C1 后按代码复核 |
| D1 / AV-D006，旧 P5 | Manager 只读状态展示仍与生命周期状态耦合 | 先分离只读投影，保留唯一状态 owner 与锁内快照；不得触发模型加载或改变 busy/重建/shutdown 语义 | 待独立规格 |
| D2 / AV-D016/017，旧 P7 | admin/audio/ws/status 路由依赖仍需逐域收敛 | 复用现有组装入口与领域服务；鉴权、公开目录、错误及参数合同保持；不造 ServiceLocator 或第二 Registry | 待 D1 后复核 |
| E1 / AV-D012/015，旧 P2/P6 | worker 命令准入/关闭诊断，以及取消和背压残余 | 原 spec/首包/send 已完成不重做；只为可复现缺口立项，保留尾帧、超时和 finally 语义 | 后续低优先复核 |
| V1 / AV-D019，旧 P0 | 三模型真实推理与硬件验收缺完整证据 | 已有环境运行 HTTP/WS、raw/prepared、prompt cache、取消恢复及听感；缺权重明确未验证，不自动下载；ARM64 QEMU 非阻塞 | 待环境验证，独立于结构治理推进 |
| G1 / AV-D018/022，旧 P0/P7 | 文档发布状态、测试归属和兼容移除条件漂移 | 触及领域时维护既有行为合同与领域索引；按 COMP-001～008 各自窗口处理；不整体搬迁测试或提前删桥接 | 持续治理 |
| G2 / AV-D020/021 | SHA1 缓存非安全用途标记及依赖残余 | 文件名稳定性合同后处理 SHA1；旧 GPU/setuptools 按兼容和真实依赖重新评估，不忽略告警；默认监听为设计保留 | 持续治理；漏洞状态以当期扫描为准 |

每批依次完成：记录当前候选与哈希 → 建立缺口回归 → 最小实现 → 定向与质量/安全检查 → 有意义的累计实现执行全量与覆盖率 → 更新边界/残余 → 仓库外补丁、日志与归档。涉及标准库至少覆盖 Python 3.10/3.12；全局覆盖率 ≥70%，同时比较同环境基线和变更路径。昂贵 Gate 在候选未变时不重复运行。未达到真实模型/并发/发布条件的项不得勾成完成。

## 证据与更新规则

- 历史逐项复测：2026-09-05 `angevoice-p5-text-preparation-boundary-ownership-characterization/historical-review/RECONCILIATION.md`；READY SHA-256 `e1c4906306d960db25db3a09360cc34b7ddfede383e766d60d3740f56dabfa8e`。历史复杂度是当时实测，当前值以 quality Gate 为准。
- P5 冻结实现：2026-09-06 `angevoice-p5-text-preparation-boundary-narrow-implementation`；READY SHA-256 `62d8dbad38cde4bb42b99dd7045fac0cdc8e63a72f6ac8853e3bddd33e973bf2`。
- 首轮证据：2026-09-07 `angevoice-foundation-wave1`，仓库外各 batch 的 `REPORT.md`、`state.json`、`incremental.patch`、Gate 日志和累计候选；完整路径见施工交付报告。上述证据目录名用于检索，不是仓库文件链接。
- 每条关闭必须同时说明边界、兼容、验证和残余限制；不以测试数量、文件数量或阶段标签代替行为证明。新字段/新框架只有真实消费方和职责需求才接入。
- 历史首轮顺序为配置 → 运行时复用 → Manager/路由，相关窄批次已有下述证据。后续以本文件新版工作清单和现场代码为准，每批先定具体行为与回滚边界，不一次重构整组巨类。

- WS 边界证据：2026-09-08 `angevoice-ws-boundary`；按当期代码修复首包异常处理并分离函数职责，不引入额外状态 owner。错误/取消/临时文件清理和二进制帧顺序由行为测试验收。

- 配置 ENV 执行边界证据：2026-09-08 `angevoice-config-env-boundary`；typed map、TTSConfig facade 与默认值→ENV→runtime→显式参数优先级保持。凭据消费已展开路径，ZipVoice 显式子目录覆盖根目录派生。

- ZipVoice 共用纯逻辑证据：2026-09-08 `angevoice-zipvoice-runtime-common`；两个实际 runtime 消费同一小型模块。模型加载、CUDA 设备/max_duration、provider fallback 与 public WAV 转换边界保持。

- 2026-09-10 现场复核：Kokoro/MOSS 已共用 WAV 编码，切片循环虽相似，音频形状、分块下限和超时恢复策略不同，本批不引入共同运行时。Manager 加载事务证据为 `angevoice-manager-load-boundary`；按当前调用链先分离加载/回滚责任，保留 provider busy、load=False 和失败重试语义。

- 路由组装证据：2026-09-10 `angevoice-route-composition-boundary`；register_service_routes 在 composition root 注入三组领域依赖。旧 register_extra_routes 与 as_service_extras_kwargs 保留兼容，移除条件见 COMP-008。
