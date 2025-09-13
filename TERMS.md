# 术语表 / Terminology Glossary

统一术语有助于提高翻译一致性与可读性。请在提交 PR 前检查新增术语是否需要补充或与现有条目冲突。

| English | 中文候选 | 说明 / Notes | 状态 |
|---------|----------|--------------|------|
| contract | 合约 | 以太坊智能合约 | 固定 |
| module | 模块 | Vyper 代码复用单元 | 固定 |
| interface | 接口 | 外部可调用函数集合 | 固定 |
| event | 事件 | EVM 日志抽象 | 固定 |
| storage slot | 存储槽 | 256-bit 槽位 | 固定 |
| storage layout | 存储布局 | 结构及变量在槽中的排列 | 固定 |
| reentrancy | 可重入 / 重入 | 根据上下文选择“重入” | 固定 |
| nonreentrant | 不可重入 | 装饰器或全局锁语义 | 固定 |
| immutable | 不可变(变量) | 部署期初始化后只读 | 固定 |
| constant | 常量 | 编译期已知且内联 | 固定 |
| external function | 外部函数 | 通过交易或合约调用 | 固定 |
| internal function | 内部函数 | 仅合约内或模块内部调用 | 固定 |
| visibility | 可见性 | external/internal/deploy | 固定 |
| mutability | 可变性 | pure/view/payable/nonpayable | 固定 |
| payable | 可支付 | 可接收并访问 msg.value | 固定 |
| view | 只读 | 读取状态但不修改 | 固定 |
| pure | 纯函数 | 不读取状态与环境变量 | 固定 |
| raw return | 原始返回 | 不经 ABI 编码的返回值 | 固定 |
| selector table | 选择器表 | 函数选择器映射表 | 待观察 |
| ABI | ABI | 保持原文大写 | 固定 |
| gas | gas | 保留原文 | 固定 |
| opcode | 操作码 | EVM 指令 | 固定 |
| optimizer / optimization | 优化器 / 优化 | 语境决定 | 固定 |
| Venom (pipeline) | Venom 管线 | Vyper 新后端名称 | 固定 |
| feature flag | 功能开关 | pragma 或语言特性开关 | 固定 |
| fallback / default function | 默认函数 | __default__ 函数 | 固定 |
| constructor | 构造函数 | __init__ 部署期函数 | 固定 |
| bound (range) | 上界（bound） | 括号中保留英文辅助 | 固定 |
| pragma | 编译指示 | #pragma 指令 | 固定 |
| layout (storage layout) | 布局 | 结合上下文可省略“存储” | 固定 |

## 维护规则

1. 新增术语：按字母序（English）插入，保持表格对齐。
2. 若中文存在多种社区用法，选主流 + 备注可选别名。
3. 禁止使用机翻难懂表达；优先“简洁 + 业内共识”。
4. 修改已“固定”条目需在 PR 描述中注明理由。
5. `状态` 列：固定 / 待观察（可能随社区反馈调整）。

## 贡献流程

1. 运行 `sphinx-intl` 更新 po 后，翻译时遇到新术语先查本表。
2. 不在表中的：本地增加候选 -> 提交 PR -> 评审确认。
3. Reviewer 合并前可提出统一建议（如命名冲突）。

## 其它建议

- 保持英文专有名大小写（EVM, ABI, ERC20）。
- 代码、保留字、装饰器统一使用反引号包裹，例如 `@external`、`Bytes[32]`。
- 句内第一次出现英文+中文括注（如 “非重入（nonreentrancy）”），后续可仅中文。

欢迎补充！
