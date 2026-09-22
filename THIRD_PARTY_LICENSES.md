# 第三方许可证清单

本文件由 `scripts/gen_third_party_licenses.py` 从**安装包真实内容**自动生成，生成时间 2026-09-22 12:18。判定优先依据包内随附的许可证原文，其次依据包元数据；两者都缺的少量组件在 `licenses/SUMMARY.json` 的 `overrides` 段登记依据。

- 随包第三方组件：**362 个**（python-embed 118 + 前端生产依赖 244）
- 有分发义务的 copyleft 组件：**12 个**

## 分发义务说明

- **LGPL-3.0（PySide6 / PySide6_Essentials / PySide6_Addons / shiboken6）**：本项目以**动态链接**方式使用，未修改其源码；随分发提供许可证原文（见 `licenses/`），用户可自行替换为兼容版本。
- **GPL-3.0（espeakng-loader 内嵌的 espeak-ng.dll 与 espeak-ng-data）**：espeak-ng 本体为 GPL-3.0。本项目未修改其源码，随包以动态链接方式调用；许可证原文见 `licenses/`，源码获取：https://github.com/espeak-ng/espeak-ng 。
- **MPL-2.0（certifi / easy-live2d / tqdm）**：随分发提供许可证原文（见 `licenses/`）。
- **AGPL-3.0（SearXNG，独立组件、非 pip 依赖）**：本项目未修改 SearXNG 源码，随安装包分发其二进制；源码获取：https://github.com/searxng/searxng 。
- 其余组件以其自身许可证发布，原文见各自官方仓库。

## 子组件许可证提示

以下组件自身许可证不是 copyleft，但随包附带的许可证原文含 copyleft 文件（通常为内嵌子组件），分发时需一并遵守：

| 组件 | 自身许可证 | 随包 copyleft 文件 | 检出 |
|---|---|---|---|
| numpy | BSD License | numpy-2.3.5.dist-info/LICENSE.txt | GPL-3.0 |
| opencv-contrib-python | Apache Software License | opencv_contrib_python-4.10.0.84.dist-info/LICENSE-3RD-PARTY.txt | LGPL-2.1, LGPL-3.0 |
| pillow | MIT-CMU | pillow-12.3.0.dist-info/licenses/LICENSE | GPL-3.0, GPL-2.0 |
| pywin32 | Python Software Foundation License | adodbapi/license.txt | LGPL-2.1 |
| pywin32 | Python Software Foundation License | pywin32-312.dist-info/licenses/adodbapi/license.txt | LGPL-2.1 |

## copyleft 组件明细

| 组件 | 版本 | 许可证 | 判定依据 | 来源 |
|---|---|---|---|---|
| certifi **(copyleft)** | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | METADATA | [链接](https://github.com/certifi/python-certifi) |
| easy-live2d **(copyleft)** | 0.4.4 | MPL-2.0 | package.json | [链接](https://panzer-jack.github.io/easy-live2d/) |
| espeakng-loader **(copyleft)** | 0.2.4 | GPL-3.0（内嵌 espeak-ng 运行时与语音数据） | 人工登记（OVERRIDES） | [链接](https://github.com/thewh1teagle/espeakng-loader) |
| numpy **(copyleft)** | 2.3.5 | BSD License | METADATA | [链接](https://numpy.org) |
| opencv-contrib-python **(copyleft)** | 4.10.0.84 | Apache Software License | METADATA | [链接](https://github.com/opencv/opencv-python) |
| pillow **(copyleft)** | 12.3.0 | MIT-CMU | METADATA | [链接](https://python-pillow.github.io) |
| PySide6 **(copyleft)** | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | METADATA | [链接](https://pyside.org) |
| PySide6_Addons **(copyleft)** | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | METADATA | [链接](https://pyside.org) |
| PySide6_Essentials **(copyleft)** | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | METADATA | [链接](https://pyside.org) |
| pywin32 **(copyleft)** | 312 | Python Software Foundation License | METADATA | [链接](https://github.com/mhammond/pywin32) |
| shiboken6 **(copyleft)** | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | METADATA | [链接](https://pyside.org) |
| tqdm **(copyleft)** | 4.70.0 | MPL-2.0 AND MIT | METADATA | [链接](https://tqdm.github.io) |

## python-embed 全部组件

| 组件 | 版本 | 许可证 | 判定依据 | 来源 |
|---|---|---|---|---|
| aiohappyeyeballs | 2.7.1 | Python Software Foundation License | METADATA | [链接](https://github.com/aio-libs/aiohappyeyeballs) |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT | METADATA | [链接](https://github.com/aio-libs/aiohttp) |
| aiosignal | 1.4.0 | Apache Software License | METADATA | [链接](https://github.com/aio-libs/aiosignal) |
| annotated-doc | 0.0.5 | MIT | METADATA | [链接](https://github.com/fastapi/annotated-doc) |
| annotated-types | 0.8.0 | MIT | METADATA | [链接](https://github.com/annotated-types/annotated-types) |
| anyio | 4.14.2 | MIT | METADATA | [链接](https://github.com/agronholm/anyio) |
| attrs | 26.1.0 | MIT | METADATA | - |
| babel | 2.18.0 | BSD License | METADATA | [链接](https://github.com/python-babel/babel) |
| beautifulsoup4 | 4.15.0 | MIT License | METADATA | [链接](https://www.crummy.com/software/BeautifulSoup/bs4/) |
| certifi **(copyleft)** | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | METADATA | [链接](https://github.com/certifi/python-certifi) |
| cffi | 2.1.0 | MIT-0 | METADATA | [链接](https://github.com/python-cffi/cffi) |
| charset-normalizer | 3.4.9 | MIT | METADATA | - |
| click | 8.4.2 | BSD-3-Clause | METADATA | [链接](https://github.com/pallets/click/) |
| colorama | 0.4.6 | BSD License | METADATA | [链接](https://github.com/tartley/colorama) |
| cryptography | 50.0.0 | Apache-2.0 OR BSD-3-Clause | METADATA | [链接](https://github.com/pyca/cryptography) |
| csvw | 4.1.0 | Apache Software License | METADATA | [链接](https://github.com/cldf/csvw) |
| dashscope | 1.26.5 | Apache Software License | METADATA | [链接](https://dashscope.aliyun.com/) |
| dataclasses-json | 0.6.7 | MIT License | METADATA | [链接](https://github.com/lidatong/dataclasses-json) |
| Deprecated | 1.3.1 | MIT License | METADATA | [链接](https://github.com/laurent-laporte-pro/deprecated) |
| dlinfo | 2.0.0 | MIT | METADATA | [链接](https://github.com/fphammerle/python-dlinfo) |
| edge-tts | 7.2.8 | GNU Lesser General Public License v3 (LGPLv3) | METADATA | [链接](https://github.com/rany2/edge-tts) |
| espeakng-loader **(copyleft)** | 0.2.4 | GPL-3.0（内嵌 espeak-ng 运行时与语音数据） | 人工登记（OVERRIDES） | [链接](https://github.com/thewh1teagle/espeakng-loader) |
| flatbuffers | 25.12.19 | Apache Software License | METADATA | [链接](https://github.com/google/flatbuffers) |
| frozenlist | 1.8.0 | Apache-2.0 | METADATA | [链接](https://github.com/aio-libs/frozenlist) |
| h11 | 0.16.0 | MIT License | METADATA | [链接](https://github.com/python-hyper/h11) |
| httpcore | 1.0.9 | BSD-3-Clause | METADATA | [链接](https://www.encode.io/httpcore/) |
| httpcore2 | 2.13.0 | BSD-3-Clause | METADATA | [链接](https://github.com/pydantic/httpx2) |
| httpx | 0.28.1 | BSD License | METADATA | [链接](https://github.com/encode/httpx) |
| httpx-sse | 0.4.3 | MIT | METADATA | [链接](https://github.com/florimondmanca/httpx-sse) |
| httpx2 | 2.13.0 | BSD-3-Clause | METADATA | [链接](https://github.com/pydantic/httpx2) |
| idna | 3.18 | BSD-3-Clause | METADATA | [链接](https://github.com/kjd/idna) |
| isodate | 0.7.2 | BSD License | METADATA | [链接](https://github.com/gweis/isodate/) |
| Jinja2 | 3.1.6 | BSD License | METADATA | [链接](https://github.com/pallets/jinja/) |
| jiter | 0.17.0 | MIT | METADATA | - |
| joblib | 1.5.3 | BSD-3-Clause | METADATA | [链接](https://joblib.readthedocs.io) |
| jsonschema | 4.26.0 | MIT | METADATA | [链接](https://github.com/python-jsonschema/jsonschema) |
| jsonschema-specifications | 2025.9.1 | MIT | METADATA | [链接](https://github.com/python-jsonschema/jsonschema-specifications) |
| kokoro-onnx | 0.5.0 | MIT | 包内许可证原文 | [链接](https://github.com/thewh1teagle/kokoro-onnx) |
| language-tags | 1.3.1 | MIT | METADATA | [链接](https://github.com/OnroerendErfgoed/language-tags) |
| live2d-py | 0.7.0.4 | MIT | METADATA | [链接](https://github.com/Arkueid/live2d-py) |
| lxml | 6.1.3 | BSD-3-Clause | METADATA | [链接](https://github.com/lxml/lxml) |
| markdown-it-py | 4.2.0 | MIT License | METADATA | [链接](https://github.com/executablebooks/markdown-it-py) |
| MarkupSafe | 3.0.3 | BSD-3-Clause | METADATA | [链接](https://github.com/pallets/markupsafe/) |
| marshmallow | 3.26.2 | MIT License | METADATA | [链接](https://github.com/marshmallow-code/marshmallow) |
| mcp | 2.2.0 | MIT License | METADATA | [链接](https://modelcontextprotocol.io) |
| mcp-types | 2.2.0 | MIT License | METADATA | [链接](https://modelcontextprotocol.io) |
| mdurl | 0.1.2 | MIT License | METADATA | [链接](https://github.com/executablebooks/mdurl) |
| multidict | 6.7.1 | Apache License 2.0 | METADATA | [链接](https://github.com/aio-libs/multidict) |
| mypy_extensions | 1.1.0 | MIT | METADATA | [链接](https://github.com/python/mypy_extensions) |
| numpy **(copyleft)** | 2.3.5 | BSD License | METADATA | [链接](https://numpy.org) |
| onnxruntime | 1.28.0 | MIT License | METADATA | [链接](https://onnxruntime.ai) |
| openai | 3.16.2 | Apache-2.0 | METADATA | [链接](https://github.com/openai/openai-python) |
| opencv-contrib-python **(copyleft)** | 4.10.0.84 | Apache Software License | METADATA | [链接](https://github.com/opencv/opencv-python) |
| opentelemetry-api | 1.44.0 | Apache-2.0 | METADATA | [链接](https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api) |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | METADATA | [链接](https://github.com/pypa/packaging) |
| pdfminer.six | 20260107 | MIT | METADATA | [链接](https://github.com/pdfminer/pdfminer.six) |
| phonemizer-fork | 3.3.2 | GNU General Public License v3 or later (GPLv3+) | METADATA | [链接](https://github.com/bootphon/phonemizer) |
| pillow **(copyleft)** | 12.3.0 | MIT-CMU | METADATA | [链接](https://python-pillow.github.io) |
| pip | 26.0 | MIT | METADATA | [链接](https://pip.pypa.io/) |
| propcache | 0.5.2 | Apache Software License | METADATA | [链接](https://github.com/aio-libs/propcache) |
| protobuf | 7.35.1 | 3-Clause BSD License | METADATA | [链接](https://developers.google.com/protocol-buffers/) |
| psutil | 7.2.2 | BSD-3-Clause | METADATA | [链接](https://github.com/giampaolo/psutil) |
| pycparser | 3.0 | BSD-3-Clause | METADATA | [链接](https://github.com/eliben/pycparser) |
| pydantic | 2.13.4 | MIT | METADATA | [链接](https://github.com/pydantic/pydantic) |
| pydantic_core | 2.46.4 | MIT | METADATA | [链接](https://github.com/pydantic) |
| pygltflib | 1.16.5 | MIT License | METADATA | [链接](https://gitlab.com/dodgyville/pygltflib) |
| Pygments | 2.20.0 | BSD-2-Clause | METADATA | [链接](https://pygments.org) |
| PyJWT | 2.14.0 | MIT | METADATA | [链接](https://github.com/jpadilla/pyjwt) |
| pynput | 1.8.2 | GNU Lesser General Public License v3 (LGPLv3) | METADATA | [链接](https://github.com/moses-palmer/pynput) |
| PyOpenGL | 3.1.10 | BSD License | METADATA | [链接](https://mcfletch.github.io/pyopengl/) |
| PyOpenGL-accelerate | 3.1.10 | BSD License | METADATA | [链接](https://mcfletch.github.io/pyopengl/) |
| pyparsing | 3.3.2 | MIT | METADATA | [链接](https://github.com/pyparsing/pyparsing/) |
| pypdf | 6.19.0 | BSD-3-Clause | METADATA | [链接](https://github.com/py-pdf/pypdf) |
| pypdfium2 | 5.12.1 | BSD-3-Clause, Apache-2.0, dependency licenses | METADATA | [链接](https://github.com/pypdfium2-team/pypdfium2) |
| PySide6 **(copyleft)** | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | METADATA | [链接](https://pyside.org) |
| PySide6_Addons **(copyleft)** | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | METADATA | [链接](https://pyside.org) |
| PySide6_Essentials **(copyleft)** | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | METADATA | [链接](https://pyside.org) |
| python-dateutil | 2.9.0.post0 | BSD License | METADATA | [链接](https://github.com/dateutil/dateutil) |
| python-docx | 1.2.0 | MIT License | METADATA | [链接](https://github.com/python-openxml/python-docx) |
| python-multipart | 0.0.32 | Apache-2.0 | METADATA | [链接](https://github.com/Kludex/python-multipart) |
| pywin32 **(copyleft)** | 312 | Python Software Foundation License | METADATA | [链接](https://github.com/mhammond/pywin32) |
| PyYAML | 6.0.2 | MIT License | METADATA | [链接](https://github.com/yaml/pyyaml) |
| rdflib | 7.6.0 | BSD License | METADATA | [链接](https://github.com/RDFLib/rdflib) |
| referencing | 0.37.0 | MIT | METADATA | [链接](https://github.com/python-jsonschema/referencing) |
| regex | 2026.7.19 | Apache-2.0 AND CNRI-Python | METADATA | [链接](https://github.com/mrabarnett/mrab-regex) |
| requests | 2.34.2 | Apache Software License | METADATA | [链接](https://github.com/psf/requests) |
| rfc3986 | 1.5.0 | Apache Software License | METADATA | [链接](http://rfc3986.readthedocs.io) |
| rich | 15.0.0 | MIT License | METADATA | [链接](https://github.com/Textualize/rich) |
| rpds-py | 2026.6.3 | MIT | METADATA | [链接](https://github.com/crate-py/rpds) |
| segments | 2.4.0 | Apache Software License | METADATA | [链接](https://github.com/cldf/segments) |
| shellingham | 1.5.4 | ISC License (ISCL) | METADATA | [链接](https://github.com/sarugaku/shellingham) |
| shiboken6 **(copyleft)** | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | METADATA | [链接](https://pyside.org) |
| six | 1.17.0 | MIT License | METADATA | [链接](https://github.com/benjaminp/six) |
| sniffio | 1.3.1 | MIT License | METADATA | [链接](https://github.com/python-trio/sniffio) |
| sounddevice | 0.5.5 | MIT | METADATA | [链接](https://github.com/spatialaudio/python-sounddevice/) |
| soundfile | 0.14.0 | BSD License | METADATA | [链接](https://github.com/bastibe/python-soundfile) |
| soupsieve | 2.9.2 | MIT | METADATA | [链接](https://github.com/facelessuser/soupsieve) |
| srt | 3.5.3 | MIT License | METADATA | [链接](https://github.com/cdown/srt) |
| sse-starlette | 3.4.11 | BSD-3-Clause | METADATA | [链接](https://github.com/sysid/sse-starlette) |
| starlette | 1.6.0 | BSD-3-Clause | METADATA | [链接](https://github.com/Kludex/starlette) |
| tabulate | 0.10.0 | MIT | METADATA | [链接](https://github.com/astanin/python-tabulate) |
| termcolor | 3.3.0 | MIT | METADATA | [链接](https://github.com/termcolor/termcolor) |
| tiktoken | 0.14.0 | MIT License | METADATA | [链接](https://github.com/openai/tiktoken) |
| tqdm **(copyleft)** | 4.70.0 | MPL-2.0 AND MIT | METADATA | [链接](https://tqdm.github.io) |
| truststore | 0.10.4 | MIT | METADATA | [链接](https://github.com/sethmlarson/truststore) |
| typer | 0.27.0 | MIT | METADATA | [链接](https://github.com/fastapi/typer) |
| typing-inspect | 0.9.0 | MIT License | METADATA | [链接](https://github.com/ilevkivskyi/typing_inspect) |
| typing-inspection | 0.4.2 | MIT | METADATA | [链接](https://github.com/pydantic/typing-inspection) |
| typing_extensions | 4.16.0 | PSF-2.0 | METADATA | [链接](https://github.com/python/typing_extensions) |
| uritemplate | 4.2.0 | BSD 3-Clause OR Apache-2.0 | METADATA | [链接](https://github.com/python-hyper/uritemplate) |
| urllib3 | 2.7.0 | MIT | METADATA | - |
| uvicorn | 0.53.0 | BSD-3-Clause | METADATA | [链接](https://uvicorn.dev/) |
| vosk | 0.3.45 | Apache Software License | METADATA | [链接](https://github.com/alphacep/vosk-api) |
| webrtcvad | 2.0.10 | MIT License | METADATA | [链接](https://github.com/wiseman/py-webrtcvad) |
| websocket-client | 1.9.0 | Apache Software License | METADATA | [链接](https://github.com/websocket-client/websocket-client/) |
| websockets | 17.0.1 | BSD-3-Clause | METADATA | [链接](https://github.com/python-websockets/websockets) |
| wrapt | 2.4.1 | BSD-2-Clause | METADATA | [链接](https://github.com/GrahamDumpleton/wrapt) |
| yarl | 1.24.5 | Apache-2.0 | METADATA | [链接](https://github.com/aio-libs/yarl) |

## 前端生产依赖全部组件

| 组件 | 版本 | 许可证 | 判定依据 | 来源 |
|---|---|---|---|---|
| @azure/msal-common | 14.16.1 | MIT | package.json | - |
| @azure/msal-node | 2.16.3 | MIT | package.json | - |
| @cacheable/memory | 2.2.0 | MIT | package.json | - |
| @cacheable/utils | 2.5.0 | MIT | package.json | - |
| @dprint/formatter | 0.5.1 | MIT | package.json | [链接](https://github.com/dprint/js-formatter#readme) |
| @dprint/markdown | 0.21.1 | MIT | package.json | [链接](https://github.com/dprint/dprint-plugin-markdown#readme) |
| @dprint/toml | 0.7.0 | MIT | package.json | [链接](https://github.com/dprint/dprint-plugin-toml#readme) |
| @eslint-community/eslint-utils | 4.10.1 | MIT | package.json | [链接](https://github.com/eslint-community/eslint-utils#readme) |
| @eslint-community/regexpp | 4.12.2 | MIT | package.json | [链接](https://github.com/eslint-community/regexpp#readme) |
| @eslint/config-array | 0.23.5 | Apache-2.0 | package.json | [链接](https://github.com/eslint/rewrite/tree/main/packages/config-array#readme) |
| @eslint/config-helpers | 0.7.0 | Apache-2.0 | package.json | [链接](https://github.com/eslint/rewrite/tree/main/packages/config-helpers#readme) |
| @eslint/core | 1.2.1 | Apache-2.0 | package.json | [链接](https://github.com/eslint/rewrite/tree/main/packages/core#readme) |
| @eslint/object-schema | 3.0.5 | Apache-2.0 | package.json | [链接](https://github.com/eslint/rewrite/tree/main/packages/object-schema#readme) |
| @eslint/plugin-kit | 0.7.3 | Apache-2.0 | package.json | [链接](https://github.com/eslint/rewrite/tree/main/packages/plugin-kit#readme) |
| @humanfs/core | 0.19.2 | Apache-2.0 | package.json | [链接](https://github.com/humanwhocodes/humanfs#readme) |
| @humanfs/node | 0.16.8 | Apache-2.0 | package.json | [链接](https://github.com/humanwhocodes/humanfs#readme) |
| @humanfs/types | 0.15.0 | Apache-2.0 | package.json | [链接](https://github.com/humanwhocodes/humanfs#readme) |
| @humanwhocodes/module-importer | 1.0.1 | Apache-2.0 | package.json | - |
| @humanwhocodes/retry | 0.4.3 | Apache-2.0 | package.json | - |
| @keyv/bigmap | 1.3.1 | MIT | package.json | [链接](https://github.com/jaredwray/keyv) |
| @keyv/serialize | 1.1.1 | MIT | package.json | [链接](https://github.com/jaredwray/keyv) |
| @oxfmt/binding-android-arm-eabi | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-android-arm64 | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-darwin-arm64 | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-darwin-x64 | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-freebsd-x64 | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-arm-gnueabihf | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-arm-musleabihf | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-arm64-gnu | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-arm64-musl | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-ppc64-gnu | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-riscv64-gnu | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-riscv64-musl | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-s390x-gnu | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-x64-gnu | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-linux-x64-musl | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-openharmony-arm64 | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-win32-arm64-msvc | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-win32-ia32-msvc | 0.35.0 | MIT | package.json | - |
| @oxfmt/binding-win32-x64-msvc | 0.35.0 | MIT | package.json | [链接](https://oxc.rs/docs/guide/usage/formatter) |
| @pixi/colord | 2.9.6 | MIT | package.json | - |
| @pixi/sound | 6.0.1 | MIT | package.json | [链接](https://github.com/pixijs/sound#readme) |
| @pkgr/core | 0.3.6 | MIT | package.json | [链接](https://github.com/un-ts/pkgr/blob/master/packages/core) |
| @radix-ui/react-compose-refs | 1.1.5 | MIT | package.json | [链接](https://radix-ui.com/primitives) |
| @radix-ui/react-slot | 1.3.3 | MIT | package.json | [链接](https://radix-ui.com/primitives) |
| @tauri-apps/api | 2.11.1 | Apache-2.0 OR MIT | package.json | [链接](https://github.com/tauri-apps/tauri#readme) |
| @types/d3-color | 3.1.3 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/d3-color) |
| @types/d3-drag | 3.0.7 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/d3-drag) |
| @types/d3-interpolate | 3.0.4 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/d3-interpolate) |
| @types/d3-selection | 3.0.11 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/d3-selection) |
| @types/d3-transition | 3.0.9 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/d3-transition) |
| @types/d3-zoom | 3.0.8 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/d3-zoom) |
| @types/earcut | 3.0.0 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/earcut) |
| @types/esrecurse | 4.3.1 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/esrecurse) |
| @types/estree | 1.0.9 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/estree) |
| @types/json-schema | 7.0.15 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/json-schema) |
| @types/node | 22.20.2 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/node) |
| @types/node-rsa | 1.1.4 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/node-rsa) |
| @types/react | 19.3.0 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/react) |
| @types/react-dom | 19.3.0 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/react-dom) |
| @types/readable-stream | 4.0.24 | MIT | package.json | [链接](https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/readable-stream) |
| @webgpu/types | 0.1.72 | BSD-3-Clause | package.json | [链接](https://github.com/gpuweb/types) |
| @xboxreplay/xboxlive-auth | 5.1.0 | Apache-2.0 | package.json | [链接](https://github.com/XboxReplay/xboxlive-auth#readme) |
| @xmldom/xmldom | 0.8.15 | MIT | package.json | [链接](https://github.com/xmldom/xmldom) |
| @xyflow/react | 12.11.6 | MIT | package.json | [链接](https://reactflow.dev) |
| @xyflow/system | 0.0.82 | MIT | package.json | - |
| abort-controller | 3.0.0 | MIT | package.json | [链接](https://github.com/mysticatea/abort-controller#readme) |
| acorn | 8.18.0 | MIT | package.json | [链接](https://github.com/acornjs/acorn) |
| acorn-jsx | 5.3.2 | MIT | package.json | [链接](https://github.com/acornjs/acorn-jsx) |
| aes-js | 3.1.2 | MIT | package.json | - |
| ajv | 6.15.0 | MIT | package.json | [链接](https://github.com/ajv-validator/ajv) |
| asn1 | 0.2.3 | MIT | package.json | - |
| balanced-match | 4.0.4 | MIT | package.json | - |
| base64-js | 1.5.1 | MIT | package.json | [链接](https://github.com/beatgammit/base64-js) |
| brace-expansion | 5.0.9 | MIT | package.json | - |
| buffer | 6.0.3 | MIT | package.json | [链接](https://github.com/feross/buffer) |
| buffer-equal | 1.0.1 | MIT | package.json | - |
| buffer-equal-constant-time | 1.0.1 | BSD-3-Clause | package.json | - |
| cacheable | 2.5.0 | MIT | package.json | - |
| class-variance-authority | 0.7.1 | Apache-2.0 | package.json | [链接](https://github.com/joe-bell/cva#readme) |
| classcat | 5.0.5 | MIT | package.json | - |
| clsx | 2.1.1 | MIT | package.json | - |
| commander | 2.20.3 | MIT | package.json | - |
| cross-spawn | 7.0.6 | MIT | package.json | [链接](https://github.com/moxystudio/node-cross-spawn) |
| csstype | 3.2.3 | MIT | package.json | - |
| d3-color | 3.1.0 | ISC | package.json | [链接](https://d3js.org/d3-color/) |
| d3-dispatch | 3.0.1 | ISC | package.json | [链接](https://d3js.org/d3-dispatch/) |
| d3-drag | 3.0.0 | ISC | package.json | [链接](https://d3js.org/d3-drag/) |
| d3-ease | 3.0.1 | BSD-3-Clause | package.json | [链接](https://d3js.org/d3-ease/) |
| d3-interpolate | 3.0.1 | ISC | package.json | [链接](https://d3js.org/d3-interpolate/) |
| d3-selection | 3.0.0 | ISC | package.json | [链接](https://d3js.org/d3-selection/) |
| d3-timer | 3.0.1 | ISC | package.json | [链接](https://d3js.org/d3-timer/) |
| d3-transition | 3.0.1 | ISC | package.json | [链接](https://d3js.org/d3-transition/) |
| d3-zoom | 3.0.0 | ISC | package.json | [链接](https://d3js.org/d3-zoom/) |
| debug | 4.4.3 | MIT | package.json | - |
| deep-is | 0.1.4 | MIT | package.json | - |
| discontinuous-range | 1.0.0 | MIT | package.json | [链接](https://github.com/dtudury/discontinuous-range) |
| earcut | 3.2.3 | ISC | package.json | - |
| easy-live2d **(copyleft)** | 0.4.4 | MPL-2.0 | package.json | [链接](https://panzer-jack.github.io/easy-live2d/) |
| ecdsa-sig-formatter | 1.0.11 | Apache-2.0 | package.json | [链接](https://github.com/Brightspace/node-ecdsa-sig-formatter#readme) |
| endian-toggle | 0.0.0 | MIT | package.json | [链接](https://github.com/substack/endian-toggle) |
| escape-string-regexp | 4.0.0 | MIT | package.json | - |
| eslint | 10.10.0 | MIT | package.json | [链接](https://eslint.org) |
| eslint-formatting-reporter | 0.0.0 | MIT | package.json | [链接](https://github.com/antfu/eslint-formatting-reporter#readme) |
| eslint-parser-plain | 0.1.1 | MIT | package.json | [链接](https://github.com/so1ve/eslint-parser-plain#readme) |
| eslint-plugin-format | 2.0.1 | MIT | package.json | [链接](https://github.com/antfu/eslint-plugin-format#readme) |
| eslint-scope | 9.1.2 | BSD-2-Clause | package.json | [链接](https://github.com/eslint/js/blob/main/packages/eslint-scope/README.md) |
| eslint-visitor-keys | 3.4.3 | Apache-2.0 | package.json | [链接](https://github.com/eslint/eslint-visitor-keys#readme) |
| eslint-visitor-keys | 5.0.1 | Apache-2.0 | package.json | [链接](https://github.com/eslint/js/blob/main/packages/eslint-visitor-keys/README.md) |
| espree | 11.2.0 | BSD-2-Clause | package.json | [链接](https://github.com/eslint/js/blob/main/packages/espree/README.md) |
| esquery | 1.7.0 | BSD-3-Clause | package.json | [链接](https://github.com/estools/esquery/) |
| esrecurse | 4.3.0 | BSD-2-Clause | package.json | [链接](https://github.com/estools/esrecurse) |
| estraverse | 5.3.0 | BSD-2-Clause | package.json | [链接](https://github.com/estools/estraverse) |
| esutils | 2.0.3 | BSD-2-Clause | package.json | [链接](https://github.com/estools/esutils) |
| event-target-shim | 5.0.1 | MIT | package.json | [链接](https://github.com/mysticatea/event-target-shim) |
| eventemitter3 | 5.0.4 | MIT | package.json | - |
| events | 3.3.0 | MIT | package.json | - |
| fast-deep-equal | 3.1.3 | MIT | package.json | [链接](https://github.com/epoberezkin/fast-deep-equal#readme) |
| fast-diff | 1.3.0 | Apache-2.0 | package.json | - |
| fast-json-stable-stringify | 2.1.0 | MIT | package.json | [链接](https://github.com/epoberezkin/fast-json-stable-stringify) |
| fast-levenshtein | 2.0.6 | MIT | package.json | - |
| file-entry-cache | 11.1.5 | MIT | package.json | - |
| find-up | 5.0.0 | MIT | package.json | - |
| flat-cache | 6.1.23 | MIT | package.json | - |
| flatted | 3.4.4 | ISC | package.json | [链接](https://github.com/WebReflection/flatted#readme) |
| gifuct-js | 2.1.2 | MIT | package.json | [链接](https://github.com/matt-way/gifuct-js) |
| glob-parent | 6.0.2 | ISC | package.json | - |
| hashery | 1.5.1 | MIT | package.json | - |
| hookified | 1.15.1 | MIT | package.json | [链接](https://github.com/jaredwray/hookified#readme) |
| hookified | 2.2.0 | MIT | package.json | [链接](https://github.com/jaredwray/hookified#readme) |
| ieee754 | 1.2.1 | BSD-3-Clause | package.json | - |
| ignore | 5.3.2 | MIT | package.json | - |
| imurmurhash | 0.1.4 | MIT | package.json | [链接](https://github.com/jensyt/imurmurhash-js) |
| is-extglob | 2.1.1 | MIT | package.json | [链接](https://github.com/jonschlinkert/is-extglob) |
| is-glob | 4.0.3 | MIT | package.json | [链接](https://github.com/micromatch/is-glob) |
| isexe | 2.0.0 | ISC | package.json | [链接](https://github.com/isaacs/isexe#readme) |
| ismobilejs | 1.1.1 | MIT | package.json | [链接](https://github.com/kaimallea/isMobile) |
| jiti | 1.21.7 | MIT | package.json | - |
| js-binary-schema-parser | 2.0.3 | MIT | package.json | [链接](https://github.com/matt-way/jsBinarySchemaParser) |
| jsnes | 2.1.0 | Apache-2.0 | package.json | [链接](https://github.com/bfirsh/jsnes) |
| json-schema-traverse | 0.4.1 | MIT | package.json | [链接](https://github.com/epoberezkin/json-schema-traverse#readme) |
| json-stable-stringify-without-jsonify | 1.0.1 | MIT | package.json | [链接](https://github.com/samn/json-stable-stringify) |
| jsonwebtoken | 9.0.3 | MIT | package.json | - |
| jwa | 2.0.1 | MIT | package.json | - |
| jws | 4.0.1 | MIT | package.json | - |
| keyv | 5.6.0 | MIT | package.json | [链接](https://github.com/jaredwray/keyv) |
| levn | 0.4.1 | MIT | package.json | [链接](https://github.com/gkz/levn) |
| locate-path | 6.0.0 | MIT | package.json | - |
| lodash.includes | 4.3.0 | MIT | package.json | [链接](https://lodash.com/) |
| lodash.isboolean | 3.0.3 | MIT | package.json | [链接](https://lodash.com/) |
| lodash.isinteger | 4.0.4 | MIT | package.json | [链接](https://lodash.com/) |
| lodash.isnumber | 3.0.3 | MIT | package.json | [链接](https://lodash.com/) |
| lodash.isplainobject | 4.0.6 | MIT | package.json | [链接](https://lodash.com/) |
| lodash.isstring | 4.0.1 | MIT | package.json | [链接](https://lodash.com/) |
| lodash.merge | 4.6.2 | MIT | package.json | [链接](https://lodash.com/) |
| lodash.once | 4.1.1 | MIT | package.json | [链接](https://lodash.com/) |
| lodash.reduce | 4.6.0 | MIT | package.json | [链接](https://lodash.com/) |
| lucide-react | 0.400.0 | ISC | package.json | [链接](https://lucide.dev) |
| macaddress | 0.5.4 | MIT | package.json | [链接](https://github.com/scravy/node-macaddress) |
| minecraft-data | 3.115.0 | MIT | package.json | - |
| minecraft-folder-path | 1.2.0 | MIT | package.json | [链接](https://github.com/simonmeusel/minecraft-folder-path#readme) |
| minecraft-protocol | 1.68.0 | BSD-3-Clause | package.json | - |
| mineflayer | 4.39.0 | MIT | package.json | - |
| minimatch | 10.2.6 | BlueOak-1.0.0 | package.json | - |
| mojangson | 2.1.0 | MIT | package.json | - |
| moo | 0.5.3 | BSD-3-Clause | package.json | - |
| ms | 2.1.3 | MIT | package.json | - |
| natural-compare | 1.4.0 | MIT | package.json | - |
| nearley | 2.20.1 | MIT | package.json | - |
| node-fetch | 2.7.0 | MIT | package.json | [链接](https://github.com/bitinn/node-fetch) |
| node-rsa | 0.4.2 | MIT | package.json | [链接](https://github.com/rzcoder/node-rsa) |
| ohash | 2.0.12 | MIT | package.json | - |
| optionator | 0.9.4 | MIT | package.json | [链接](https://github.com/gkz/optionator) |
| oxfmt | 0.35.0 | MIT | package.json | [链接](https://oxc.rs/docs/guide/usage/formatter) |
| p-limit | 3.1.0 | MIT | package.json | - |
| p-locate | 5.0.0 | MIT | package.json | - |
| parse-svg-path | 0.2.0 | MIT | package.json | - |
| path-exists | 4.0.0 | MIT | package.json | - |
| path-key | 3.1.1 | MIT | package.json | - |
| pixi.js | 8.20.1 | MIT | package.json | [链接](http://pixijs.com/) |
| prelude-ls | 1.2.1 | MIT | package.json | [链接](http://preludels.com) |
| prettier | 3.9.6 | MIT | package.json | [链接](https://prettier.io) |
| prettier-linter-helpers | 1.0.1 | MIT | package.json | [链接](https://github.com/prettier/prettier-linter-helpers#readme) |
| prismarine-auth | 3.1.1 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-auth#readme) |
| prismarine-biome | 1.4.0 | MIT | package.json | - |
| prismarine-block | 1.23.0 | MIT | package.json | - |
| prismarine-chat | 1.13.0 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-chat#readme) |
| prismarine-chunk | 1.41.0 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-chunk) |
| prismarine-entity | 2.6.0 | MIT | package.json | - |
| prismarine-item | 1.18.0 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-item#readme) |
| prismarine-nbt | 2.8.0 | MIT | package.json | [链接](https://github.com/prismarinejs/prismarine-nbt) |
| prismarine-physics | 1.11.1 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-physics#readme) |
| prismarine-realms | 1.6.0 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-realms#readme) |
| prismarine-recipe | 1.5.0 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-recipe#readme) |
| prismarine-registry | 1.12.0 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-registry#readme) |
| prismarine-windows | 2.10.0 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-windows#readme) |
| prismarine-world | 3.7.0 | MIT | package.json | [链接](https://github.com/PrismarineJS/prismarine-world) |
| process | 0.11.10 | MIT | package.json | - |
| protodef | 1.19.0 | MIT | package.json | [链接](https://github.com/ProtoDef-io/node-protodef) |
| protodef-validator | 1.5.0 | MIT | package.json | [链接](https://github.com/ProtoDef-io/node-protodef-validator#readme) |
| punycode | 2.3.1 | MIT | package.json | [链接](https://mths.be/punycode) |
| qified | 0.10.1 | MIT | package.json | [链接](https://github.com/jaredwray/qified#readme) |
| railroad-diagrams | 1.0.0 | CC0-1.0 | package.json | [链接](https://github.com/tabatkins/railroad-diagrams) |
| randexp | 0.4.6 | MIT | package.json | [链接](http://fent.github.io/randexp.js/) |
| rcon-client | 4.2.5 | MIT | package.json | - |
| react | 19.3.0 | MIT | package.json | [链接](https://react.dev/) |
| react-dom | 19.3.0 | MIT | package.json | [链接](https://react.dev/) |
| readable-stream | 4.7.0 | MIT | package.json | [链接](https://github.com/nodejs/readable-stream) |
| ret | 0.1.15 | MIT | package.json | - |
| rxjs | 7.8.2 | Apache-2.0 | package.json | [链接](https://rxjs.dev) |
| safe-buffer | 5.2.1 | MIT | package.json | [链接](https://github.com/feross/safe-buffer) |
| scheduler | 0.28.0 | MIT | package.json | [链接](https://react.dev/) |
| semver | 7.8.5 | ISC | package.json | - |
| shebang-command | 2.0.0 | MIT | package.json | - |
| shebang-regex | 3.0.0 | MIT | package.json | - |
| smart-buffer | 4.2.0 | MIT | package.json | [链接](https://github.com/JoshGlazebrook/smart-buffer/) |
| string_decoder | 1.3.0 | MIT | package.json | [链接](https://github.com/nodejs/string_decoder) |
| synckit | 0.11.13 | MIT | package.json | - |
| tailwind-merge | 2.6.1 | MIT | package.json | [链接](https://github.com/dcastil/tailwind-merge) |
| tiny-lru | 11.4.7 | BSD-3-Clause | package.json | [链接](https://github.com/avoidwork/tiny-lru) |
| tinypool | 2.1.0 | MIT | package.json | [链接](https://github.com/tinylibs/tinypool#readme) |
| tr46 | 0.0.3 | MIT | package.json | [链接](https://github.com/Sebmaster/tr46.js#readme) |
| tslib | 2.8.1 | 0BSD | package.json | [链接](https://www.typescriptlang.org/) |
| type-check | 0.4.0 | MIT | package.json | [链接](https://github.com/gkz/type-check) |
| typed-emitter | 2.1.0 | MIT | package.json | - |
| typed-emitter | 0.1.0 | MIT | package.json | - |
| typed-emitter | 1.4.0 | MIT | package.json | - |
| uint4 | 0.1.2 | MIT | package.json | [链接](https://github.com/wtfaremyinitials/uint4) |
| undici-types | 6.21.0 | MIT | package.json | [链接](https://undici.nodejs.org) |
| uri-js | 4.4.1 | BSD-2-Clause | package.json | [链接](https://github.com/garycourt/uri-js) |
| use-sync-external-store | 1.7.0 | MIT | package.json | - |
| uuid | 8.3.2 | MIT | package.json | - |
| uuid | 10.0.0 | MIT | package.json | - |
| uuid-1345 | 1.0.2 | MIT | package.json | [链接](https://github.com/scravy/uuid-1345) |
| vec3 | 0.2.0 | BSD | package.json | - |
| vec3 | 0.1.10 | BSD | package.json | - |
| webidl-conversions | 3.0.1 | BSD-2-Clause | package.json | - |
| whatwg-url | 5.0.0 | MIT | package.json | - |
| which | 2.0.2 | ISC | package.json | - |
| word-wrap | 1.2.5 | MIT | package.json | [链接](https://github.com/jonschlinkert/word-wrap) |
| xxhash-wasm | 0.4.2 | MIT | package.json | - |
| yggdrasil | 1.8.0 | MIT | package.json | - |
| yocto-queue | 0.1.0 | MIT | package.json | - |
| zustand | 4.5.7 | MIT | package.json | [链接](https://github.com/pmndrs/zustand) |

---

机读版本：`licenses/SUMMARY.json`；许可证原文：`licenses/` 目录。
