# comfyUI_casc

[中文](#中文说明)

**Bring reusable AI character assets into ComfyUI as one portable `.casc` file.**

`comfyUI_casc` is a ComfyUI custom-node package for Character Asset Studio containers. A CASC file can carry a character's identities, reference images, fixed-view reference images, audio, video, private LoRAs, and integrity metadata together—without relying on the original source-file paths.

Upload one container, choose an identity, then route its assets into your ComfyUI workflow.

---

## Highlights

- **One-file character asset library** — keep a virtual person, model, or character's reusable assets together in a `.casc` container.
- **Direct CASC upload** — the `CASC Input` node provides a **Click to upload CASC file** button; uploaded files go to `ComfyUI/input/comfyUI_casc/`.
- **Identity-first workflow** — one container can include multiple identities, such as different outfits, styles, ages, or model variants.
- **Reference-image ready** — output general and detail images as native ComfyUI `IMAGE` batches.
- **11-view reference support** — access portrait, front, rear, sides, top, bottom, and half-body `settingImage` views through dedicated outputs.
- **Private LoRA loading** — apply a LoRA stored in the CASC container to your base `MODEL` and `CLIP` without manually extracting it.
- **Integrity verification** — CASC v3 assets are re-hashed with SHA-256 during decoding; corrupted or modified files stop the workflow instead of silently producing incorrect assets.
- **Encrypted container support** — supports password-protected AES-256-CBC CASC files created by Character Asset Studio.

---

## Installation

Copy this folder into your ComfyUI custom-node directory:

```text
ComfyUI/
└── custom_nodes/
    └── comfyUI_casc/
```

Restart ComfyUI. The nodes appear in the **CASC** category.

> The package includes `native/libzstd.dll` for Zstandard-compressed CASC files on Windows. It expects a normal ComfyUI runtime with its own `torch`, `numpy`, `Pillow`, `aiohttp`, and `comfy` modules.

---

## Quick Start

```text
CASC Input
    ↓ identities
CASC Identity Selector
    ↓ identity
CASC Resources Output
    ├── generalImage → CASC General Images → IMAGE
    ├── settingImage → CASC Setting Images → 11 × IMAGE
    ├── DetailsImage → CASC Detail Images → IMAGE
    └── privateLora + MODEL + CLIP → CASC Private LoRA → MODEL + CLIP
```

### 1. Upload a CASC file

Add **CASC Input** and click **Click to upload CASC file**. Select a `.casc` file from your computer.

- Enter the password only for encrypted containers.
- The node returns the container's complete identity list.

### 2. Inspect identities

Connect the output to **CASC Identity Viewer**. After executing the graph, the node displays a clear list such as:

```text
Identity index / name
0: Base identity
1: Summer outfit
2: Studio portrait
```

### 3. Select an identity and split its resources

Use **CASC Identity Selector** with the desired `identity_index`, then connect it to **CASC Resources Output**.

### 4. Consume only what the workflow needs

For general images, detail images, and audio, use `asset_index`:

| `asset_index` | Behavior |
|---:|---|
| `-1` or any negative value | Return the entire resource list |
| `0` or larger | Return only that zero-based asset |

This makes one node useful both for image-batch workflows and for workflows that need one specific reference.

---

## Nodes

### Input & identity nodes

| Node | Purpose |
|---|---|
| **CASC Input** (`casc_input`) | Upload or resolve a `.casc` file, decrypt it when needed, and output `identities`. |
| **CASC Identity Selector** (`casc_identity_selector`) | Select one identity using its zero-based `identity_index`. |
| **CASC Identity Viewer** (`casc_identityviewer`) | Draw the available identity indices and names directly on the node canvas. |
| **CASC Resources Output** (`casc_resources_output`) | Split an identity into general images, setting images, detail images, reference audio, reference video, and private LoRAs. |

### Image nodes

| Node | Input | Output | Notes |
|---|---|---|---|
| **CASC General Images** (`casc_get_generalImage`) | `generalImage`, `asset_index` | `IMAGE` | Negative index returns the full image batch. |
| **CASC Detail Images** (`casc_get_DetailsImage`) | `DetailsImage`, `asset_index` | `IMAGE` | Negative index returns the full image batch. |
| **CASC Setting Images** (`casc_get_settingImage`) | `settingImage` | 11 × `IMAGE` | Missing views produce a 64×64 black placeholder image. |
| **CASC Image List Viewer** (`casc_imagelistviewer`) | General / setting / detail image lists | — | Displays images in the ComfyUI result UI. |

### `settingImage` output order

`CASC Setting Images` exposes these fixed outputs, matching the Character Asset Studio schema:

```text
Portrait
Front
Left
Right
Rear
Top
Bottom
LeftFronthalf
RightFronthalf
LeftRearHalf
RightRearHalf
```

### Audio, video & LoRA nodes

| Node | Input | Output | Notes |
|---|---|---|---|
| **CASC Reference Audio** (`casc_get_refAudio`) | `refAudio`, `asset_index` | `CASC_AUDIO` | Returns extracted temporary-file paths; negative index returns all audio files. |
| **CASC Reference Video** (`casc_get_refVideo`) | `refVideo` | `CASC_VIDEO` | Returns extracted temporary-file paths. |
| **CASC Private LoRA** (`casc_get_privateLora`) | `MODEL`, `CLIP`, `privateLora`, `lora_index`, `strength_model`, `strength_clip` | `MODEL`, `CLIP` | Extracts the selected LoRA, then applies it through ComfyUI's LoRA loader. |

---

## CASC Compatibility

| Capability | Status |
|---|---|
| CASC versions | v1, v2, v3 |
| Compression | None, Qt Deflate, Zstandard, LZ4 block |
| Historical LZ4 enum files | Supported — earlier Character Asset Studio builds used Qt Deflate under the LZ4 enum, and the reader accepts them |
| AES password encryption | Supported — AES-256-CBC with the Character Asset Studio key derivation scheme |
| SHA-256 resource verification | Supported for CASC v3 |
| Fixed `settingImage` slots | Supported — all 11 slots |

---

## Security & Integrity Notes

- A CASC v3 container stores a SHA-256 digest for every embedded resource.
- The plugin recalculates each digest during load. Any mismatch is treated as an error.
- Encrypted CASC files require the correct password before decompression and resource parsing.
- Temporary extracted audio, video, and LoRA files are stored in ComfyUI's temporary directory under `comfyUI_casc`.

---

## Development Notes

The project is intentionally self-contained:

```text
comfyUI_casc/
├── __init__.py          # ComfyUI package entry point and web extension registration
├── nodes.py             # Node definitions
├── casc_format.py       # CASC v1/v2/v3 reader, AES, SHA-256, compression handling
├── upload.py            # CASC upload route
├── js/
│   └── casc_upload.js   # Upload button and identity-viewer canvas rendering
└── native/
    └── libzstd.dll      # Windows Zstandard decoder dependency
```

## License

Licensed under the [Apache License 2.0](LICENSE).
---

## 中文说明

**把可复用的 AI 人物资产装进一个 `.casc` 文件，直接带入 ComfyUI 工作流。**

`comfyUI_casc` 是一个用于读取 Character Asset Studio `.casc` 容器的 ComfyUI 自定义节点插件。一个 CASC 文件可以集中保存角色身份、通用参考图、细节参考图、标准机位图、音频、视频、私有 LoRA 和完整性校验信息，而无需依赖原始文件路径。

上传一个 CASC 文件，选择一个身份，然后把对应资源连接到 ComfyUI 工作流中即可。

### 核心特点

- **单文件角色资产库**：把虚拟人、模特或角色的可复用资产集中保存到一个 `.casc` 文件。
- **直接上传 CASC**：`CASC Input` 节点提供 **点击上传 CASC 文件** 按钮，上传文件会保存到 `ComfyUI/input/comfyUI_casc/`。
- **以身份为核心**：一个容器可以保存多个身份，例如不同服装、风格、年龄或模型版本。
- **原生图片输出**：通用参考图和细节参考图可直接输出为 ComfyUI `IMAGE` batch。
- **11 个标准机位**：支持肖像、正面、背面、左右侧、顶部、底部与半身机位的独立输出。
- **私有 LoRA 直载**：无需手动解压，可将 CASC 内的 LoRA 应用到基础 `MODEL` 和 `CLIP`。
- **SHA-256 完整性校验**：读取 CASC v3 时会重新计算所有资源校验值，资源损坏或被修改时中止执行。
- **加密容器支持**：支持由 Character Asset Studio 创建的 AES-256-CBC 密码保护容器。

### 安装

将整个插件文件夹复制到：

```text
ComfyUI/
└── custom_nodes/
    └── comfyUI_casc/
```

重启 ComfyUI 后，节点会出现在 **CASC** 分类中。

> 插件内置 `native/libzstd.dll`，用于 Windows 环境下读取 Zstandard 压缩的 CASC 文件。运行时需要完整 ComfyUI 环境提供 `torch`、`numpy`、`Pillow`、`aiohttp` 和 `comfy` 模块。

### 快速开始

```text
CASC Input
    ↓ identities
CASC Identity Selector
    ↓ identity
CASC Resources Output
    ├── generalImage → CASC General Images → IMAGE
    ├── settingImage → CASC Setting Images → 11 × IMAGE
    ├── DetailsImage → CASC Detail Images → IMAGE
    └── privateLora + MODEL + CLIP → CASC Private LoRA → MODEL + CLIP
```

1. 添加 **CASC Input**，点击 **点击上传 CASC 文件**，选择本地 `.casc` 文件。
2. 如果容器加密，在 `password` 中填写正确密码。
3. 将 `identities` 接入 **CASC Identity Viewer**，节点执行后会直接显示身份索引与身份名称。
4. 用 **CASC Identity Selector** 的 `identity_index` 选择需要使用的身份。
5. 把身份接入 **CASC Resources Output**，然后按资源类型连接后续节点。

### `asset_index` 规则

通用图片、细节图片和音频节点都有 `asset_index` 输入：

| `asset_index` | 行为 |
|---:|---|
| `-1` 或任何负数 | 返回整个资源集合 |
| `0` 或更大 | 仅返回对应零基索引的资源 |

因此同一个节点既可服务于整组图片 batch 工作流，也可用于只需要某张指定参考图的工作流。

### 节点说明

#### 输入与身份节点

| 节点 | 功能 |
|---|---|
| **CASC Input** (`casc_input`) | 上传或读取 `.casc` 文件；需要时解密；输出 `identities` 身份列表。 |
| **CASC Identity Selector** (`casc_identity_selector`) | 通过零基 `identity_index` 选择一个身份。 |
| **CASC Identity Viewer** (`casc_identityviewer`) | 在节点画布上显示可用身份的索引和名称。 |
| **CASC Resources Output** (`casc_resources_output`) | 将身份拆分为通用图片、标准机位图、细节图片、参考音频、参考视频和私有 LoRA。 |

#### 图片节点

| 节点 | 输入 | 输出 | 说明 |
|---|---|---|---|
| **CASC General Images** (`casc_get_generalImage`) | `generalImage`、`asset_index` | `IMAGE` | 负数索引返回整个图片 batch。 |
| **CASC Detail Images** (`casc_get_DetailsImage`) | `DetailsImage`、`asset_index` | `IMAGE` | 负数索引返回整个图片 batch。 |
| **CASC Setting Images** (`casc_get_settingImage`) | `settingImage` | 11 × `IMAGE` | 缺失机位输出 64×64 黑色占位图。 |
| **CASC Image List Viewer** (`casc_imagelistviewer`) | 通用 / 标准机位 / 细节图片列表 | — | 在 ComfyUI 结果界面中显示图片集。 |

#### 标准机位图输出顺序

`CASC Setting Images` 的固定输出与 Character Asset Studio 的 `settingImage` 结构一致：

```text
Portrait
Front
Left
Right
Rear
Top
Bottom
LeftFronthalf
RightFronthalf
LeftRearHalf
RightRearHalf
```

#### 音频、视频与 LoRA 节点

| 节点 | 输入 | 输出 | 说明 |
|---|---|---|---|
| **CASC Reference Audio** (`casc_get_refAudio`) | `refAudio`、`asset_index` | `CASC_AUDIO` | 返回解出的临时音频文件路径；负数索引返回全部音频。 |
| **CASC Reference Video** (`casc_get_refVideo`) | `refVideo` | `CASC_VIDEO` | 返回解出的临时视频文件路径。 |
| **CASC Private LoRA** (`casc_get_privateLora`) | `MODEL`、`CLIP`、`privateLora`、`lora_index`、`strength_model`、`strength_clip` | `MODEL`、`CLIP` | 提取指定 LoRA 后调用 ComfyUI LoRA loader，输出已应用 LoRA 的模型与 CLIP。 |

### CASC 格式兼容性

| 能力 | 支持情况 |
|---|---|
| CASC 版本 | v1、v2、v3 |
| 压缩方式 | 无压缩、Qt Deflate、Zstandard、LZ4 block |
| 历史 LZ4 枚举文件 | 支持：早期 Character Asset Studio 曾以 LZ4 枚举写入 Qt Deflate，插件会兼容读取 |
| AES 密码加密 | 支持：使用 Character Asset Studio 对应的 AES-256-CBC 密钥派生方案 |
| SHA-256 资源校验 | 支持 CASC v3 |
| 固定 `settingImage` 机位 | 支持全部 11 个机位 |

### 安全与完整性说明

- CASC v3 会为每个嵌入资源保存 SHA-256 摘要。
- 插件加载时会重新计算 SHA-256，校验不匹配会直接报错。
- 加密 CASC 文件必须输入正确密码，才能解密、解压和解析资源。
- 解出的音频、视频和 LoRA 临时文件会存放在 ComfyUI 临时目录中的 `comfyUI_casc` 子目录。

### 开发目录结构

```text
comfyUI_casc/
├── __init__.py          # ComfyUI 插件入口与前端扩展注册
├── nodes.py             # 节点定义
├── casc_format.py       # CASC v1/v2/v3 解析、AES、SHA-256、压缩处理
├── upload.py            # CASC 上传路由
├── js/
│   └── casc_upload.js   # 上传按钮与身份预览画布渲染
└── native/
    └── libzstd.dll      # Windows Zstandard 解码依赖
```

### 许可证

本项目使用 [Apache License 2.0](LICENSE) 开源。