# Terminal-Bench Agent network policy

The converted Terminal-Bench rows now use the canonical object form for
`environment.agent_network`. The row mode remains `internet` to preserve the
existing tester configuration's explicit `extend` behavior. The row domain
list records the destinations required by the public task; it does not grant
direct connections or Evaluation-time network access.

| Rows | Declared domains | Public-task basis |
| --- | --- | --- |
| `cancel-async-tasks`, `headless-terminal`, `kv-store-grpc` | `pypi.org`, `pythonhosted.org` | The prompts permit or require installing Python packages. |
| `count-dataset-tokens`, `hf-model-inference` | `huggingface.co`, `hf.co`, `xethub.hf.co`, `pypi.org`, `pythonhosted.org` | Hugging Face dataset/model downloads and Python package installation. |
| `extract-moves-from-video` | `youtube.com`, `googlevideo.com`, `ytimg.com`, `pypi.org`, `pythonhosted.org` | The prompt names a YouTube video and may require a downloader package and media hosts. |
| `install-windows-3.11` | `download.qemu.org` | The checked-in QEMU preparation reference downloads QEMU 5.2 from this host. |
| All other Terminal-Bench rows | `[]` | No reviewed required destination was identified; this preserves their prior empty row declaration and tester-default behavior. |

The three Hugging Face domains cover the repository and the observed storage
host families named by the conversion review. `googlevideo.com` and `ytimg.com`
are kept with the named YouTube origin because media delivery and
thumbnail/player requests can use those subdomains. The GPT-2 blob host is not
declared because the checked-in image preparation downloads those weights at
image-build time; candidate-time use of another host remains unqualified.

The explicit tester `extend` lists can still broaden effective Agent egress,
so a run's tester policy remains part of the reviewed execution configuration.
The row edit changes row and provenance digests. Historical Linux qualification
therefore remains evidence for the prior row state and must be rerun for the
twenty-five incremental conversions before they can be presented as renewed
Approved conversions. This static migration does not qualify unobserved CDN,
package mirror, or API redirects; a real-Docker egress check must record any
additional required host before admission.
