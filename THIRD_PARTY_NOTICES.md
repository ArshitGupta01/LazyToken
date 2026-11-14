# Third-party notices

The optional 3D dashboard vendors **Three.js 0.187.0**, including `three.module.js`, `three.core.js`, and `OrbitControls.js`, from <https://github.com/mrdoob/three.js>. Three.js is distributed under the MIT license; its full copyright and license notice is included in `vendor/THREE-LICENSE.txt`. The OrbitControls import path was adjusted to load the bundled local module. Three.js is loaded only when 3D is requested and is not required by the MCP server.

LazyToken's coding-efficiency policy was informed by reviewing <https://github.com/DietrichGebert/ponytail>. No Ponytail source code is included or required.

This Windows build includes the optional Hugging Face **tokenizers 0.19.1** runtime from https://github.com/huggingface/tokenizers, under the Apache License 2.0. Its license is bundled as `vendor/TOKENIZERS-LICENSE.txt`. No model or tokenizer vocabulary is shipped; a matching local tokenizer file must be supplied separately for strict configured-tokenizer budgets. The source core works without this optional runtime.
