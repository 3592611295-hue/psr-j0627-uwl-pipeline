# PSR J0627+0706 Parkes/UWL pipeline

这是一个面向新 Parkes/UWL `.rf` 折叠归档的可复用处理流程。它把此前分散的 PSRCHIVE 命令、模板对齐、双 off-window 质控、去色散子带检查、候选分级和总表汇总放进同一个可追溯的仓库。

当前结果的科学定位是 **candidate evidence**。脚本不会把 7 个 subint 的单次观测包装成完整的模式转换统计确认。

## 最重要的流程约束

1. 原始 `.rf` 只读，绝不原地修改；`paz` 和 `pam` 总是写新文件。
2. 不做 time-scrunch，保留原始亚积分。
3. 全频 `.I` 和所有 4/8/16 子带归档都显式执行 `pam -D`。
4. 子带只分析 PSRCHIVE 生成且验证为 `dmc=1` 的 `I4D/I8D/I16D`；Python 代码不允许把 raw-channel `pdv` 数据按通道直接分组求和。
5. 每个观测只从全频平均轮廓求一个 template shift；同一个 shift 固定应用于全部 subint 和全部子带，不能逐 subint/子带追峰。
6. MP、candidate-IP、两个 off-window、子带边界和阈值写入冻结配置，并随每次结果快照保存；所有 bin 窗口统一使用 Python 半开区间 `[start,end)`。
7. `uwl_241215_133711` 一类高频限域事件单列，不自动进入 full-UWL broadband 样本。
8. 相对能量单位是任意单位，不是经过 FluxCal 的 mJy。

这些约束及统计定义见 [docs/methodology.md](docs/methodology.md)。

## 处理链

```text
.rf
 ├─ 基础元数据检查 + raw flux/frequency plots
 ├─ paz -r -> .zap（保留 full Stokes 和原始 subint）
 ├─ zap plots
 ├─ pam -D -F -p -> .I
 ├─ bin profile + 独立 FTP 模板匹配 + MJD
 ├─ MP/IP-test 能量、误差、S/N + 双 off-window QC
 ├─ pam -D -p --setnchn 4/8/16 -> I4D/I8D/I16D
 ├─ dmc/nchan provenance gate
 ├─ 四子带宽带一致性和候选 Tier A/B/C
 └─ observation summary + master summary + MJD relative-energy SVG
```

## 默认冻结参数

示例配置 [configs/j0627_uwl.example.json](configs/j0627_uwl.example.json) 保存了当前流程参数：

- `nbin = 1024`
- FTP template：`uwl_220604_024229.FTp`（仓库不包含数据文件）
- MP：`[465,525)`，共 60 个 bin
- candidate-IP test window：`[970,30)`，跨相位零点
- primary off：`[650,800)`，共 150 个 bin
- control off：`[100,250)`，共 150 个 bin
- 四子带：`704–1536`、`1536–2368`、`2368–3200`、`3200–4032 MHz`
- fullband state S/N：`<3` non-detection、`3–5` low-S/N、`5–8` weak、`≥8` strong

`970–30` 只叫作 **candidate-IP test window**。除非有导师模板、论文或独立高信噪比轮廓支持，不能把它写成已经确认的 IP。

`reference_band_index` 默认是 `null`。这是有意为之：应先只按有效数据比例和 off-pulse RMS 选择并冻结 B_ref，不能按 MP high/low 分离效果或 IP 表现倒推 B_ref。

汇总若干处理完成的观测后，可先生成不读取 MP 分离或 IP 响应的 QC 表：

```bash
PYTHONPATH=src python3 -m j0627_uwl bref-report \
  --results /mnt/data/results
```

人工检查 `master_summary/reference_band_qc_report.csv` 以及 zap 权重后，再把 B_ref 的低到高频索引写回新冻结配置。

## Windows + Docker 快速运行

准备目录：

```text
C:\psrchive_work\
├─ uwl_YYMMDD_HHMMSS.rf
├─ templates\uwl_220604_024229.FTp
├─ psr-j0627-uwl-pipeline\
└─ results\
```

在 PowerShell 中：

```powershell
cd C:\psrchive_work\psr-j0627-uwl-pipeline

powershell -ExecutionPolicy Bypass -File .\scripts\run_docker.ps1 `
  -InputFile "uwl_241215_133711.rf"
```

默认使用此前环境中的镜像：

```text
artefact.skao.int/ska-pst-dspsr:0.3.7
```

如镜像名不同，可传 `-Image`。如果要正式冻结参数，先复制示例配置为 `local-config.json`，修改模板路径和经确认的阈值，再把该文件以只读方式挂入容器。

## 容器内或 Linux 运行

无需安装第三方 Python 包：

```bash
cp configs/j0627_uwl.example.json local-config.json

PYTHONPATH=src python3 -m j0627_uwl validate-config \
  --config local-config.json
```

先生成命令计划，不运行 PSRCHIVE：

```bash
PYTHONPATH=src python3 -m j0627_uwl plan \
  --config local-config.json \
  --input /mnt/data/uwl_241215_133711.rf \
  --output /mnt/data/results
```

处理一个文件：

```bash
bash scripts/run_one.sh \
  local-config.json \
  /mnt/data/uwl_241215_133711.rf \
  /mnt/data/results
```

批量处理：

```bash
bash scripts/run_batch.sh \
  local-config.json \
  /mnt/data/new_rf \
  /mnt/data/results \
  'uwl_*.rf'
```

汇总所有成功观测：

```bash
PYTHONPATH=src python3 -m j0627_uwl summarize \
  --results /mnt/data/results
```

每个已有结果目录默认不覆盖。确认配置完全相同后才能传 `--resume`；若要改变窗口、模板或阈值，请使用新的 results 根目录，保留旧证据链。

## 输出目录

```text
results/
├─ observations/
│  └─ uwl_YYMMDD_HHMMSS/
│     ├─ 00_manifest/          # 输入信息、冻结配置、完成状态
│     ├─ 01_checks/            # vap / psrstat / psredit
│     ├─ 02_raw_plots/
│     ├─ 03_zap/               # .zap，保留 subint/full Stokes
│     ├─ 04_zap_plots/
│     ├─ 05_total_intensity/   # 显式去色散的 .I 及 plots
│     ├─ 06_profiles/          # pdv 文本和 bin profile
│     ├─ 07_template_match/    # shift、corr、对齐轮廓 SVG
│     ├─ 08_qc/                # subint_metrics.csv
│     ├─ 09_subbands/
│     │  ├─ n04/               # I4D、dmc provenance、metrics、plots
│     │  ├─ n08/
│     │  └─ n16/
│     ├─ 10_candidates/        # event/observation summary
│     └─ logs/commands.jsonl   # 每条外部命令与返回状态
└─ master_summary/
   ├─ master_observations.csv
   ├─ master_candidate_events.csv
   ├─ master_subint_qc.csv
   ├─ master_summary.md
   └─ mjd_relative_energy.svg
```

列定义见 [docs/output-schema.md](docs/output-schema.md)。

## 候选分级

四子带分类只使用显式去色散后的 `I4D`：

- Tier A：4/4 子带在两个 off-window 下都稳定为正，且 fullband QC 通过。
- Tier B：3/4 子带同向，剩余子带低 S/N，未出现稳定负响应。
- Tier C：仅 1–2 个相邻子带、仅最高频子带、对 off-window 敏感、符号冲突或仅子带检出。

8/16 子带用于定位频率范围和排查窄带 RFI，不用于事后“升级”四子带结论。已知 `241215` 观测在配置中带独立 review annotation，即使全频峰很强，也必须经 dedispersed multi-band coherence 重新证明才能进入 broadband pool。

## 外部 MP 分类器（可选、后置）

单个 7-subint 文件不拟合 HMM，也不按中位数强行切成 high/low。只有累计足够多、处理一致的 UWL 观测后才能：

1. 仅用 QC 选择并冻结 `reference_band_index`；
2. 把 `external_classifier.enabled` 改为 `true`；
3. 对目标观测执行 leave-one-observation-out 训练和冻结：

```bash
PYTHONPATH=src python3 -m j0627_uwl freeze-groups \
  --config local-config.json \
  --results /mnt/data/results \
  --target uwl_231005_181706
```

脚本比较单高斯和两高斯 BIC，并检查组件分离度。未通过就拒绝生成 `mp_groups_frozen.csv`。通过时输出连续 `p_high/p_low`；`p≥0.8` 和 `p≤0.2` 的硬标签只用于画图。

冻结后可做描述性的概率加权 candidate-IP 差值、固定概率回归和共同增益控制：

```bash
PYTHONPATH=src python3 -m j0627_uwl conditional-ip \
  --config local-config.json \
  --results /mnt/data/results \
  --target uwl_231005_181706
```

该命令不输出渐近 p 值。四子带带协方差的联合 Monte Carlo 需要从合法伪窗口或噪声实现估计协方差，不能用 7 个回归残差硬估一个 `4×4` 矩阵，因此没有在缺少验证数据时自动给出“显著性”。

## 明确不做的事

对目前常见的 7-subint 观测，pipeline 不做：

- 单文件两状态 HMM
- 驻留时间和转换率
- 循环移位主检验
- 状态转换延迟拟合
- 逐 subint/逐子带独立模板追峰
- 未定标数据的偏振物理解读

新的短 subint、full-Stokes、PolCal/FluxCal UWL 观测到位后，再扩展为真正的模式转换统计。

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
bash -n scripts/run_one.sh
bash -n scripts/run_batch.sh
```

单元测试不需要 PSRCHIVE；真实 `.rf` 端到端测试必须在 PSRCHIVE 容器里完成。

## PSRCHIVE 依据

- [PSRCHIVE `paz` manual](https://psrchive.sourceforge.net/manuals/paz/)
- [PSRCHIVE `pam` manual](https://psrchive.sourceforge.net/manuals/pam/)
- [PSRCHIVE cold-plasma/dedispersion behavior](https://psrchive.sourceforge.net/manuals/guide/design/cold_plasma.shtml)
- [PSRCHIVE standard output options](https://psrchive.sourceforge.net/manuals/guide/design/options.shtml)
