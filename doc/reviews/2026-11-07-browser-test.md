# 浏览器操作测试记录

状态：全部 9 批执行完成，本轮测试已结束。182 条唯一用例均有记录：167 通过、10 失败、5 阻塞、0 未执行。阻塞项为部分覆盖限制，不代表产品缺陷；功能未全部验收通过。

最新执行约束：用户调整后仅使用 headless agent-browser；禁止 Computer Use、桌面操作、`--headed`、连接 CDP 或 auto-connect。此前浏览器已由主执行者关闭，后续使用独立 headless 会话恢复。所有 XLSX 按用户最新要求使用只读脚本核验，禁止 Excel 桌面操作；S-17、X-02 按此条件判定。

## 环境

| 项目 | 实际环境 |
| --- | --- |
| 日期、执行人 | 2026-11-07，sol |
| 测试地址 | http://127.0.0.1:8088 |
| 浏览器 | Chrome，User-Agent 版本 156.0.0.0 |
| 操作工具 | agent-browser CLI 0.33.0 |
| 主窗口 | 1440 × 900；A-09 / A-10、X-01 初次截图尺寸例外已在相同流程复测中纠正，最终引用均为 1440 × 900 |
| 当前会话 | sol-owner-real，独立配置文件 |
| 执行账号 | sol-owner@example.edu、sol-admin@example.edu、sol-temp@example.edu、sol-editor@example.edu、sol-viewer@example.edu、sol-disabled@example.edu、sol-outsider@example.edu、sol-annotator@example.edu |
| 仓库版本 | HEAD `d731a34`；方案记为 `b900df9`，与运行镜像的对应关系待核对 |
| Compose 项目 | corpus |
| 测试项目 | Sol 浏览器测试，`e6b68bfd-c5ba-4de3-81ce-8a180fb439a6` |
| 服务状态 | api、postgres、worker、worker-light 为 healthy；web、agent 为运行中 |
| 健康检查 | `/api/health`：ok=true、db=true；`/agent/health`：ok=true |
| 样本 | `tmp/browser-test/samples/` 中方案所列样本均存在 |
| 证据目录 | `tmp/browser-test/shots/`；截图按 `<用例编号>-<序号>-<简述>.png` 命名 |

## 用例结果

已测结果按批次追加，未测用例不预判。

| 用例 | 结果 | 备注 |
| --- | --- | --- |
| A-01 | 通过 | 首次登录进入 `/onboarding`，显示创建项目、导入语料、第一次检索、试试助手、完成五步骤，未出现改密页。截图：A-01-2-onboarding.png。 |
| G-01 | 通过 | 输入 70 字长名称被截为 60 字，显示“60 / 60”；创建“Sol 浏览器测试”成功并进入第 2 步，其余步骤可点。截图：G-01-1-created.png。 |
| G-02 | 通过 | 预填“翻译”检索命中大于 0；改为 `翻译/v` 后解释为“限定动词”，结果稳定为 38 次 / 34 句；保存后为“已保存”。截图：G-02-1-search.png。 |
| G-03 | 通过 | 助手约 3 秒、1 次工具调用，KWIC 卡片正常渲染 3 条例句；正文无 UUID，38 次 / 34 句 / 1 篇与其精确词形工具查询一致；引导后证据篮仍为 0。截图：G-03-1-kwic.png。 |
| G-04 | 通过 | 完成摘要显示“已创建 / 可检索 / 已保存 / 可用”；进入检索后保留 Tatoeba 中英范围与 `翻译/v` 查询。截图：G-04-2-loaded.png。 |
| P-01 | 失败 | B01：带前后空格邮箱被前端拦截为“请输入邮箱”；改用小写无空格邮箱后添加成功，最终 5 人，角色及“我”标签正确，角色列为下拉。截图：P-01-1-email.png。 |
| S-01 | 通过 | “翻译”60 次 / 55 句 / 34 篇；“研究”545 / 439 / 141；`研究 $3 方法` 3 / 2 / 2。第三组经只读 DOM 观察，计数由检索中直接变为终值，无滚动。截图：S-01-3-final-counts.png。 |
| S-07 | 通过 | Tatoeba 中英：“说话”简繁通查开为 178 次 / 174 句，关闭为 74 次 / 74 句；打开后以英文双引号精确检索为 73 次。截图：S-07-1-expanded.png、S-07-3-exact-final.png。 |
| C-01 | 通过 | 上传 GBK 样本后“S-GBK 作文”为 1 篇 / 11 句 / 236 词，语言 zh、可检索；首句“我的翻译学习体会”无乱码；“翻译”命中 9 次。截图：C-01-1-preview.png、C-01-2-nine-hits.png。 |
| AS-01 | 通过 | 12.7 秒、3 次工具调用；展开有中文“解析查询式”“计算搭配”，参数为窗口 5、前 10、logdice。图表前 3 项奥德赛 10.61、英文 10.55、爱因斯坦 10.52，节点 60 次、总计 784,327 词；无 UUID 或未注册组件，证据篮仍 0。截图：AS-01-1-running.png、AS-01-2-chart-and-tools.png、AS-01-3-final-chart.png。 |
| X-01 | 通过 | 实际浏览器打开 `/api/docs`、`/api/openapi.json` 均为 404；文档 `/`、`/login` 为 200，`/api/auth/me` 为 401，均含四项预期安全响应头。截图：X-01-3-docs-1440.png、X-01-4-openapi-1440.png。 |
| T-01 | 通过 | 排除标点和数字时前 5 行为的 26,909、年 10,794、在 8,139、月 5,582、和 4,905；总计 784,327 词、排除 171,711 词、1,003 部分。DP 与 Juilland D 悬停分别显示 `DP = ½ Σ∣vᵢ − sᵢ∣`、`D = 1 − CV / √(n − 1)` 公式说明。取消排除后首行为逗号 43,129、第三行为句号 25,178。截图：T-01-1-frequency.png、T-01-2-punctuation.png。 |
| C-28 | 通过 | 中文侧 1 篇 / 45,703 句 / 402,442 词，英文侧 1 篇 / 220,395 句 / 2,110,299 词；点击中文侧放大镜后检索范围正确。C-06 后补测 HF 2021 起（year ≥ 2021）为 554 篇 / 560 句 / 7,359 词，篇数小于 1,136，整条完成。截图：C-28-2-tatoeba-sizes.png、C-28-3-use-subcorpus.png、C-28-4-hf-subcorpus.png。依赖顺序见 R01。 |
| S-17 | 通过 | 按用户调整以只读结构核验判定：CSV、XLSX 已通过界面下载，结构核验通过；CSV 按标准 CSV 解析为 84 条数据（88 个记录含两行文件头、空行及表头）；XLSX A5:L88 为 84 行，首条 D5 句序 547 与界面一致，两行文件头与 CSV 完全一致，含 84 / 79 / 1、UTC、索引 `8fac8adcbbce1514`、来源和许可。A4:L4 字段标题均使用宋体粗体；1,022 个已存储单元格均引用 fillId=0、无底色，未发现公式。用户已调整验收条件为只读结构检查，该条件通过；未声称进行 Excel 可视打开。截图：S-17-1-export.png（界面导出已完成；Office 拒绝由工具文本返回）。 |
| A-05 | 通过 | sol-admin 在独立会话搜索 sol-，确认原有 7 个账号；界面新建 sol-temp（Sol 临时、未勾管理员）后显示“账号已创建”，临时密码长度 16，复制后提示“已复制”；点击弹窗外不关闭。完成后列表为“正常 / 从未 / 项目 0”。截图：A-05-1-created-user.png。密码未写入文件或证据。 |
| A-06 | 通过 | sol-temp 首次临时密码登录进入“设置新密码”，导航根地址仍返回改密页；依次触发“新密码长度须为 12 到 1024 位”“新密码不能与原密码相同”“两次输入的新密码不一致”；有效修改后进入 `/onboarding`。截图：A-06-1-onboarding.png。 |
| C-02 | 通过 | 重开上传对话框默认“新建语料库”、文件为空；选择 essay-01.txt 后按 Esc 关闭，再打开仍无文件。截图：C-02-1-clean-reopen.png。 |
| C-03 | 阻塞 | E02，部分完成：两次点选同一 essay-01.txt 可正确显示“已跳过重复文件：essay-01.txt”，列表仅 1 个；方案要求的第二次拖入文件尚未执行，CLI drag 仅支持页面 DOM source / target，无本地文件拖入参数，未用 JS 合成 drop，不能以重复点选替代整条通过。截图：C-03-1-duplicate-file.png。 |
| A-07 | 通过 | sol-temp 两个独立会话：错误原密码提示“原密码不正确”；有效修改提示“密码已修改，其他设备需重新登录”。B 刷新回登录，A 刷新仍在 `/settings?tab=account`。截图：A-07-1-password-changed.png、A-07-2-other-session-loggedout.png。 |
| A-08 | 通过 | sol-admin 仅重置 sol-temp，显示“密码已重置”，临时密码 16 位；temp A 刷新回登录，新临时密码登录进入“设置新密码”，按方案改密后恢复应用。截图：A-08-1-session-invalid.png、A-08-2-reset-completed.png。 |
| P-02 | 通过 | 添加 nobody@example.edu 显示“邮箱不存在”，成员仍 5 人；键盘清空邮箱后添加显示“请输入邮箱”。截图：P-02-1-validation.png。 |
| C-05 | 通过 | 无效 JSON、两行 year 重复、第 2 行缺少字段名分别显示对应错误。使用有效名称“S-C05校验不提交”及 essay-01.txt 再测重复 year：上传按钮视觉可点，但点击被校验拦截，对话框保持且显示“字段「year」重复”，未创建语料或提交任务；“不可提交”成立，非按钮 disabled。截图：C-05-1-validation.png、C-05-2-duplicate-key.png、C-05-3-missing-key.png、C-05-6-submit-blocked.png。 |
| P-03 | 通过 | temp 以查看者加入后在项目菜单实际选主项目并检索；owner 改为标注者后 temp 刷新显示“标注者”。移除并确认后 temp 刷新整页显示“你已不是该项目成员”“项目已删除，或负责人已将你移出。”，可选“我的研究项目”或“新建项目”。临时成员已移除，主项目恢复 5 人。截图：P-03-1-role-changed.png、P-03-2-removed-member-gate.png。 |
| P-04 | 通过 | owner 改名后提示“已改名”，面包屑同步；editor 独立会话的名称框禁用，无保存、删除项目、审计入口。owner 已恢复“Sol 浏览器测试”原名并收到“已改名”。截图：P-04-1-renamed.png、P-04-2-editor-readonly.png。 |
| P-07 | 通过 | owner 刷新可见 8 条项目审计，含 temp 添加、改角色、移除，列为时间 / 操作人 / 操作 / 对象；editor 不显示审计。截图：P-07-2-audit-refreshed.png。 |
| A-04 | 通过 | owner 设置仅项目 / 账号 / 数据与隐私；直接打开 `?tab=admin` 仍为项目页，无管理内容。按用例控制台请求 `GET /api/admin/users` 返回 403、`FORBIDDEN`、“权限不足”。 |
| C-29 | 通过 | owner 的 Tatoeba 详情仅文档、元数据，无上传、重建、文档编辑或删除入口；admin 在“Sol 管理员项目”的列表可见“新建内置语料”，详情有“上传”页签，仅查看未改动。截图：C-29-1-admin-built-in.png、C-29-2-owner-built-in.png。 |
| C-13 | 通过 | 选择 broken.jsonl 后显示“文件解析失败：broken.jsonl 第 2 行不是有效的 JSON：Expecting ',' delimiter”，错误码 `PARSE_ERROR`，未出现 INTERNAL。截图：C-13-1-broken-jsonl.png。 |
| C-30 | 通过 | 实点“内置 5”筛选为 5 行，“项目 20”为 20 行，“全部 25”满足 5 + 20；Tatoeba 文档列为 47,533 句对，索引更新“9 天前”、可检索，未显示哈希；项目库删除图标提示“删除语料库「名称」”。截图：C-30-1-project-filter.png。 |
| A-11 | 通过 | sol-admin 自身行有“我”且无操作按钮；临时将 sol-temp 设为管理员，确认后列表为“是”，temp 刷新出现管理页签；取消管理员并确认后 temp 刷新管理页签消失，已恢复普通账号。截图：A-11-2-admin-after-reload.png、A-11-3-admin-revoked.png。 |
| C-23 | 通过 | 通过真实 DevTools Network / Throttling 原生选择框设为 3G；120 MB 上传显示 0.0 → 0.7 / 120 MB 递增，点“取消上传”后提示“已取消上传”。随即恢复 No throttling，刷新后无“S-取消上传”空库。截图：C-23-1-upload-progress.png、C-23-2-progress-increased.png、C-23-3-cancelled.png、C-23-4-throttle-restored.png、C-23-5-no-empty-corpus.png。已恢复无限制并清理本次空库。 |
| P-05 | 通过 | “Sol 删除测试”确认框列出 0 语料库、0 标注层、0 笔记、0 文献与规范、0 术语、2 成员及 7 天内可恢复；确认删除提示“已删除项目”并离开项目，viewer 刷新显示门页。owner 从主项目“最近删除”恢复后提示“已恢复项目”，viewer 刷新可重新访问临时项目语料库页。已立即恢复。截图：P-05-1-delete-confirm.png、P-05-2-deleted-gate.png、P-05-3-restored.png。 |
| P-06 | 通过 | 第二次软删除“Sol 删除测试”后，admin 在已删除项目列表看到“删除于：刚刚”；确认“恢复项目「Sol 删除测试」？”后提示“已恢复项目「Sol 删除测试」”，该项目从已删除列表消失并在使用中显示 owner、2 成员，owner 刷新项目菜单重新可见。已立即恢复，成员仍 2 人，无遗留删除状态。截图：P-06-1-admin-restored.png。 |
| C-04 | 通过 | 5 篇作文导入完成，41 句 / 494 词，语言 en；genre 文本值为“学习者作文”、level 文本值为“大学二年级”，各 1 个取值。截图：C-04-1-metadata-form.png、C-04-2-completed-metadata.png。 |
| C-25 | 通过 | Tatoeba cmn 语言 zh、45,703 句 / 402,442 词；两次下一页后为第 101–150 句，共 45,703 句。补测作文完整分句预览，首句“My Hometown”，共 8 句。截图：C-25-1-cmn-preview.png、C-25-2-page-three.png、C-25-3-essay-preview.png。 |
| C-32 | 阻塞 | 部分完成： S-HF 导出初始未建、1,146 句、预计 6 秒；点击建立后经历“建立中 / 排队中”，完成为已建 1,146 句。重建排队中取消，仍显示“已建”及 1,146 句，旧索引保留可用。截图：C-32-1-building.png、C-32-2-built.png、C-32-3-old-index-after-cancel.png。已取消本次重建，保留已建索引；实际运行中 x / y 句的中间进度帧未捕获，不声称已核验该数字进度。 |
| A-09 | 通过 | 仅停用 sol-disabled，确认文案说明会话立即失效，状态变“已停用”；其会话点击统计即回登录页，正确原密码登录提示“账号已停用，请联系管理员”，无错误码小字。截图：A-09-2-disabled-login-1440.png。已接续 A-10 立即恢复。 |
| A-10 | 通过 | admin 确认启用 sol-disabled 后状态正常；该账号以原密码重新登录可进入主项目统计页，角色仍为查看者。截图：A-10-3-retest-restored-1440.png。已恢复正常，无遗留停用。 |
| C-22 | 通过 | 空闲时分别通过界面提交：`#85ea5c1e` 28 ms 失败，原文“bomb-520mb-unpacked.docx 文件解压后过大（超过 500 MB）”；`#0d043185` 409 ms 失败，原文“bomb-10001-files.docx 文件解压后过大（超过 10000 个文件）”，均为 `PARSE_ERROR`。worker 内存执行前后均约 1.912 GiB、1.747 GiB，无明显上涨；上传目录 24 M、语料目录 532 M，未展开大文件。截图：C-22-1-size-rejected.png、C-22-2-file-count-rejected.png。 |
| N-10 | 通过 | S-对齐中文 1 篇 / 12,000 句 / 58,000 词；S-对齐英文 1 篇 / 11,998 句 / 56,000 词，两库可检索、导入任务完成，句数符合“约 12,000”。截图：N-10-2-completed.png。 |
| N-01 | 通过 | 建立“S-学习者作文 词性”（upos 17、全部文档），层 `1aeb59f4-2952-4a14-9897-6585f25a2ff1`；新建预标后按 Enter 未重开对话框。My 确认、Hometown 改为 ADJ 后拒绝，来源保留“语料自带 · 人工确认 / 人工修改 / 人工拒绝”。J 到第 2 句、Shift+Enter 整句确认并自动下一句、K 返回第 2 句，已完成且本句 0 处待确认。无需刷新进度由 1 → 2 → 14 / 494（3%）；复用语料预标完成很快，未捕获运行中间帧。截图：N-01-1-layer-submitted.png、N-01-4-progress-after-confirm.png。 |
| P-09 | 通过 | outsider 独立登录后停在引导、未建项目；直接打开主项目检索页显示门页。按方案控制台 `GET /api/projects/e6b68bfd-c5ba-4de3-81ce-8a180fb439a6` 返回 404、`NOT_FOUND`、“项目不存在”。截图：P-09-1-nonmember-gate.png。 |
| A-02 | 通过 | 空提交提示“请输入邮箱和密码”，只读 animationstart 观察到登录卡 class 含 shake、动画名 shake；错误密码提示“邮箱或密码错误”；点眼睛后密码明文、按钮为“隐藏密码”。截图：A-02-1-login-validation.png。 |
| A-03 | 通过 | 静默超过 60 秒后连续 8 次错误密码：1–6 次为 401、“邮箱或密码错误”，7–8 次为 429、`LOGIN_RATE_LIMITED`、“登录尝试过多，请 1 分钟后再试”；再静默 65 秒正确密码登录恢复。功能符合预期，提示下重复错误码小字另记 B02。截图：A-03-1-rate-limited.png、A-03-2-recovered.png。 |
| G-05 | 通过 | owner 通过 Ctrl+K 搜“打开引导”，进入带已有项目参数的 `/onboarding`，从第 2 步“导入语料”开始；第 2、3、4 步分别点“跳过此步”，到完成后进入检索，未新建项目。截图：G-05-2-skipped-to-search.png。执行批次漏列更正见 R03。 |
| A-12 | 通过 | 距其他登录超过 60 秒，以 temp 的错误原密码和有效新密码连续界面提交 8 次：1–6 次 `POST /api/auth/password` 400、`WRONG_PASSWORD`，7–8 次 429、`LOGIN_RATE_LIMITED`；界面从“原密码不正确”变为“登录尝试过多，请 1 分钟后再试”。均为失败提交，实际密码未变。截图：A-12-1-shared-rate-limit.png。重复错误码小字合并记入 B02。 |
| P-11 | 通过 | 按方案控制台请求：editor 查找 owner 为 403、`FORBIDDEN`；owner 两次为 200，仅 id / email / display_name、不含 is_admin；不存在邮箱为 200、items 空。隔足独立分钟后并发 22 次为 20 个 200、2 个 429，`RATE_LIMITED`、“查找过于频繁，请一分钟后再试”。429 发生在循环编号 19、21，编号 22 为 200，因并发到达顺序不同，服务端总限额准确。截图：P-11-1-user-lookup-page.png（当前界面）；实证为 CLI 网络和控制台结果。 |
| C-07 | 通过 | 意大利语任务 `#17f8c0ea` 失败，`LANGUAGE_UNSUPPORTED`、“暂不支持该语言：it（支持 zh、en、ja、fr、de、es、ru）”；中夹英成功，1 篇 / 7 句 / 131 词、zh、可检索。截图：C-10-1-expected-failures.png。 |
| C-08 | 通过 | DOCX 标题“语料库翻译学概论”，24 句 / 135 词；预览包含 3 个一级标题、3 条列表、表格“通用汉英平行语料库”“约 2000 万字”及脚注式段落。截图：C-08-1-docx-preview.png。 |
| C-09 | 通过 | PDF 为 1 篇 / 18 句 / 144 词、en，标题正确，pages 数值为 3、author 为 Test Author；界面检索 explicitation 为 2 次 / 2 句 / 1 篇。截图：C-09-1-pdf-preview.png、C-09-2-two-hits.png。 |
| C-10 | 通过 | 扫描 PDF 任务 `#2f996659` 失败，`PARSE_ERROR`、“PDF 没有文字层（扫描件），暂不支持 OCR”。截图：C-10-1-expected-failures.png。 |
| C-11 | 通过 | 核验说明工作表及作文工作表映射后导入完成，5 篇 / 36 句 / 474 词；编号、年级、年份、性别、备注元数据齐全，年份为数值。截图：C-11-2-explanation-sheet.png、C-11-3-essay-sheet-map.png、C-11-4-completed.png。 |
| C-12 | 通过 | JSONL 完成 30 篇 / 60 句 / 715 词、zh；meta.year 为数值，meta.source、id 齐全；news001 源文件含 Unicode 转义的正文在预览显示正常中文。截图：C-12-1-map.png、C-12-2-completed-metadata.png、C-12-3-unicode-preview.png。 |
| C-14 | 通过 | 列表显示平行、12 句对、2 文档；界面检索“背景”为 1 次 / 1 句 / 1 对，译文“The translator needs to understand the cultural background of the source text.”无标签残留。截图：C-14-1-clean-alignment.png、C-14-2-pair-tooltip.png；悬停显示“2 个文档（每种语言一个）”。 |
| C-15 | 通过 | 中意 TMX 任务 `#f898390d` 失败，`LANGUAGE_UNSUPPORTED`、“TMX 含暂不支持的语言：it”。截图：C-10-1-expected-failures.png。 |
| C-16 | 通过 | 五库语言分别 ja / fr / de / es / ru；依次界面检索翻訳 5、traduction 5、Übersetzung 1、traducción 3、перевод 2 次；每种点首条 KWIC 打开上下文，均无乱码。截图：C-16-1-japanese.png、C-16-2-french.png、C-16-3-german.png、C-16-4-spanish.png、C-16-5-russian.png。 |
| C-17 | 通过 | 指定 fr 导入为 1 篇 / 8 句 / 158 词，界面检索 traduction 为 5 次，与自动识别结果一致。截图：C-17-1-specified-french.png。 |
| C-18 | 通过 | 中夹英语料为 zh，界面检索“离散度”为 1 次 / 1 句 / 1 篇。截图：C-18-1-chinese-mixed.png。 |
| C-19 | 通过 | 繁体库概况为 zh、繁体、jieba；查询卡显示“繁体”，简繁通查为选中状态。截图：C-19-1-overview.png、C-19-2-search-label.png。 |
| C-21 | 通过 | CoNLL-U 为 1 篇 / 3 句 / 18 词；界面 `{dep=obj}` 为 2 次（books、decision），`{lemma=make}` 为 1 次；无 text 的第 3 句正常显示“The translation is good.”。截图：C-21-1-dependency-hits.png、C-21-2-lemma-hit.png、C-21-3-three-sentences.png。 |
| C-24 | 通过 | 许可 CC BY 4.0、署名 Sol 测试、来源链接悬停信息齐全；界面检索 translation 为 3 次并实际导出 CSV，`tmp/browser-test/downloads-imports/检索结果-20261107-1356.csv` 来源行与所填完全一致。截图：C-24-1-license-tooltip.png、C-24-2-exported.png。 |
| C-31 | 通过 | 首句“Translation Quality”前无 BOM 乱码，4 句预览无空句。截图：C-31-1-bom-preview.png。 |
| C-06 | 通过 | 列映射、正文必填与元数据核验完成；导入 1,136 篇 / 1,146 句 / 15,063 词，year 数值等 7 字段完整。实际任务 `GET /api/jobs/6fea0f58...` 200 结果为 documents=1,136、skipped_duplicates=59；完成 toast 全文未捕获。第 10 行公式文字、第 113 行单元格换行、带逗号正文“This study revises the news report, sentence by sentence using a parallel corpus.”均在界面预览保留。截图：C-06-1-column-map.png、C-06-2-body-required.png、C-06-3-completed-metadata.png、C-06-4-row10.png、C-06-5-cell-newline.png、C-06-7-comma-text.png。标题规则见 R05。 |
| C-20 | 通过 | 追加横幅显示 S-去重已有 1 篇；追加通知“导入完成：0 篇，跳过重复 1 篇（dup-b.txt）”，任务 `#05ca36ad` 结果 0 篇、跳过 1 篇，未新增建索引，原索引仍 19 分钟前。批内任务 `#b8704bca` 为 1 篇、跳过 1 篇；批内完成 toast 未捕获，以实际任务响应及界面篇数核对。两库最终各 1 篇 / 2 句 / 22 词。截图：C-20-1-append-existing.png、C-20-2-skipped-duplicate.png、C-20-4-batch-final.png、C-20-5-no-index-after-zero-import.png、C-20-6-final-one-document.png、C-20-7-appended-still-one.png。 |
| P-08 | 通过 | 五账号逐格实际操作完成，17 行权限均符合矩阵，详细实测分项与最终矩阵见下文；负责人、编辑者双向取消/重试他人任务均 200，最终任务完成、运行 0 / 排队 0。负责人新 CSV 通过界面自动下载成功；已收回 `tmp/browser-test/downloads-perm-owner/检索结果-20261107-1429.csv`（27,581 B），结构核验 60 数据行、16 列、34 个文档，文件头 60 / 55 / 34。后续重复 CLI download 取消不计产品问题。无新增产品问题。关键截图：P-08-19-owner-sample-created.png、P-08-18-owner-method-appendix.png、P-08-46-editor-cancelled-owner-job.png、P-08-47-owner-cancelled-editor-job.png，其他分角色证据见下文。 |
| P-10 | 通过 | headless 重读设置角色表，四项目角色均列出、与 P-08 权限概述一致；帮助另列平台管理员。帮助文字为非排他的简要概述，未穷举标注者知识库能力不算矛盾。截图：P-10-2-settings-role-table.png、P-10-3-headless-role-help.png。 |
| S-19 | 通过 | Tatoeba 中文侧“翻译”简繁开，词形分解 84 = 翻 譯 38 + 翻译 38 + 翻译成 8。按右一词前 3 行为句号 20、成 15、逗号 6，逐行实际回到例句为 20 次 / 19 句 / 19 对、15 / 15 / 15、6 次，计数一致。设置含译文 translate 后分解禁用，悬停真实 title“含译文条件时不可用”。截图：S-19-1-wordform-breakdown.png、S-19-2-right-word-breakdown.png、S-19-3-period-return.png、S-19-4-cheng-return.png、S-19-5-comma-return.png、S-19-6-translation-condition-disabled.png。无失败网络或控制台。 |
| S-20 | 通过 | 从 Tatoeba 中文侧 84 次“翻译”实际点“统计译法”，头部为译文 en、命中句 79、有对齐 67、无对齐 12；前 3 行 translate 22、translated 14、translation 11。界面 Dice 0.48，已发生 `GET /api/stats/82b0c180-f42c-42e0-b55b-d66bd80e39e2` 200 原值 0.4782608695652174，符合约 0.4783。点击 translate 回例句，保留精确 translate / Translate 的或条件，最终 22 句 / 22 对。截图：S-20-1-translations.png、S-20-2-translate-return.png。无异常。 |
| S-02 | 通过 | headless、1440 × 900。维基中文词性弹层为“词性体系 jieba（北大标注） · 写作 词/标签，如 语言/n”；`翻译/v` 为 45 次 / 41 句 / 25 篇，`语言/n` 为 116 / 103 / 41。GSD 弹层 UPOS，`{pos=PROPN}` 为 9,736 / 3,033 / 2，`中国/PROPN`、`中国/n` 均为 255 / 217 / 2。截图：S-02-1-jieba.png、S-02-2-upos.png、S-02-3-mapped-pos.png。未见失败请求或产品问题。 |
| S-21 | 通过 | H 实际打开历史，显示最近 5 条及查询、数字、范围、时间。恢复会话后旧“研究”不在其中，先通过界面检索维基中文“研究”545 次，再 H 点该条回填并检索；保存“研究-维基”成功，Ctrl+K 搜索在“保存的查询”组出现，Enter 实际重开后仍 545 次。截图：S-21-1-history.png、S-21-2-saved-query.png、S-21-3-command-saved-query.png、S-21-4-query-reopened.png。会话恢复导致旧历史缺项未报产品缺陷。 |
| S-26 | 通过 | 面包屑语料库段打开真实下拉菜单，内置项均标“（内置）”；选择 UD 英文 EWT 后，子库段打开独立菜单并选“不限子库”，面包屑与检索范围同步为 UD 英文 EWT / 不限子库，未打开命令面板。截图：S-26-1-corpus-menu.png、S-26-2-subcorpus-menu.png、S-26-3-scope-synchronized.png。 |
| S-03 | 通过 | Tatoeba 整库 `{pos=NOUN}` 同步完成 380,100 次 / 210,577 句；平行库第三卡为句对 210,577，按已知限制 3.5，不将方案本条“文档 2”视为产品缺陷。点击到终值 10.617 秒，实际 `POST /api/search` 10.190 秒。每页 50 条，首屏末句 67 的 word 到第 2 页首同句 substitute 顺接；连翻至第 5 页返第 4 页，50 行逐项一致。第 2–5 页网络耗时 90.3 / 90.8 / 52.1 / 39.8 ms，返第 4 页缓存即时，无 500。截图：S-03-1-page1.png、S-03-2-page4-return.png；逐行证据：tmp/browser-test/S03-page2.json 至 S03-page5.json、S03-page4-back.json。 |
| S-04 | 通过 | GSD `{pos=NOUN}` 为 30,732 次 / 4,473 句 / 2 篇，实际首屏请求 265.5 ms；连续翻第 2、3、4 页请求 49.3 / 49.9 / 55.3 ms，界面呈现均小于 1 秒。Tatoeba 中文侧同查询为 42,036 次 / 27,667 句，第三卡按已知限制 3.5 显示句对 27,667。截图：S-04-1-gsd-page4.png、S-04-2-chinese-subcorpus.png。无失败请求。 |
| S-13 | 通过 | 译文含 translate 为 23 次 / 22 句，不含为 61 次 / 57 句，23 + 61 = 84；`translate $` 在译文框正下方显示“第 11 个字符：$ 后应为数字，如 $3 或 $2-5”，定位正确。切至非平行维基中文后无译文条件。字段内错误省略方案中的“译文条件”前缀，见 R06，不计产品缺陷。截图：S-13-1-aligned-include.png、S-13-2-aligned-exclude.png、S-13-3-aligned-syntax-error.png、S-13-4-nonparallel-no-condition.png。 |
| S-24 | 通过 | S-HF 全库语义查询“A teacher explains the meaning of a poem.”显示“50 句 · 按相似度排序”，0.86 至 0.62 非升序，前列为 poem 含义相近句。HF 2021 起同查，实际打开前 3 条上下文为 #540 / #748 / #123，year 为 2021 / 2022 / 2023。第 3 条实际钉住，`POST .../evidence` 200，证据篮 2 → 3。截图：S-24-1-semantic-ranked.png、S-24-2-subcorpus-year.png、S-24-3-semantic-pinned.png。 |
| S-14 | 通过 | 维基“研究”545 次；结果内筛选含“语言”回车后查询框为 `研究 +语言`，12 次 / 9 句 / 7 篇；不含后 `研究 -语言`，533 / 430 / 138；清空回车恢复 `研究` 与 545 / 439 / 141。最终查询框通过主执行者直接目视及截图前 full snapshot 双重核对为“研究”，解析与计数一致。悬浮提示为“作为同句条件重新检索全部结果，回车生效”。截图：S-14-1-include-filter.png、S-14-2-exclude-filter.png、S-14-3-filter-cleared.png。 |
| S-08 | 通过 | GSD“语言”通查开为 32 / 27 / 2，关闭为 0 / 0 / 0，显示“该库为繁体，试试「語言」（32 次）”，点击提示检索后 32 / 27 / 2；“为”开为 1,380 / 1,143 / 2，关为 0。S-繁体通查开时“语言”5 / 5 / 1、“翻译”4 / 4 / 1，无零命中提示。截图：S-08-1-traditional-suggestion.png、S-08-2-uploaded-traditional.png。未见失败请求。 |
| S-05 | 通过 | 首轮 `*` 按左语境请求 17.6656 秒同步给 784,327 次 / 38,360 句 / 1,003 篇。按方案在另一标签提交正常 Tatoeba 2-gram（最低频次 2、前 200）后重做，请求 20.2453 秒返回语料顺序首页，三卡“计算中”及“排序在计数完成后生效”，前行金鸡 / 河 / 是；随后自动完成为 784,327 / 38,360 / 1,003、提示消失并按左语境重排（第二行为田中秀和句 151 BGM）。第 2 页返回再进 50 行逐项一致。截图：S-05-2-current-query.png、S-05-3-parallel-count-state.png、S-05-4-background-complete.png、S-05-5-stable-page2.png；辅助逐行证据 S05-page2*.json。无 500 或错误；S-05-1 为旧结果，不作最终证据。 |
| S-09 | 通过 | 维基英文 the、The 均为 46,463 次 / 22,974 句 / 996 篇；已核实英文双引号精确输入，`"The"` 为 6,801 / 6,560 / 815，`"the"` 为 39,660 / 20,528 / 992。截图：S-09-1-exact-lowercase.png。未见失败请求。 |
| S-25 | 失败 | B03：HF 语义检索后打开首条上下文，再切 S-学习者作文，等待 2.2 秒，顶栏已切新范围并显示未建 41 句、检索禁用，下方仍保留 HF 的 50 条相似句及 #831 / year 2019 上下文，无旧范围标签。未建面板本身正确；C-27 后已补过期分支：索引 1,146 句、当前 1,145 句，显示文档有增删需重建；实际语义查询成功渲染结果表及已过期标签，原 B03 失败仍保留。截图：S-25-1-index-not-built.png、S-25-2-stale-semantic-results.png、S-25-3-stale-index-search-usable.png。 |
| S-10 | 失败 | B04：EWT `{lemma=make}` 为 451 / 439 / 226，make 为 209 / 205 / 134；GSD `{dep=nsubj}` 为 8,383 / 4,302 / 2，计数符合。每行尾仅术语例句、钉住按钮，点行后的上下文也无“依存”入口，无法展开原生依存树，未通过造层绕过。截图：S-10-1-no-dependency-button.png。`POST /api/search` 200，无 error.code / 控制台错误，非 500。 |
| S-15 | 通过 | 维基“翻译”按左语境、右语境、随机、出处排序均保持 60 / 55 / 34，顺序实际改变（左首向您致敬尼加拉瓜、右首霍布斯、随机首富井政章、出处首布雷斯地区圣马丹）。40 字左右等宽、未裁半；整句和整段完整换行，主执行者目视截图确认。实际悬停出处，原生 title 为“布雷斯地区圣马丹 · 句 2”。截图：S-15-1-left-sort.png、S-15-2-right-sort.png、S-15-3-random-sort.png、S-15-4-source-sort-40chars.png、S-15-5-full-sentence.png、S-15-6-full-paragraph.png、S-15-7-source-title-tooltip.png。 |
| S-11 | 通过 | 维基中文输入 `{dep=nsubj}` 未提交即报第 1 字符无依存层；`语言 $` 未提交即报第 4 字符错误并标出。实际提交无依存查询返回预期 `POST /api/search` 422、`INVALID_LAYER`；改“语言”后 148 / 128 / 52，旧错误清除。片段校验因维基中文已被 P-08 建抽样层，按 R07 改用无片段层的维基英文，输入 `[偏误:时态]` 未提交即报第 1 字符无片段标注层。截图：S-11-1-no-dependency.png、S-11-2-span-validation.png、S-11-3-syntax-validation.png、S-11-4-error-cleared.png、S-11-5-no-span-layer-wikiEN.png。 |
| S-12 | 通过 | Tatoeba 中文侧“翻译”84 次 / 79 句，第三卡句对 79 按已知限制 3.5；40 字模式语境仅当前句。首句“因为我想成为翻译。”对应“Because I want to be a translator.”；句 3500、11185 等无对齐项明确显示“无对齐译文”。实际切整句，源句及译文完整、可换行。截图：S-12-2-parallel-kwic.png、S-12-3-whole-sentence.png；S-12-1 为切范围旧结果，不作最终证据。无失败请求。 |
| S-06 | 通过 | Tatoeba 英文侧 `*`（继承按左语境）先后台计算，再三卡“未完成”，固定提示“命中超过 200 万，请缩小范围或加条件”，首屏仍有 50 行。最后 `POST /api/search` 200（requestId 5904.149），counts.complete=false、failed=true、message 为上述提示，无 error.code，属业务结果。只读 performance 确认最后搜索请求距观察时 127,326 ms、无新搜索请求，轮询停止。截图：S-06-3-final-limit-warning.png、S-06-4-polling-stopped.png。无 500 或控制台错误；中间/旧范围截图不作最终证据。 |
| S-16 | 通过 | Tatoeba 中文侧“翻译”首条句 547 实际打开上下文；前 1 句两次、后 1 句一次，指示为 −2 / +1。标题句 547、双语对照、文档 Tatoeba cmn、句序号 547 均正确，未显示码点或内部字段。实际滚动底部，主执行者目视确认钉住按钮完整可见，与任务托盘不重叠。截图：S-16-1-context-expanded.png、S-16-2-context-footer-visible.png。 |
| S-22 | 通过 | UD EWT make 为 209 / 205 / 134，实际开启词性着色并展开“词性颜色”，不同词性彩色下划线及 8 类图例可见。通过界面导入无 POS 的专用 CoNLL-U，S-POS缺失为 1 篇 / 1 句 / 3 词，probe 命中 1 / 1 / 1，词性着色禁用、悬停“当前结果不含词性”。已通过界面删除专用库并确认列表无该名。截图：S-22-1-pos-colors-legend.png、S-22-2-no-pos-disabled.png。无遗留副作用。 |
| S-18 | 通过 | Tatoeba 英文侧 the 为 94,132 次 / 74,803 句；界面提交 XLSX 导出 `#ba1312d5`，任务页由运行中“已处理 0”到完成“94,132 行 100%”。后台导出期间另查 dog 成功为 1,126 次 / 1,100 句，检索可用。实际下载 `tmp/browser-test/downloads-permissions/检索结果-20261107-1438.xlsx`（8,248,954 B），只读流式核验文件头命中 94,132、工作表“检索结果”、12 列、精确 94,132 数据行。截图：S-18-1-export-progress.png、S-18-2-export-completed.png。 |
| X-02 | 通过 | 依据用户最新要求，CSV/XLSX 采用只读脚本核验。界面检索 spreadsheet 并实际下载 CSV 587 B、XLSX 5,486 B；CSV 左语境为 `'=SUM(A1:A2) is how a `，XLSX G4 同值且为字符串，公式 0、超链接 0，表头宋体、无底色。精确文件在 `tmp/browser-test/downloads-perm-owner/检索结果-20261107-1441.csv`、`检索结果-20261107-1442.xlsx`。未进行 Office 可视操作或声称观察安全弹窗。截图：X-02-1-formula-text-result.png。标题规则沿用 R05。 |
| T-09 | 通过 | S-学习者作文默认 15 指标、按 level 分组，5 行词数 essay-01=86、04=83、02=78、05=89、03=97（实际 78–97，见 R08）。STTR、MTLD 均为 —，明确“5 篇文档词数少于 100，不计 STTR 与 MTLD”；TTR、密度、句长、依存距离、Flesch 均有值。level 共 1 组、5 篇：TTR 0.70±0.04、密度 0.56±0.05、句长 10.58±0.95、依存 2.59±0.10、Flesch 69.50±3.08，TTR 箱线图存在。截图：T-09-1-text-metrics.png、T-09-2-level-summary-boxplot.png。 |
| T-02 | 通过 | 默认维基英文频次前 50，首 5 项 the 46,463、of 22,382、and 20,038、in 19,039、a 13,905，无独立 The。实际横向滚动后点 the 回例句，精确查询涵盖 the / The / THE，为 46,463 / 22,974 / 996。回统计勾区分大小写重算，首 5 项 the 39,660、of 22,344、and 19,999、in 16,286、to 13,077，结果头标“区分大小写”。截图：T-02-1-folded-frequency.png、T-02-2-back-to-concordance.png、T-02-3-case-sensitive.png。无失败请求。 |
| T-06 | 通过 | 关键词目标维基中文、参照 UD 中文 GSD，未计算即显示“目标为简体、参照为繁体：同一个词的简繁字形会被算作不同的词，关键词前列会是简繁差异。请选用同一字形的参照。”截图：T-06-1-script-warning.png。无失败请求。 |
| T-04 | 通过 | 维基中文“翻译”±5 默认四指标，节点 60 次、25 项；前三奥德赛 logDice 10.61、英文 10.55、爱因斯坦 10.52。加 MI3、双向 ΔP、z 后列出现，实际悬停显示 `MI3=log₂(O³/E)`、条件概率差及 `z=(O−E)/√E`。奥德赛右侧回跳最终 1 / 1 / 1，左侧 2 / 1 / 1，1 + 2 = 总共现 3，按 R09 更正原方案；搜索 200、counts.complete=true。网络图图例“距离 / 线宽 = logDice”、标签在圆内，条形标签无裁切。截图：T-04-1-default-collocates.png、T-04-2-extra-metrics.png、T-04-3-return-to-kwic.png、T-04-4-bars.png、T-04-5-network.png。公式由后续实际悬停核验，T-04-6 不作公式截图。 |
| T-15 | 通过 | T-04 扩展结果实际导出 CSV/XLSX，完成通知带下载；文件在 `tmp/browser-test/downloads-permissions/统计-搭配-20261107-1501.csv`（2,817 B）及同名 XLSX（7,568 B），参数含节点翻译、±5、logDice、最低 3、前 200、区分大小写否，来源及 CC BY-SA 4.0 齐全；25 行数据，合理小数无长浮点，XLSX 表头宋体、无底色。方法说明实际打开附录，含 3.1 搭配。深色下下载 SVG（10,347 B）、PNG（104,091 B），均在真实 headless 浏览器新标签打开；SVG 无 parsererror、白底深字，PNG 完整。已恢复浅色。截图：T-15-1-method-appendix.png、T-15-2-dark-export-source.png、T-15-3-svg-in-browser.png、T-15-4-png-in-browser.png。Office 只读结构核验。 |
| T-12 | 通过 | 初始 wiki 为 25 次 / 每百万 31.27、ewt 为 1 / 4.35，差异 LL 7.15、Log Ratio 2.84。实际添加 8 次至 10 项后添加禁用，再删回 2 项后两项删除均禁用。两项改为 HF、translator / student、year / Spearman，显示 2018–2023 六年图表；保留标签 wiki、ewt 的两行分别 ρ=0.01、p=0.739、n=1,136 与 ρ=−0.03、p=0.340、n=1,136。截图：T-12-1-two-corpus-comparison.png、T-12-2-ten-item-limit.png、T-12-3-spearman-year.png。各步实际界面完成，无异常。 |
| T-10 | 通过 | NGSL 1.2 整体四行词次 / 覆盖率为 394,985 / 60.26%、47,994 / 7.32%、21,602 / 3.30%、表外 190,896 / 29.12%；表外首项 's 4,772。按每篇实际重算共 1,000 行，各有四等级覆盖率，首篇 Aily 101 词、69.31 / 2.97 / 3.96 / 23.76%。截图：T-10-1-overall-ngsl.png、T-10-3-per-document-final.png；T-10-2 仅排队状态，不作最终证据。无失败请求，后台标签激活后正常完成，不将节流算产品问题。 |
| T-16 | 通过 | 界面以 S-HF、translator / student 两行查询、附文本指标导出 CSV；`tmp/browser-test/downloads/整洁数据-20261107-1458.zip` 为 57,326 B，内 tidy_data.csv 有 1,136 唯一 document_id、25 列，与 codebook 25 条字段逐一匹配且说明非空。含元数据、tokens / sentences、两查询 hits / pm、9 文本指标；q1 总和 120、q2 118，与 T-12 年度总和一致，各 pm=hits×10⁶/tokens，核算最大误差 0。11 行实际提交提示“最多 10 个查询式”、未建导出；已恢复两行。截图：T-16-1-export-submitted.png、T-16-2-query-limit.png。 |
| X-03 | 通过 | 同参数 XLSX 已经界面下载，`tmp/browser-test/downloads/整洁数据-20261107-1504.xlsx`（153,892 B）含 data / codebook，data 为 1,136 数据行、25 列。第 5–9 行 meta_note 与 CSV 五值逐一一致，均以单引号起始、字符串类型、无超链接；全工作簿公式 0、超链接 0、非空单元格背景填充 0。按用户最新要求只读结构核验，不做 Office 桌面。截图：X-03-1-xlsx-export-submitted.png。 |
| T-03 | 通过 | EWT 文档部分为 858，the 10,056、range 742（86.48%），界面 DP 0.17；实际界面下载 CSV 中 DP 0.1695、DPnorm 0.1695、Juilland D 0.9759，均 4 位小数。改等分后头为“10 部分（等分 10 段）”，改 split 后为“2 部分（按 split）”。文件 `tmp/browser-test/downloads-imports/统计-频次-20261107-1503.csv`（15,975 B）。截图：T-03-2-document-parts-final.png、T-03-3-ten-parts.png、T-03-4-split-parts.png；T-03-1 仅队列状态，不作最终证据。无产品问题。 |
| T-18 | 通过 | HF translator 按 genre 分解 subtitles 28、fiction 25、legal 24、news 23、academic 20，总和 120。实际点 academic 回检索为 20 / 20 / 20，显示“临时筛选 · 体裁 = academic”；清除后实际恢复 120 次。截图：T-18-1-genre-breakdown.png、T-18-2-academic-return.png、T-18-3-full-search-total.png。 |
| T-05 | 通过 | 正向 LL 前 5 为 of 844.23、the 704.24、in 668.50、his 437.34、by 361.03，含 LR 95% 区间、%DIFF、Odds Ratio、Bonferroni。实际悬停核对 %DIFF、OR、Bonferroni 公式；负向 200 行逐项目标 pm 小于参照 pm，首 I 的 LL 8,645.18。指定 translation / the 只 2 行（25 对 1、46,463 对 10,056），方向及最低频次禁用。同库参照在菜单排除，目标改为已有参照时自动清空、提交提示“请选择参照”，按 R10 视为有效前置防护。截图：T-05-1-positive-keywords.png、T-05-3-bonferroni-tooltip.png、T-05-4-negative-keywords.png、T-05-5-specified-words.png、T-05-6-same-target-excluded.png、T-05-8-reference-cleared-validation.png。无产品缺陷。 |
| T-11 | 通过 | 上传后提示“已添加词表 自编中文词表（7 词，1 个重复词只保留第一个等级）”；GBK 整体一级 13 / 3 / 6.74%、二级 1 / 1 / 0.52%、三级 7 / 3 / 3.63%、表外 172 / 123 / 89.12%（词次 / 词种 / 覆盖率）。一级实际回例句含文化、翻译、语言，为 13 / 7 / 1，翻译归一级。用于维基英文为预期 `POST /api/stats/vocab_profile` 422、`VALIDATION_ERROR`、“词表语言与语料不一致”。确认删除后 `DELETE /api/vocab-lists/04a66280-a60f-43f4-9f7b-c3c3e9125c36` 204，列表无该词表；P08 两词表及 NGSL 保留。截图：T-11-1-vocabulary-uploaded.png、T-11-2-custom-levels.png、T-11-3-language-mismatch.png、T-11-4-first-level-includes-translation.png、T-11-5-delete-confirm.png、T-11-6-custom-vocabulary-removed.png。已恢复，无 500。 |
| T-13 | 通过 | UD EWT make / VERB 按主语、宾语等分栏；宾语 change 共现 15 / logDice 10.44、it 23 / 9.72、decision 8 / 9.64。实际点 decision 回检索，查询包含 decision 的 lemma / obj 与 made、make、making 同句条件，最终 8 次 / 8 句 / 7 篇（非过渡空值）。维基中文“语言”报 `NO_DEPENDENCIES`、“该语料没有依存标注，请先在标注页建依存层”，附建层链接。截图：T-13-1-word-sketch.png、T-13-2-decision-examples.png、T-13-3-no-dependency.png。 |
| T-14 | 通过 | big / large 共 31 项，各关系为偏 big / 共同 / 偏 large 三栏；共同 subject 的 it 原始差 5.9125371587−5.9218491923=−0.0093120335，界面 −0.01，符合 logDice 差。将 B 改为 big 实际点击计算，提示“与词元 A 相同”。截图：T-14-1-synonym-comparison.png、T-14-2-identical-lemma.png。 |
| T-07 | 失败 | B05、B06。n-gram 含文化为 63 项、每行含文化，SVG/PNG 禁用且悬停说明正确；分布空查询实际提交提示“请输入查询式”。翻译 / 文档位置 / 10 区间结果总 60 命中，但图卡过窄、数值标签重叠（B05）；点第 2 柱选中 10–20% 表行后回例句，本应 7 次却返回全库 60 / 55 / 34（B06）。柱先选表行的交互见 R11。截图：T-07-1-ngram-includes-culture.png、T-07-2-query-required.png、T-07-3-position-distribution.png、T-07-6-bar-selects-table-row.png、T-07-7-selected-row-examples.png。 |
| T-08 | 通过 | 非平行维基中文“译法”页签禁用，实际悬停“仅平行语料”。S-TMX 中英“翻译”、默认最低 2，头为译文 en、命中句 7、有对齐 7；六列齐全，共 8 项，translation 共现 3 / 42.86% / 目标 4 / Dice 0.55，translate 共现 2 / 28.57% / 目标 2 / Dice 0.44。translated 在匹配句仅 1 次，被默认最低 2 排除，见 R12，不报产品缺陷。截图：T-08-1-parallel-only.png、T-08-2-tmx-translations.png。 |
| T-17 | 通过 | 打开文本指标历史后自动进入文本指标页、范围 S-学习者作文正确。确认删除本轮右一词结果 `82da0718`，DELETE 204，重开历史由 38 → 37 且该行消失。搭配中 Ctrl+K 切维基中文再切分布，表单和面包屑范围一致；当前页新算“语言”分布为 148 次，结果显示后继续观察 3.5 秒，无统计完成通知遮挡或运行中提示。截图：T-17-1-open-history-result.png、T-17-2-history-deleted.png、T-17-3-shared-scope.png、T-17-4-completed-no-overlay-toast.png。仅删除本轮 sol 输出。 |
| SP-01 | 通过 | Tatoeba 中文侧“翻译”84 命中，实际抽 20 条、seed 42，新建翻译词性标签动词 / 名词；默认层名含简繁展开，按方案填写“抽样·翻译”。创建层 `aeebcdb2-67c3-44a4-b02a-1fa09511b948`，提示“已抽取 20 条（共 84 条命中，seed 42）”，已编码 0 / 20、20 项全未编码。截图：SP-01-1-sample-parameters.png、SP-01-2-sample-created.png。 |
| N-02 | 通过 | 预标差异仅句 1，预标 / 人工对照中 Hometown 拒绝为 —，1 处拒绝；同一词修改后又拒绝，最终 0 修改正确。实际点编辑回句 1；统计为 token 494、已确认 13、已修改 0、已拒绝 1；有效 NOUN 104 回例句为 104 次 / 38 句 / 5 篇，已切 N-01 层。截图：N-02-1-preannotation-diff.png、N-02-2-annotation-statistics.png。步骤主体通过；文档进度 0/0 的探索问题另记 B07。 |
| N-05 | 通过 | 单人片段层 HF 2021 起子库 554 篇，估算 560 句 / 56 次；全部 HF 1,136 篇为 1,146 句 / 115 次，均按每批 10 句向上取整，显示“将把所选句子发送到 api.deepseek.com”。实际取消，未提交 HF 层或模型任务。改 S-学习者作文 / 子库，提示“该语料库没有子库”，随后取消。截图：N-05-1-subcorpus-estimate.png、N-05-2-all-documents-estimate.png、N-05-3-no-subcorpus.png。无产品缺陷。 |
| SP-02 | 通过 | 空标签 Enter 提示“先选择标签（数字键）”；实际数字键 + Enter 编码 10 条：动词 6、名词 4，X 拒绝 1，J / K 实际前后移动。汇总总命中 84 / 已编码 10 / 拒绝 1 / seed 42；动词 60.0%、Wilson 31.3–83.2%、约 50；名词 40.0%、16.8–68.7%、约 34，分母与估计正确。截图：SP-02-1-label-required.png、SP-02-2-coded-summary.png。 |
| SP-05 | 失败 | B09：方法附录有语料及子库、查询式、n=20 / seed=42 / 总命中 84、编码结果与 Wilson 1927，但缺 79 句、1 篇及单独检索节；全文 DOM 不含 79，不满足检索三项计数。截图：SP-05-1-sampling-appendix.png。方法附录请求 200，无 error.code / 控制台异常，非 500。 |
| SP-03 | 通过 | 同查询、20 条、seed 42、已有翻译词性标签集，实际建立复核层 `ea7e02f2-b747-4ecc-ad2a-46282e89f38f`；逐条 J 读取前 5 项均为 Tatoeba cmn 句 42996 / 13925 / 3500 / 20746 / 19559，与主层完全一致。截图：SP-03-1-reproduced-fifth-item.png。 |
| SP-04 | 通过 | 抽样条目仅确认 / 拒绝 / 前后移动，无删除条目。实际预标为预期 `POST /api/layers/aeeb.../preannotate` 422、`SAMPLE_LAYER`、“抽样层不能预标注”，未创建模型任务或外传。界面导出 `tmp/browser-test/downloads/抽样___翻译-分布-20261107-1524.xlsx`（7,015 B），偏误分布 / 片段两表，片段恰 10 数据行、6 动词 4 名词，未编码 9 和拒绝 1 均不出现；宋体标题，无填充、公式。截图：SP-04-1-prelabel-forbidden.png、SP-04-2-xlsx-export.png。原始标注句序按契约为 0 基，不套用检索导出 1 基要求。 |
| N-06 | 失败 | B10（严重）：边界按钮保留焦点，Enter / Shift+Enter 触发按钮默认动作，意外缩短人工片段且没有确认；详细稳定复现及 200 PATCH 证据见问题表。已通过实际界面把片段恢复至预定 148–158 并显式点击确认，未改其他模型建议；其余校对步骤和后续依赖继续执行。截图：N-06-13-arrow-focus-before-enter.png、N-06-14-enter-shrinks-again.png、N-06-15-span-restored-explicit-confirm.png。 |
| N-03 | 通过 | S-GBK 依存层 ud-deprel 62、全部 11 句，预标 `#7166c73f` 执行时 DOM 显示“预标中 0 / 11 句”，完成为 Stanza 1.15.0 zh、236 词；11 句不足一处理块，未捕获块内中间值，不将快速完成判失败。词下显示 PRON / PART / VERB / NOUN。实际把“我”中心词从“4·学习体会”改为“3·翻译”，状态已修改、模型建议·人工修改，关系弧改接，三角箭头与关系标签存在。长句连续 →40 次至句尾，scrollLeft=1712、clientWidth=530、总宽 2242，所选句末词仍在编辑区内。截图：N-03-2-dependency-ready.png、N-03-3-head-modified.png、N-03-4-arrow-key-scroll-end.png；N-03-1 为初始化 0/0，不用作句单位证据。 |
| K-01 | 通过 | 导入卡一次实际点选 4 文件（非拖拽），提示已提交 4 个文件，初始排队后均可检索。PDF 标题 Corpus Methods in Translation Studies、3 片段 / 3 页、作者 Test Author；DOCX 标题语料库翻译学概论、2 片段；两 Markdown 分别学习者偏误标注规范（2 片段）、语料库翻译学综述（中篇）（105 片段）。PDF 正文保留标题与 Introduction 换行，主执行者目视核验。截图：K-01-1-four-imports-submitted.png、K-01-2-pdf-details.png、K-01-3-four-documents-ready.png。瞬时解析 / 分段 / 向量化帧未逐阶段捕获，未声称逐帧见到。 |
| N-04 | 通过 | 维基中文 / jieba 57 / 指定文档下拉首列 50 / 1,003，真实到底滚动两次为 100、150；远程搜索并选择长孙虑、镇龙站（地铁）提交“N04指定两文档词性”。层 `8ec23c73-d877-4570-a7ed-3db71b854023`，预标 `#4a673889` 完成后文档菜单仅两项，分别 0 / 13、0 / 38，共 51 句。截图：N-04-1-first50-documents.png、N-04-2-loaded100.png、N-04-3-loaded150.png、N-04-4-remote-title-search.png、N-04-5-two-documents-submitted.png、N-04-7-ready-exact-two-documents.png；N-04-6 仅排队空菜单，不作最终证据。无产品缺陷。 |
| N-13 | 通过 | 仅删除 N-04 本轮临时层，确认框“删除标注层「N04指定两文档词性」？”、“该层的全部标注一并删除。”；实际删除后提示“已删除标注层”，列表移除。截图：N-13-1-delete-layer-confirm.png、N-13-2-layer-deleted.png。临时层已清理，未动偏误-双人或他人层。 |
| N-07 | 通过 | owner 建偏误-双人（仅 editor、annotator，不预标），再勾预标时实际显示独立性警示并取消。两人真实拖选前 3 句、各整句确认 3 / 8，故意 mountain 不同标签；补 editor 独有 city 后，annotator 刷新仍只见自身 small、无 city，editor 的对方视图也为空。最终 agreement 200 与界面一致：κ −0.14、α −0.08、矩阵 n=4；按标签含用词 κ−0.33 / n4、未标注 κ0 / n1、主谓一致 κ0 / n1，未标注悬停说明明确。分歧均句内高亮，实际分别采用 mountain、city 后已仲裁，未仲裁筛选下消失、关闭筛选可见两标签。viewer 独立会话只读、确认与标签禁用。截图：N-07-1-multi-layer-created.png、N-07-2-prelabel-independence-warning.png、N-07-15-unmarked-agreement-row.png、N-07-17-annotator-cannot-see-city.png、N-07-18-viewer-readonly.png、N-07-20-final-both-adjudicated.png、N-07-21-editor-other-view-final.png。层保留供 N-12，无新增产品缺陷。 |
| S-23 | 通过 | 依赖补验：实际人工拖选 go 建已确认时态 198–200（span 1800），并确认模型 work 时态 427–431。时态统计 total=4、confirmed=2、modified=0；`[时态]` 最终 2 次 / 2 句 / 2 篇，与已确认 2 一致。go 为 1 / 1 / 1，KWIC 嵌套 mark.kspan 的 title 与标签为时态；本页恰 1 个 `POST /api/search/span-marks` 200（38984.4143），响应 span1800 / 198–200 / 时态 / confirmed。截图：S-23-1-manual-tense-test-preparation.png、S-23-2-confirmed-tense-count.png、S-23-3-go-highlight-one-request.png。 |
| N-14 | 通过 | 9 层时收起层列表到当前“偏误”，实际 J 三次切至句 4，编辑器与右上当前标注始终在视口内；之后展开恢复。截图：N-14-1-layer-collapsed-three-jumps.png。 |
| N-12 | 通过 | 正常界面下载并只读核验 CoNLL-U（21,041 B、41 个 sent_id / 494 token、10 字段、无 UUID，人工和拒绝标注符合）、BRAT ZIP（2,995 B，5 篇各 txt / ann 与 annotation.conf）及 XLSX（6,484 B）。BRAT 5 条均与 txt 码点一致：go 198–200 / 时态、make us more knowledge 87–109 / 偏误、many informations 142–159 / 搭配、nformation 148–158 / 用词、work 427–431 / 时态；无未校对建议或已拒绝 help。XLSX“偏误分布”“片段”两表、14 标签加合计总 5 / 时态 2、明细 5 行与 BRAT 一致，标题全宋体、全部无底色。多人菜单含另附原始标注项。文件均在 tmp/browser-test/downloads-permissions。截图：N-12-2-multi-json-menu-after-adjudication.png、N-12-3-single-span-export-scope.png、N-12-4-export-tasks-complete.png。表名为方案简称的同义具体名称，不报缺陷；不做 Office 视觉操作。 |
| K-07 | 通过 | 实际创建 explicitation、从证据篮加入 1 条例句并导出；任务页点击已完成 TBX / CSV / XLSX 下载，`tmp/browser-test/downloads/术语表-20261107-1546.{tbx,csv,xlsx}` 分别 1,550 / 425 / 5,369 B。只读解析 3 术语，explicitation 的译名显化、语言 zh、来源手工、例句 1 与界面一致；TBX 中文 definition 位于 zh langSec，en 下无中文 definition；XLSX 4 行 / 9 列，9 表头宋体、无填充。截图：K-07-1-term-example.png、K-07-2-term-exports-submitted.png。 |
| K-12 | 通过 | 真实文件控件上传解压上限样本 553.4 KB，`POST /api/projects/e6b68bfd.../kb/documents` 200，文档 `210d8eb4` / 任务 `7d33fb0d`；随后列表“解析失败”，原文“source.docx 文件解压后过大（超过 500 MB）”。再选择 CSV，提示“不支持的文件格式：hf-export-nli.csv”，未发第 2 次上传。截图：K-12-2-csv-unsupported.png、K-12-3-unpack-failed-final.png；K-12-1 仅排队，不作最终证据。预期拒绝正常，无 500。 |
| N-11 | 通过 | 本地预标 `#25074341` 于 15:46:58 完成（约 31 分钟），层 `0ad30259-8941-45ce-a5a3-cff104baec4c` 有 11,990 建议。目标下拉共 11,998 句，实际查 5001 并选中；library 匹配 1,000 句，真实滚动加载至目标 1214，超过首批 50。首源选目标 1、5001，离开输入焦点 Enter 后确认，当前显示 1:2；第 2 源实际移除选择再 Enter，已完成、未对齐。截图：N-11-4-target-5001.png、N-11-5-target-library.png、N-11-6-one-to-two-confirmed.png、N-11-7-unaligned-confirmed.png。对齐 POST/PATCH 均 200；初次清空未生效的默认值已通过界面纠正，以最终未对齐为准。 |
| K-02 | 通过 | “什么是显化”混合 / 向量 / 关键词均 200，高低相关度标签取代原始分数；向量 8 条为 1 高 / 7 低，实际展开低相关项。按 R13 不强求固定 top 8 混合来源，补查询“译文比原文更明确”返回 DOCX 首位。实际点结果打开文档定位 chunk914，自动加载 100 chunks，目标 class=chunk on、top329 / bottom633 在视口内，#79 与正文对应。截图：K-02-1-hybrid-search.png、K-02-2-vector-search.png、K-02-3-keyword-search.png、K-02-4-low-results-expanded.png、K-02-5-document-location.png、K-02-6-docx-phrase-search.png。功能通过，摘要转义细节另记 B11。 |
| N-08 | 通过 | 偏误关系层 essay-02，实际点已确认父 many informations → R → 子 nformation → 更正并确认，再反向建成因并确认。两条相反方向弧控制高度 33.1 / 6.5，标签纵向错开、不重叠，来源人工、已确认；离页重开仍 2 条、100%、0 待确认。截图：N-08-1-relation-layer-estimate.png、N-08-2-first-relation-created.png、N-08-3-two-nested-relation-arcs.png、N-08-4-saved-relations-reopened.png。方案允许仅新建，可选预标 `#110202e8` 后续已 succeeded，written=1 / total=3、failed_sentences=0；完成后界面 2 / 3（67%），新增 1 条虚线模型成因，原 2 条实线人工已确认仍保留，三层弧和标签错开无重叠（N-08-5-preannotation-done-relations.png）。 |
| N-09 | 阻塞 | E03，部分完成：真实依存层 N09三文档依存重试（b9de6946...），维基中文 / ud-deprel / 3 篇 / 122 句，新建与运行已测。有限尝试中实际观察 `#b8b2c205` 运行 8 / 122 句、7% 后立即截图并点该任务取消，`POST /api/jobs/b8b2c205-b9c9-4646-96a8-2e5a4e5c21c8/cancel` 409，到达时已完成；响应体与 error.code 未捕获。最终 ready、122 句，无失败或重试入口，取消→失败→重试分支未覆盖，不伪称通过。截图：N-09-6-dependency-running.png、N-09-8-dependency-completed-409.png、N-09-9-dependency-ready-no-retry.png、N-09-10-blocked-final-ready-layer.png。误建 POS 层已界面删除且不计覆盖；无残留运行或取消副作用。 |
| K-09 | 失败 | B12：新建“翻译例句观察”，3 段正文自动由未保存到已保存；在第 2 段前插 Tatoeba 547，位置正确、引用 1。再从 8 条证据篮单次加入该笔记，引用变 9，正文立即仍 1 块；刷新后 9 块，547 重复两次，未按每条只插一次去重。预览命中加粗、对齐译文、出处正常。截图：K-09-1-inline-evidence-autosaved.png、K-09-2-basket-appended.png、K-09-3-preview-duplicate-reference.png、K-09-4-reloaded-duplicate.png。请求均 200，无 console / error.code。 |
| E-05 | 通过 | 证据篮含命中及逗号频次行，实际生成附录并切 GB/T → APA，参考文献格式变化；语料、子库规模、许可版本、jieba / Stanza / CWB 3.5.0 / dev、Tatoeba 84 / 79 / 1 与维基 60 / 55 / 34、频次参数公式及文献齐全。复制提示“已复制 Markdown”；实际下载 `tmp/browser-test/downloads/方法附录-20261107-1555.docx`（38,956 B），只读 XML 核验宋体 eastAsia、无 shd，来源许可与 APA 内容齐全。实际新建笔记默认“方法附录”，保存成功。截图：E-05-1-gbt-method-appendix.png、E-05-2-apa-copied.png、E-05-3-saved-note.png。按 headless 调整不打开记事本或 Word，复制以界面提示核验。 |
| K-11 | 通过 | 专用 K11 自动保存节流笔记，真实键盘约 34.6 秒、12 段、每隔约 3 秒输入；UTC 07:52:19.001–07:52:53.467，最后自动 PATCH 07:52:54.229 为 200。连续输入期间仅复用 1 个重建任务 `8f3f152d`，worker 07:53:24.105 开始、24.206 完成，距最后保存 29.876 秒，符合 30 秒防抖误差；空笔记准备任务早已完成，不计本段输入。截图：K-11-1-continuous-input.png、K-11-3-rebuild-final.png；输入时刻 tmp/browser-test/k11-input-times.json。 |
| E-01 | 通过 | owner 实际钉首 3 条，篮 3→6；检查器句 3500 再钉至 7，频次逗号 7,509 钉至 8；统计行显示可读内容。owner 另钉句 11185，editor 用旧页面实际提交同条，200、existing=true，提示“已在证据篮中”，未重复新增。当前共享页面的“已钉”点击会移出，应按 R14 用旧 DOM 竞争覆盖判重。截图：E-01-1-three-pinned.png、E-01-2-inspector-pinned.png、E-01-3-readable-statistic.png、E-01-4-owner-race-preparation.png、E-01-5-editor-duplicate-stale.png。 |
| E-02 | 通过 | editor 实际新钉句 8102、9842，owner 清空前篮共 11；owner 用真实键盘聚焦越界清空按钮、Enter 两次确认，`DELETE .../evidence?mine=true` 200 后为 3。editor 刷新稳定核验 8102 / 9842 仍已钉，owner 的 547 / 11185 变未钉，另 1 条他人维基证据保留，未误清他人。截图：E-02-1-editor-two-pins.png、E-02-2-owner-cleared-own.png、E-02-5-editor-preserved-stable.png。隔离逻辑通过，清空按钮越界另记 B13；E-02-4 为加载初始，不作最终证据。 |
| K-10 | 通过 | owner / editor 独立 headless 同开“翻译例句观察”。B 追加“B 的修改”，PATCH 200、已保存；A 不刷新追加“A 的修改”，`PATCH /api/kb/documents/d98e3132...` 409、`NOTE_CONFLICT`，中文提示笔记已被更新、请载入最新版本合并，后续无重试 PATCH。实际复制提示已复制本地内容；载入最新后 B 保留，本地只读 textarea 保留 A 并提示可合并。截图：K-10-1-editor-saved.png、K-10-2-owner-conflict.png、K-10-3-latest-loaded-local-preserved.png。已恢复正常最新版本、未覆盖 B。 |
| AS-02 | 通过 | 写操作先出确认卡，执行前篮 3 不变；实际执行后卡片已执行，2 个工具结果为新增 / 已有，篮 3→4，与 1 条唯一新增一致。第三条确认实际点取消后已取消，该会话胶囊仍为 4，取消未写入；其他标签并发钉证据不混入本次瞬间计数。方案固定 +2 依 R15 更正。截图：AS-02-1-confirm-before-write.png、AS-02-2-executed.png、AS-02-3-cancelled.png。 |
| K-03 | 通过 | 实际界面添加公网 Wikipedia URL，提示已提交，最终 Corpus linguistics - Wikipedia、54 片段、可检索。依次添加 127.0.0.1:8088、localhost、10.0.0.1、169.254.169.254/latest/meta-data，真实 `POST .../kb/documents` 均 422、`INVALID_URL`、“只能导入公网地址”，未建私网文献。FTP 实际点添加即提示须以 http:// 或 https:// 开头，无导入请求。截图：K-03-2-loopback-rejected.png、K-03-3-localhost-rejected.png、K-03-4-private-address-rejected.png、K-03-6-ftp-scheme-rejected.png、K-03-7-public-web-ready.png、K-03-8-public-web-detail.png、K-03-9-metadata-address-confirmed.png。首次元数据点击被 pending 抑制不计覆盖，已补真实请求；无外网阻塞或产品缺陷。 |
| AS-12 | 通过 | 在已用工具对话实际点“工具 53”，9 组中文分类数量 10 / 7 / 6 / 7 / 7 / 6 / 7 / 1 / 2，总 53；展开可见“新建子库 需确认”，组头语料已用 2、统计已用 1、证据已用 1。Ctrl+K 实际打开后助手工具仅一项“展开全部 53 个工具”，Esc 恢复。截图：AS-12-1-grouped-tools.png、AS-12-2-command-panel-collapsed-tools.png。 |
| K-08 | 通过 | 新建规范空名称时创建禁用、未生成未命名记录；填偏误标注规范 v1、关联 learner-errors 14 实际创建。打开学习者偏误标注规范文献、设为规范并确认后提示已设为规范，文献 9→8、规范 3→4。新建片段层表单中两规范均可选，实际选转换后的规范再取消，未建层或模型任务；两份 P08 规范保留。截图：K-08-1-empty-name-disabled.png、K-08-2-guideline-created.png、K-08-3-convert-confirm.png、K-08-4-document-converted.png、K-08-5-both-guidelines-selectable.png、K-08-6-converted-guideline-selected.png。无产品缺陷。 |
| AS-03 | 通过 | GSD 会话只读获取第 1 句 40 token，实际展开思考链后依存树组件渲染；无写操作确认，标注层仍 11、无新 GSD 层。截图：AS-03-1-dependency-tree.png、AS-03-2-no-new-layer.png；初始链折叠的 missing-dependency-card 中间图不作缺陷证据。 |
| AS-11 | 通过 | AS-01 回答实际保存为新笔记、直接成功，默认沿用会话标题，按 R16 更正“助手回答”固定预期。再插入翻译例句观察成功；界面重开后 B 的修改仍在，正文 1,728 字，10 行图表转 Markdown 表首奥德赛 10.61；新笔记 618 字含同表。截图：AS-11-1-saved-note.png、AS-11-2-appended-note.png、AS-11-3-note-retained-chart-table.png、AS-11-4-new-note-chart-table.png。 |
| H-01 | 通过 | 实际点击帮助六目录，内容均可见；示例按钮“检索语言”（提示在检索页打开）在维基中文实际检索语言为 148 / 128 / 52，回帮助复制提示已复制。参考文献 GB/T → APA 实际切换作者、年份、文献类型及 DOI 格式，后恢复 GB/T。截图：H-01-1-help-example-query.png、H-01-2-help-apa-references.png。 |
| H-02 | 通过 | 统计页反馈空提交禁用、0 / 2000；实际提交“浏览器测试反馈：统计页”，`POST /api/feedback` 200、提示已收到，供 M-04 后续处理。截图：H-02-1-empty-feedback.png、H-02-2-feedback-received.png。 |
| H-03 | 通过 | Ctrl+K 搜 UD 英文回车，面包屑及统计范围同步为 UD 英文 EWT；空命令面板含页面 / 项目 / 语料库 / 子库 / 保存查询 / 助手工具，工具收为展开全部 53 项。先聚焦打开按钮再 Ctrl+K / Esc，等 400 ms，焦点回同一已连接 BUTTON。截图：H-03-1-ud-scope-synced.png、H-03-2-command-groups.png。 |
| AS-06 | 通过 | 新会话长问题发送约 3 秒后真实停止，显示已停止、2 次工具调用；正文空时仅重新生成，无复制 / 保存按钮。实际重新生成后替换原回答并自然完成，4 个工具引用，仍 2 条消息、无重复用户提问。截图：AS-06-1-stopped-empty.png、AS-06-2-regenerated-single-question.png。 |
| AS-07 | 通过 | Markdown 表格正常渲染为 DOM table，五库文档 / 句数为维基中文 1,003 / 38,360、Tatoeba 2 / 266,098、维基英文 1,000 / 37,383、EWT 858 / 14,545、GSD 2 / 4,497，均与基线一致。截图：AS-07-1-markdown-table.png。 |
| H-04 | 通过 | ? 实际打开快捷键浮层、Esc 关闭；检索页 / 后焦点为 input#q，data-slash=true。深色刷新后 data-theme=dark、body rgb(15,18,24)，截图无白底，之后已恢复浅色。截图：H-04-1-shortcuts-popover.png、H-04-2-dark-after-refresh.png、H-04-3-slash-query-focus.png。 |
| H-05 | 通过 | outsider 独立 headless 登录后打开 /help，独立帮助页有项目列表，无“检索语言 / 在检索页打开”示例按钮，复制可用。截图：H-05-1-standalone-help.png。 |
| U-04 | 通过 | 1280 × 800 实际检索点行，检查器为覆盖面板；再开助手，顶栏次要按钮收起、范围截断，标题横排，执行者目视两图确认。截图：U-04-1-inspector-overlay.png、U-04-2-assistant-responsive.png。已关闭助手、恢复 1440 × 900。 |
| AS-04 | 失败 | B14：已读取近义词流程、执行对比能力，按 R17 不强制 Word Sketch。正式近义词结果 31 行，助手 SketchDiff 卡仅 29 项 / 29 DOM 行且无部分展示说明，缺 conj-large、pp:than-US 两项；已显示 29 行的频数和两位 diff 均与工具一致。截图：AS-04-1-skill-and-comparison.png、AS-04-2-inconsistent-sketch.png。链内两次 openui-lang 未找到工具原文亦可见，不另分问题。 |
| K-04 | 通过 | 合成 36k 文献实际确认“生成摘要？”及发送至 api.deepseek.com；首任务 `082b16f5` 在 1 / 4 外部 `MODEL_ERROR`（返回格式不正确），任务接口 200、非本地 500。按有限规则仅界面重试一次 `6c3a678f` 完成，摘要正文正常渲染、“按 3 段摘要”“模型生成”标签齐全。再次点重新生成确认框正确、随后取消，未提交第 3 任务。截图：K-04-1-summary-send-confirm.png、K-04-3-first-summary-model-error.png、K-04-4-one-retry-submitted.png、K-04-5-summary-rendered.png、K-04-6-regenerate-confirm.png、K-04-7-final-summary.png。初次外发审批经全文合成样本和授权证据补审通过，无遗留阻塞，不计产品缺陷。 |
| K-06 | 通过 | 文献抽取界面显示对话模型及发送说明，任务 `fa82c4a1` 完成 50 草稿 / 跳过 0，正式任务结果 segments=3、candidates=50，耗时 1 分 7 秒；完成 toast 未捕获，不冒称见到 3 段提示。实际确认“翻译共性假设”为已确认。S-TMX 词性模式候选 100 返回“范围内没有出现 2 次及以上的词性模式组合”，按 R18 补一次 S-HF：`139d2b95` 新增 12 / 跳过 0，来源语料、例句 1；original letter 有 HF #11 例句，实际确认成功。原 P08 术语保留，总数 3→53→65。截图：K-06-1-literature-model-notice.png、K-06-4-corpus-extraction-result.png、K-06-5-draft-confirmed.png、K-06-6-hf-pos-pattern-result.png、K-06-7-corpus-example-detail.png、K-06-8-corpus-draft-confirmed.png、K-06-9-literature-task-completed.png。 |
| AS-08 | 失败 | B15：首轮 3 标签在 6.293 秒内实际发送，前两运行，第三 `POST /agent/sessions/b1b259f0.../messages` 429、`TOO_MANY_RUNS`、中文说明已有 2 对话；第三页面却空正文、输入清空、无错误提示，多分钟仍空。补测首会话 stop 204 后第三重发 200、进入思考，随后实际停止恢复；未捕获 429 的中间轮次不作限流证据。截图：AS-08-1-third-conversation-limited.png、AS-08-8-new-session-retry-running.png。后端限制有效，界面吞错导致失败，非 500。 |
| E-03 | 通过 | 实际下载证据篮 DOCX（37,780 B）、XLSX（6,246 B）至 tmp/browser-test/downloads，文件名分别证据篮-20261107-1601.docx、证据篮-20261107-1602.xlsx。DOCX 来源许可 / 署名 / 版本、7 处命中加粗、译文、句序出处齐，宋体 eastAsia、无 shd；XLSX 11 行 / 6 列含来源、空行、表头与 7 证据（3 条重钉 Tatoeba、2 editor、2 wiki），来源译文句号齐，表头宋体、无底色 / 公式。截图：E-03-1-exports-submitted.png、E-03-2-basket-xlsx-submitted.png、E-03-3-export-tasks-complete.png。初次误点检索导出不计；实际篮任务 9516312f。仅测试 profile 自动下载屏蔽已设 allow 并用同任务界面下载，非产品问题，不用 Office。 |
| U-01 | 通过 | Sol 删除测试项目逐页空态：内置 5 / 项目 0，语料库无整块项目空态；统计提示设置参数后计算；标注还无层；知识库稳定提示拖文件或链接导入；任务暂无；证据篮 0 且提示用行尾钉住。截图：U-01-1-corpora-with-builtins.png、U-01-2-statistics-empty.png、U-01-3-annotation-empty.png、U-01-4-knowledge-empty-stable.png、U-01-5-jobs-empty.png、U-01-6-evidence-empty.png。已切回主项目。 |
| U-05 | 通过 | editor 独立会话 390 × 844 实际登录成功；检索、统计文档 scrollWidth=1280，横滚至 scrollX=890 可实际点 n-gram，所见无重叠、按钮可达。截图：U-05-1-mobile-login.png、U-05-2-search-desktop-layout.png、U-05-3-search-horizontal-scroll.png、U-05-4-stats-desktop-layout.png、U-05-5-stats-scroll-button.png。已恢复 1440 × 900。 |
| U-06 | 通过 | 实际 Tab / Shift+Tab 遍历关闭、类型、语料、名称、标签集、范围和提交按钮，焦点可见；按既定 Q46，关闭模态后稳定 BODY，不回新建按钮。标签集实际展开后首 Esc 仅关下拉、模态保留，第二 Esc 关模态；再点 N-01 My 按 Enter 不重开，人工确认保留。截图：U-06-1-tab-focus.png、U-06-2-modal-closed-focus-body.png、U-06-4-dropdown-escape-modal-retained.png、U-06-5-token-enter-no-reopen.png。前置更正见 R19，中间未开下拉图不计覆盖。 |
| X-04 | 通过 | owner 独立 headless 只读核对 corpus_session 属性 HttpOnly=true、SameSite=Lax、Secure=false（本机 HTTP），document.cookie 名称列表为空。未输出 cookie 值，未写入任何文件密钥。 |
| E-04 | 通过 | 维基“研究”545 命中，前 4 页每页实际点击钉住 50 次，共 200 次，篮 7→57→107→157→207。刷新后重新开篮，实际显示“显示 200 / 共 207”，滚底可见加载更多；实际点击后有 207 个移出按钮且加载更多消失。截图：E-04-1-first-50-pins.png、E-04-2-200-of-207.png、E-04-3-bottom-load-more.png、E-04-4-loaded-all-207.png。未用 API 批造，207 条本轮测试证据保留复查，editor 原 2 条未动。 |
| AS-09 | 通过 | 学习者偏误会话 34.3 秒、16 工具，展开明确读取学习者偏误分析流程，并实际读取语料、5 行文本指标、标注统计 / 一致性 / 片段能力。正文 433 为排标点文本指标口径，不与含标点 494 混判；模型建议小库不抽样，未提出实际写操作，未新建层或写确认卡，条件分支不强制触发。截图：AS-09-1-learner-skill-no-write.png。 |
| AS-05 | 失败 | B16：Tatoeba 中文侧“翻译”84，抽屉占位与工具查询 / 子库正确，组件数字与工具一致。仅面包屑切 EWT 后等待超过 10 秒，顶栏新范围、旧 Tatoeba 结果和会话仍在，缺范围不一致说明及“按当前范围新对话”按钮；需额外检索 EWT 后才出现提示，再实际新对话成功。截图：AS-05-1-current-result-context.png、AS-05-2-current-query-tool-steps.png、AS-05-3-scope-mismatch-banner.png（实际为缺失提示）、AS-05-4-new-current-scope.png。无 5xx；简繁统计口径差按已知限制不报。 |
| J-05 | 通过 | 失败筛选第 3 页 C-22 行自动展开实际解压错误与 PARSE_ERROR；点 `#85ea5c1e` 详情显示完整编号、S-解压大及样本、sol-owner、解析阶段、开始 / 结束 13:50:22、用时 0.1 秒和失败原文，实际关闭详情成功。截图：J-05-1-failure-detail.png。 |
| J-07 | 通过 | 1280 × 800 任务页取消操作右边界 1,176，下载 / 重试右边界 1,196，均小于 1,280，滚动可见可操作。截图：J-07-1-1280-action-column.png、J-07-2-download-retry-column.png。已恢复 1440 × 900。 |
| J-06 | 通过 | S-GBK 频次实际以最低 7、8 各提交新任务 `4eb0adba`、`efa6fac8` 并完成，托盘两项均显示“频次 · S-GBK 作文 / 已完成”，不是计算编号或已处理 0；并行导入另显示真实 53,892 / 273,892 字。实际点第 2 项跳转统计结果 `49a53c45-338b-4caf-ba18-cbcef7819f3b` 并渲染 2 行频次。截图：J-06-1-method-scope-tray.png、J-06-2-opened-frequency-result.png。无 5xx。 |
| U-02 | 通过 | 实际刷新后观察 J-03 导入 `#1f3bfef6` 运行“分句与标注 · 44,736 / 273,892 字 16%”，15 秒后仍同值，未虚称增长或估值。失败库 S-意大利语显示 LANGUAGE_UNSUPPORTED 与具体 it 支持范围；S-扫描件显示样本名及无文字层、不支持 OCR 的实际原因。截图：U-02-1-failed-corpus-reason.png、U-02-4-import-live-reloaded.png、U-02-5-import-live-after-15s.png；旧列表中间图不作运行证据。 |
| AS-10 | 通过 | AS-01 前 owner 基线为 2026-11、38,546 token / 不限；AS-01 / AS-02 后实际通过设置→账号重新加载，显示“2026-11”“1,514,397 token / 上限 不限”，明确增加。随后 admin 2026-11 按用户 owner 总 1,771,350 = 提示 1,659,284 + 生成 112,066、81 调用，按项目 Sol 浏览器测试同数；不同采样时刻仍有后续调用，不要求两次总数相等。截图：AS-10-1-owner-usage-increased.png、AS-10-3-admin-usage-by-user.png、AS-10-4-admin-usage-by-project.png。 |
| J-02 | 通过 | 3 个真实表单快速提交法 / 德 / 西小导入，同时提交 S-GBK 频次 `4f7c271a`；队列显示法运行、德前 2 / 西前 3 / 统计前 4，随前任务完成推进。最终法 1 / 8 / 158、德 1 / 7 / 120、西 1 / 7 / 128，统计完成。日志核验统计由 worker-light 16:29:25.278–25.324 处理 46 ms，同刻普通 worker 处理西语 11.7 秒。小导入共享短 lane，FIFO 排在先提交小导入后正常，见 R20。截图：J-02-1-queued-imports-and-light-stat.png、J-02-2-light-stat-and-queue-state.png。无新增产品问题。 |
| M-01 | 通过 | admin 搜 sol-owner 得两项目、列齐；仅 Sol 删除测试真实改派给 editor，两账号设置分别验证原 owner 为编辑者、editor 为负责人，再立即改回 owner。改派新增的 editor 成员关系仅本次移除，恢复 owner + viewer 原 2 人。停用账号不可改派复用本轮 A-09 已实测证据，不重复停用，sol-disabled 当前启用不变。截图：M-01-1-owner-project-filter.png、M-01-2-reassign-confirm.png、M-01-4-old-owner-now-editor.png、M-01-5-editor-now-owner.png、M-01-7-owner-restored-settings.png、M-01-9-original-members-restored.png、M-01-1-disabled-owner-unavailable.png。 |
| M-02 | 通过 | admin 实际筛运行中 / 导入，找到 owner 的 S-取消导入，确认“取消该任务？”后执行，`POST /api/jobs/1f3bfef6.../cancel` 200、提示已取消，owner 独立界面同步已取消 23%。已由导入执行者界面重试 `4b8d6de1` 恢复中，不再次取消。截图：M-02-1-global-running-import.png、M-02-2-cancel-confirm.png、M-02-3-cancelled-toast.png、M-02-4-owner-cancel-synced.png。 |
| M-03 | 通过 | sol-admin 操作筛选含账号生命周期、恢复、改派、管理员取消，IP 172.26.0.1；清除 admin 过滤再选登录失败，7 条 owner 13:51–13:52，操作人实际为邮箱。选主项目、起止日 2026-11-07，20 条均同项目同日，成员及删除、管理员取消记录齐。截图：M-03-1-admin-audit.png、M-03-2-system-login-failures.png、M-03-5-today-project-filter-final.png。预期更正见 R21，中间日期框图不作最终证据。 |
| M-04 | 通过 | 仅处理 H-02 专用反馈，改已处理、备注已转缺陷，提示已标记处理；已处理中可见、回未处理后该文字消失。截图：M-04-1-feedback-handled-toast.png、M-04-2-handled-feedback-visible.png。 |
| M-05 | 通过 | 版本 dev、对话主机 DeepSeek、向量本机；当前 worker、worker-light 两容器刚刚正常，历史另 22 心跳无响应按契约允许保留，见 R22。磁盘可用 883.4 / 总 1,006.9 GB、缓存 123 MB、备份未找到。截图：M-05-2-system-stable.png；初始未加载图不作最终证据。 |
| M-06 | 通过 | admin 非成员实际打开主项目检索地址，仅门页“你已不是该项目成员 / 项目已删除或移出”，无项目内容。截图：M-06-1-admin-project-content-denied.png。 |
| M-07 | 通过 | 实际开内置任务开关，列出维基 / Tatoeba 导入和索引历史，点详情有内置标签；关闭开关后回 Sol 管理员项目暂无任务。截图：M-07-1-builtin-jobs.png、M-07-3-builtin-detail-tag.png、M-07-4-project-restored-final.png。标签位置更正见 R23，已恢复开关。 |
| X-05 | 通过 | 专用脚本字符串库在列表、详情、面包屑、命令面板和任务均字面显示，未生成攻击 DOM、无对话框或控制台异常；admin 反馈 id93 中脚本文字也正确转义，无注入 script。仅本例库已界面删除 204、列表确认移除。截图：X-05-2-corpus-imported-literal.png、X-05-4-command-name-literal.png、X-05-7-search-breadcrumb-literal-final.png、X-05-8-jobs-literal-final.png、X-05-11-own-corpus-deleted.png、X-05-12-admin-feedback-literal.png。反馈保留，未动其他库。 |
| J-04 | 阻塞 | E04，部分完成：Tatoeba 整库 / 等分 10 段实际统计首任务 4.65 秒完成，有限一次补测 `721def91` 约 5.3 秒完成；托盘详情初有取消按钮，下一命令任务已完成、按钮消失，CLI 未发取消请求。P-08 同类任务已有实际取消 200 与重试完成证据，但本条 5 秒内停止及统计页不再计算中的观察未补齐，保守阻塞、不报产品缺陷。截图：J-04-2-second-stat-completed-before-cancel.png；主执行者最后同脚本补验 `86439902` 初帧也无取消按钮，2.5 秒即完成、未发 cancel，补图 J-04-3-third-target-completed.png；不再重算，任务均完成无残留。 |
| J-01 | 通过 | C-06 原运行已观察 0 / 83,679 字；本次实时导入 255,559 / 273,892 字、93% 具单位。任务页 C-06 完成行 `#6fea0f58` 实际显示 1,136 篇 / 1,146 句 / 15,063 词、100%，托盘标题最近任务；运行中的任务标题此前已有实际观察，未伪造专图。截图：J-01-1-running-char-unit.png、J-01-4-HF-complete-recent-tray.png；初加载图不主引。 |
| J-03 | 通过 | 与 M-02 共享实际管理员取消路径（非 owner 本人点取消）：原 `1f3bfef6` cancel 200，owner 界面同步已取消 23%、63,059 / 273,892 字，后续任务相继运行。owner 真实点重试自动打开新 `4b8d6de1`，从 3% 至 97%，最终 16:30:13–16:38:16 完成，1 篇 / 11,998 句 / 56,000 词；自动索引 `c6acdf95` 也完成，恢复已完成。截图：J-03-1-import-submitted.png、J-03-2-owner-sees-admin-cancel.png、J-03-3-retry-opened-new-task.png、J-03-4-new-retry-running-detail.png、J-03-5-retry-completed.png、J-03-6-retry-finished-counts.png。 |
| C-26 | 通过 | 删除 S-去重确认框准确列 1 篇 / 2 句、C26 层人工 3 条、证据 1 / 笔记 0，初始删除禁用；勾选后实际 `DELETE /api/corpora/d42e5719-4749-45d6-8a1d-e6622f93bacb` 204，专用库及层删除，S-去重2 保留。篮仍 208，实际滚底看见 C26 的原句与出处保留。学习者 essay-01 删除确认有 22 人工、1 篇 / 8 句及“删除后需重建索引”，仅查看后取消，5 篇未删。截图：C-26-2-delete-impact-three-manual.png、C-26-3-deleted-corpus-evidence-retained.png、C-26-4-document-reindex-warning.png。仅按方案删除本轮测试库，非 sol 数据未动，无 5xx。 |
| C-27 | 阻塞 | E05，部分完成：实际删除准确 `hf-export-nli #10`，自动索引 `60c1ab46` 16:44:07–10、2.7 秒完成；规模为 1,135 篇 / 15,042 词，实际 spreadsheet 检索 0。删除后同脚本立即进检索，初帧范围尚加载、下一可用帧已完成，未捕获“索引更新中”提示；不冒称瞬态通过、不再重删。截图：C-27-1-delete-formula-document.png、C-27-3-deleted-query-zero.png、C-27-4-automatic-index-completed.png；C-27-2 实为完成后空框，不作提示证据。核心重建正常，不报产品缺陷。 |
| K-05 | 通过 | 长篇文献实际摘要任务 `109babed` 16:44:00–16:45:27（1 分 27 秒），界面进度 5 / 21→20 / 21→完成；重开详情有 396 字摘要、“按 20 段摘要”“模型生成”，明确“按 20 段摘要（全文 22 段约 257830 字，只读取前 20 段约 239207 字）”。只读任务结果 succeeded、done21 / total21、parts20 / total_parts22、truncated=true、error=null，与界面一致，无需重试。截图：K-05-5-summary-task-completed.png、K-05-6-twenty-segment-summary-visible.png。 |
| U-03 | 通过 | 仅停本测试栈 API，失败 annotations 为 nginx 502 HTML、无 error.code、非 API 500。恢复后明确 There 重试 200、人工确认；曾误确认 are 已真实重置为建议。唯一有区别短复测在 Enter 后 1,354 ms 捕获并截图“服务暂时不可用，本次修改未保存，请重试”，finally 启动、health ok / db true、API healthy。恢复后不再 Enter，刷新确认 are 仍建议、There 已确认，最终层 15 / 494，确认 14 / 修改 0 / 拒绝 1，计数不再变。截图：U-03-6-there-retry-confirmed-final.png、U-03-8-short-retest-error-toast.png、U-03-9-are-unsaved-after-refresh.png、U-03-10-there-preserved-final.png、U-03-11-count-unchanged-final.png。中文提示断言已补齐，无遗留停服或误标。 |

## 问题

问题编号从 B01 起；环境问题与方案更正单列。

| 编号 | 页面/功能 | 严重度 | 现象 | 复现步骤 | 期望 | 截图 | 控制台/网络错误 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B01 | 设置 / 添加成员 | 一般 | 在成员已有 3 人时，输入带前后空格的 `  SOL-VIEWER@Example.edu  ` 点“添加”，邮箱框红字“请输入邮箱”，人数仍为 3；重复提交及 Tab 失焦后仍可复现。换小写无空格邮箱可添加，最终 5 人。 | sol-owner 登录 → 设置 → 项目 → 邮箱输入上述带空格值 → 添加。 | P-01：邮箱匹配前去除前后空白、转小写，可加入查看者。 | P-01-1-email.png | 控制台无异常；提交未发出对应 `GET /api/users` 或成员添加 POST 请求，无失败状态码、无 `error.code`，非 500。 |
| B02 | 登录 / 改密错误提示 | 细节 | 登录 429 中文提示下重复显示无操作意义的英文小字 `LOGIN_RATE_LIMITED`；A-12 改密错误同样显示 `WRONG_PASSWORD`、`LOGIN_RATE_LIMITED`。功能和恢复行为正常。 | owner 登录页填正确邮箱、错误密码快速提交 8 次；或 temp 账号页以错误原密码连续提交改密，查看错误提示。 | 依项目界面规范，不添加无实际作用的错误码小字；保留中文提示即可。 | A-03-1-rate-limited.png、A-12-1-shared-rate-limit.png | `POST /api/auth/login` 429、`LOGIN_RATE_LIMITED`；`POST /api/auth/password` 400、`WRONG_PASSWORD`，之后 429、`LOGIN_RATE_LIMITED`；控制台无页面崩溃。 |
| B03 | 检索 / 语义范围切换 | 一般 | 当前范围切为 S-学习者作文，面板“未建”、41 句、预计约 1 秒、检索禁用；等待 2.2 秒后下方仍显示“相似句 50 句 · 按相似度排序”、HF #831 等 50 条结果及其 year 2019 上下文，无旧查询范围说明，易误认为新库结果。 | sol-owner 登录主项目 → 检索 / 语义 / S-HF 导出 → 查 A teacher explains the meaning of a poem. → 点首条 #831 上下文 → 面包屑切 S-学习者作文 → 等 2.2 秒。 | 范围变更后清空旧语义结果和上下文，或明确标注旧查询范围，避免与当前范围混淆。 | S-25-2-stale-semantic-results.png | HF semantic-index GET 200 → `POST /api/search/semantic` 200 → 学习者 semantic-index GET 200；切换后无新语义查询；console errors 空，无失败请求、无 500，error.code 不适用。 |
| B04 | 检索 / 原生依存树 | 一般 | UD 中文 GSD 的 `{dep=nsubj}` 成功返回 8,383 次，但 KWIC 行尾仅加入术语例句、钉住；打开上下文检查器也无依存入口，无法查看关系标签和弧线树。 | sol-owner 登录主项目 → 检索 → UD 中文 GSD → `{dep=nsubj}` → 检索 → 查看行尾并点击一行。 | S-10、contracts/p3.md:107：KWIC 行可展开该句依存树，原生 CoNLL-U 依存应可展示。 | S-10-1-no-dependency-button.png | `POST /api/search` 200（requestId 15468.145），无 error.code、无控制台错误，非 500。只读定位：Search.tsx 的 treeLayer 仅取独立 dep 层，未接原生依存。 |
| B05 | 统计 / 分布图布局 | 一般 | 1440 × 900 下分布图卡仅约 169 px 宽、SVG 127 × 220，10 柱数值标签 126.8 / 114.7 / 102.1 等重叠，页面仍有大片横向空白，影响读数。 | sol-owner 登录主项目 → 统计 / 分布 → 维基中文 → 翻译 / 文档位置 / 10 区间 → 计算。 | 图表利用可用宽度，柱数值标签清晰、不重叠。 | T-07-3-position-distribution.png | `POST /api/stats/distribution` 200；无控制台错误、无 error.code、非 500。 |
| B06 | 统计 / 分布回到例句 | 一般 | 10–20% 表行有 7 命中；点第 2 柱选中该行后“回到例句”，实际无区间过滤，最终为全查询 60 次 / 55 句 / 34 篇、counts.complete=true。 | 在 B05 分布结果点第 2 柱 → 高亮 10–20% 表行 → 点该行“回到例句”。 | 回检索范围保留所选文档位置区间，命中 7 次，与该行一致。 | T-07-6-bar-selects-table-row.png、T-07-7-selected-row-examples.png | `GET /api/stats/ce34359c-a2d2-4a2a-9da2-e7f71f142fa9` 200：row 10–20%、hits=7，但 search_scope 仅 corpus_id；实际 `POST /api/search` 200，scope 亦仅 corpus_id、query=翻译，返回 60 / 55 / 34；无控制台错误、error.code 不适用、非 500。 |
| B07 | 标注 / 统计文档进度 | 一般 | N-01 词性层编辑左侧 essay-01 已完成 2 / 8、层进度 14 / 494；“统计 → 文档进度·句”五篇却全部为 0 / 0。重开统计并等 2.2 秒仍相同，进度展示互相矛盾。 | sol-owner 登录主项目 → 标注 → S-学习者作文词性 → 编辑页看 essay-01 的 2 / 8 → 统计页看文档进度。 | 文档句进度与编辑区实际句数和完成状态一致，不显示无效 0 / 0。 | N-02-3-progress-2-of-8.png、N-02-4-doc-progress-zero-stable.png | `GET /api/layers/1aeb59f4-2952-4a14-9897-6585f25a2ff1/stats` 200；progress=494、confirmed=13、rejected=1，per_document essay-01 total=96、confirmed=13、rejected=1；界面仍全 0/0。无控制台或网络失败，error.code 不适用。 |
| B08 | 标注 / 预标进度单位 | 一般 | S-学习者作文仅 5 篇、41 句；创建估算和任务进度均按句，标注层列表却显示“预标中 30 / 41 篇”。单位固定写错，不是异步数值暂不同。 | sol-owner 登录主项目 → 新建片段层 → S-学习者作文 / learner-errors / 全部文档 → 预标中看层列表。 | 预标进度按句显示，应为 30 / 41 句，与任务实际单位一致。 | N-06-2-preannotation-job-progress.png、N-06-3-wrong-progress-unit.png | `POST /api/layers` 及对应预标请求均 200；无网络错误、非 500，error.code 不适用。 |
| B09 | 抽样 / 方法附录 | 一般 | 抽样方法说明包含总命中 84、n=20、seed=42、编码结果和 Wilson 文献，却完全缺少检索句数 79、文档数 1，也无单独检索节；全文 DOM 不含 79。 | Tatoeba 中文侧“翻译”检索 → 抽样 20、seed 42 → 汇总“方法说明” → 查看附录。 | SP-05、contracts/p8.md:82 要求语料、检索三项计数、抽样与编码说明齐全。 | SP-05-1-sampling-appendix.png | `POST /api/projects/e6b68bfd-c5ba-4de3-81ce-8a180fb439a6/method-appendix` 200，无 error.code、控制台异常，非 500。 |
| B10 | 标注 / 片段键盘确认 | 严重 | 点击边界按钮后仍保留焦点，Enter / Shift+Enter 再激活该按钮，实际改写人工标注范围。informations 147–159 调整至预定 148–158 后，Enter 变为 148–157，Shift+Enter 又为 148–156；箭头切换后仍可稳定复现，未确认成功。 | sol-owner → 偏误层 / essay-02 句 4 → 拖选 informations 建用词片段 147–159 → 起点 +1、终点 −1 至 148–158 → 按 Enter，再 Shift+Enter；或先 ←→ 切片段后再 Enter。 | Enter 仅确认当前片段、Shift+Enter 仅整句确认，保留人工设定的 148–158 边界。 | N-06-13-arrow-focus-before-enter.png、N-06-14-enter-shrinks-again.png、N-06-15-span-restored-explicit-confirm.png | 连续 `PATCH /api/layers/168f3f6f-e2e7-4c43-a81f-34b39a70d8c2/spans/1786` 均 200；requestId 38984.1954 end159、1955 end158、1956 Enter 后 end157、1959 Shift+Enter 后 end156，全部 action=modify，无 confirm。无 500 / error.code。已界面右移两次并显式点确认，恢复 148–158、focus=null。 |
| B11 | 知识库 / 检索摘要转义 | 细节 | 向量检索摘要字面显示 `Cohen&#x27;s`、`Krippendorff&#x27;s`，打开同文献对应 #79 则正常显示英文撇号。 | sol-owner 登录主项目 → 知识库 → 输入“什么是显化” → 向量 → 检索，查看首项摘要。 | 摘要正确显示撇号，不泄露 HTML 转义字符。 | K-02-7-escaped-apostrophe.png、K-02-5-document-location.png | `POST /api/projects/<主项目>/kb/search` 200，无 5xx / error.code；属于渲染转义问题。 |
| B12 | 知识库 / 笔记证据追加 | 一般 | 笔记已有 Tatoeba 547 证据 1 条，再单次从含该条的 8 条证据篮加入现有笔记，变为 9 引用；立即正文仍 1 块，刷新后有 9 块、547 重复两次，追加未去重且客户端正文滞后。 | sol-owner → 新建翻译例句观察 → 正文中插入 Tatoeba 547 → 证据篮 8 条 → 加入现有笔记 → 确定一次 → 查看预览并刷新。 | 每条证据只插入一次；正文和引用数同步，不需刷新才能看到追加。 | K-09-2-basket-appended.png、K-09-3-preview-duplicate-reference.png、K-09-4-reloaded-duplicate.png | 首次 `POST /api/kb/documents/d98e3132-f792-4c19-bb03-caee8ee122c9/refs` 200（42936.4029）；证据篮追加 8 次 4048/4049/4050/4051/4052/4054/4055/4056 均 200；无 console 错误或 error.code，非 500。 |
| B13 | 证据篮 / 底部操作布局 | 一般 | 1440 × 900 下底部 5 个操作按钮不换行，“清空我钉的”按钮 x=1457.2、宽 78，完全超出视口；普通点击落空并关闭面板，需 Shift+Tab 聚焦后 Enter 两次绕路。 | sol-owner 登录主项目 → 打开含证据的证据篮 → 查看底部清空操作。 | 主要操作在视口内可点击，按钮组可换行或横向可达。 | E-02-3-before-clear.png | 无 API / 控制台错误；布局问题，error.code 不适用。清空逻辑已用真实键盘完成，editor 刷新确认仅 owner 项被删、他人项保留。 |
| B14 | 助手 / 近义词对比卡 | 一般 | 正式结果 row_count=31，助手 SketchDiff 卡却标 29 项、仅 29 行，未标部分展示；漏 conj-large（0/2、diff −12）、pp:than-US（0/2、diff −13.192645）。已显示行数字正确，但需跳统计页才可看全。 | sol-owner → 助手 → UD 英文 EWT → 比较 big 和 large 用法 → 展开近义词对比卡，与正式统计结果对照。 | 卡片完整呈现工具结果，或明确部分展示及查看完整结果入口，不以模型措辞浮动掩盖数据缺项。 | AS-04-1-skill-and-comparison.png、AS-04-2-inconsistent-sketch.png | `GET /api/stats/7409c384-4cbc-4021-bd4e-c197fbf3936b` 200、row_count=31，卡 29 DOM 行；29 行 freq_a / freq_b / diff 均匹配。非 500，无 HTTP error.code；链另可见 openui-lang 工具未找到原文。 |
| B15 | 助手 / 并发限流提示 | 一般 | 第 3 对话被后端 429 拒绝，body 有 TOO_MANY_RUNS 和“已有 2 个对话在运行，请等待完成或停止后再试”；页面却没有错误提示、正文空、输入已清空，多分钟仍为空，用户无法知道拒绝原因且丢失输入。 | owner 3 标签分别新会话，约 6.3 秒内发送长问题 → 前两运行时看第 3 页。 | 显示后端明确的并发提示，保留或可恢复输入；停止前一个后可再次发送。 | AS-08-1-third-conversation-limited.png | `POST /agent/sessions/b1b259f0.../messages` 429，`error.code=TOO_MANY_RUNS`；补测停止请求 204 后第三消息 200、进入思考。无 500；中间未捕获 429 的请求不作为限流证明。 |
| B16 | 助手抽屉 / 页面范围切换 | 一般 | 从 Tatoeba 中文侧结果打开助手后，仅用面包屑切 UD 英文 EWT 并稳定等 >10 秒，顶栏已 EWT，但抽屉仍旧会话，未显示会话 / 当前页面范围差异及按当前范围新对话按钮。需额外检索后才出现应有提示，用户需绕路。 | sol-owner → Tatoeba 中文侧查翻译、选行开助手并提问 → 面包屑切 UD 英文 EWT → 等待，不再次检索。 | 选库即提示会话范围与页面范围不一致，并提供按当前范围新对话，按 AS-05 第 3 步即可完成。 | AS-05-3-scope-mismatch-banner.png、AS-05-4-new-current-scope.png | 无 5xx / error.code；只读定位 AssistantDrawer.tsx 使用 ctx?.scope 优先且 ctx 来自旧 req.scope，选库未重检仍沿旧范围。 |

## 严重度统计与优先修复

截至当前：严重 1、一般 13、细节 2。优先修复顺序：B10 确认键误改人工边界；B06 分布回查丢位置筛选；B12 笔记重复插证据；B14 助手统计卡缺项；B03 切未建索引范围残留旧结果。B16 同类上下文提示紧随。

## 环境问题

| 编号 | 影响用例 | 现象 | 处理与范围 |
| --- | --- | --- | --- |
| E01（已解除） | S-17 | 本机注册有 `C:\Program Files\Microsoft Office\Root\Office16\EXCEL.EXE`；请求通过 Computer Use 打开 Excel 时，工具明确返回“Computer Use was not approved to use Excel”。 | 已结束该 CUA 阶段，未绕过拒绝；CSV/XLSX 均已下载并完成只读结构核验，原为测试环境权限限制；用户随后将 S-17 条件调整为只读文件结构核验，现该用例已通过，此项不再计阻塞，也不计产品缺陷。 |
| E02 | C-03 | agent-browser 的 drag 帮助只提供 DOM source / target 拖动，无本地文件拖入参数，方案要求的真实本地文件拖入分支未执行。 | 已实测重复点选去重，但不据此替代拖入；未使用 JavaScript 合成 drop，整条暂列阻塞，不计产品缺陷。证据：C-03-1-duplicate-file.png 为已测分支界面。 |
| E03 | N-09 | 依存预标在取消请求到达前已完成；有限尝试中虽捕获运行 8 / 122 句，实际 cancel 返回 409，最终 ready，无失败重试状态。 | 取消 / 失败 / 重试分支未完成，按有限尝试要求停止，列覆盖阻塞，不报产品缺陷。响应体、error.code 未捕获；误建 POS 层已删除、不计覆盖，无遗留副作用。 |
| E04 | J-04 | 统计在 4.65–5.3 秒完成，详情取消按钮在下一命令前消失，未发本次 cancel 请求。 | 有限补测后停止；P-08 取消证据可参考，但本条时限与页面结束态未完整覆盖，列部分阻塞，不计产品缺陷。 |
| E05 | C-27 | 自动重建在 2.7 秒内完成，立即导航的可用帧未捕获索引更新中提示。 | 实际自动任务完成、删除项检索 0 已通过；仅瞬态提示覆盖不足，保守部分阻塞，不重删、不报产品缺陷。 |

## 方案更正

| 编号 | 用例 | 更正 | 原因 |
| --- | --- | --- | --- |
| R01 | C-28 / 批次顺序 | 批次 1 先执行 C-28 第 1、2、4 步；第 3 步应在批次 2 的 C-06 导入完成后补测。 | C-28 第 3 步依赖 S-HF 导出，但方案将 C-06 排在批次 2，批次 1 无法完整执行。本项为方案依赖顺序更正，不计产品缺陷。 |
| R02 | C-05 / 元数据输入 | 无效 JSON 先修为 `{}`，再切换字段表并验证重复字段及缺字段名。 | 无效 JSON 直接切换时保留输入与错误，防止未解析内容丢失，属于合理保护；原步骤需补操作，不计产品缺陷。 |
| R03 | G-05 / 批次顺序 | 将 G-05 补入批次 3 的引导回归。 | 第五节执行顺序表未列 G-05，本轮已补实际执行，未新建项目；非产品缺陷。 |
| R04 | P-11 / 并发限流 | 22 个并发请求应核对 20 次成功、其余 429，按服务端到达顺序判定，不按客户端循环编号。 | 实测 20 个 200、2 个 429，429 循环编号为 19、21，编号 22 为 200；并发到达次序可不同，限额实际正确。 |
| R05 | C-06、C-27、X-03 / CSV 文档标题 | CSV 导入标题按统一去扩展名规则使用 `hf-export-nli #n`，相关查找以此为准。 | 实际标题为 `hf-export-nli #10` 等，与 TXT 同样去扩展名；方案写为 `.csv #n` 有误，不是正文或元数据丢失。 |
| R06 | S-13 / 译文条件错误文案 | 字段下的 inline 错误为“第 11 个字符：$ 后应为数字，如 $3 或 $2-5”，无需额外“译文条件”前缀。 | 提示就在译文条件框下，错误字段和字符定位准确；原方案将前缀也写入预期，属于轻微文案预期更正，不计产品缺陷。 |
| R07 | S-11 / 无片段层前置 | 第 2 步改在当时无片段层的维基英文补测，其他步骤仍使用维基中文。 | 批次 3 的 P-08 已为维基中文创建“P08负责人抽样”片段层，此时片段查询可检索为正常行为；应在实际无该层的语料核验提前报错，不计产品缺陷。 |
| R08 | T-09 / 作文词数估计 | 样本实际 5 篇词数为 78–97，替代方案估计的“约 78–93”。 | 实际每篇数值已核对，仍全部不足 100，短文指标适用说明正确；近似范围差异不作为产品计数缺陷。 |
| R09 | T-04 / 搭配回跳方向计数 | 奥德赛共现总频次 3；“右侧”回跳应为 1 次，反向左侧为 2 次，1 + 2 = 3。 | 右侧 `翻译 $4 "奥德赛"` 在句 201 为 1 次；左侧在句 172 为 2 次。原方案将总共现 3 当成右侧命中 3，产品方向查询正确，不计缺陷。 |
| R10 | T-05 / 同库参照校验 | 实际为参照菜单排除当前目标；目标变更若与参照重合，自动清空参照并提示“请选择参照”。 | 防护发生在选库阶段，比方案期待“参照与目标相同”更早，避免同库提交有效，不计产品缺陷。 |
| R11 | T-07 / 柱图交互 | 点柱先选中、高亮对应表行，再点击该行“回到例句”。 | 柱本身不直接导航属于实际交互设计，原方案步骤应细化，不因此报缺陷；表行回跳缺少区间过滤另记 B06。 |
| R12 | T-08 / 默认最低频次期望 | 前列词应以默认最低频次 2 过滤后的实际 8 项为准，不强求 translated 出现。 | 样本另一处 translated 对应中文“直译”，不匹配“翻译”；匹配 7 句中仅 1 次，按参数过滤正确。 |
| R13 | K-02 / 固定来源预期 | 检索不强制同一 top 8 同时出现 DOCX 与综述；用对应内容查询补验 DOCX 可返回、文档可定位。 | 三模式实际排序均可检索，向量 top 8 为综述片段；“译文比原文更明确”向量查询 DOCX 首位返回，固定来源混合不是检索排序契约。 |
| R14 | E-01 / 共享证据判重操作 | 正常刷新页面中同条已显示“已钉”，再点会移出；需两会话旧 DOM 竞争提交同条，验证 existing=true 与已在提示。 | 共享篮状态会同步，不能把“已钉”的移出按钮误作再次钉住。实际旧页面竞争请求已确认去重正常。 |
| R15 | AS-02 / 执行后证据计数 | 增量应等于工具结果中的唯一新增数，已有 / 重复项不再新增，不固定要求 +2。 | 本次两工具结果为 1 新增、1 已有，篮由 3 变 4，取消后不变；P08 已有同句证据，按工具实际结果核对正确。 |
| R16 | AS-11 / 保存笔记标题 | 保存回答默认沿用会话标题，实际直接保存成功，不固定为“助手回答”。 | 本次新笔记标题沿用“统计维基百科中文里 翻译的搭配词，前10个，条形图展示logDice”，内容表格正确保留，非保存失败。 |
| R17 | AS-04 / Word Sketch 调用 | 按本地近义词流程，仅需完整画像时额外调用 Word Sketch，不强制每次比较都调用。 | 本地 skill 第 4 条有明确条件；本次已读取流程并执行多项对比、近义词对比，调用必要能力即可，数字和组件另核。 |
| R18 | K-06 / 词性模式候选前置 | S-TMX 小样本可有效返回 0；为核验有草稿、语料来源和例句分支，补一次现有 S-HF 词性模式抽取。 | S-TMX 没有出现 2 次以上的词性组合，空候选提示正确；不能固定期待新增草稿，补 S-HF 后 12 项有例句并可确认。 |
| R19 | U-06 / 关闭焦点 | 模态关闭后焦点落 BODY，不要求回新建层按钮；随后点词元 Enter 不重开即可。 | doc/change-log.md:128 的 Q46 既定处理为避免 Enter 再次触发顶栏按钮；当前真实行为符合该决定，方案焦点返回预期应修正。 |
| R20 | J-02 / 小导入排队预期 | 小于默认 5 MB 的导入同属短 lane，按 FIFO 与统计共享队列，不要求统计越过已提交小导入。 | 只读 jobs.py short_lane 与实际日志均验证：worker-light 正常处理统计，未被重导入阻塞；原方案将小语种样本也当成长队任务不准确。 |
| R21 | M-03 / 登录失败审计 | 切登录失败前清除 sol-admin 筛选；本轮已知邮箱失败的操作人实际显示该邮箱，不固定要求系统或空。 | 筛选和操作对象实际正确，邮箱展示更明确；原预期写死身份文字，不计产品缺陷。 |
| R22 | M-05 / Worker 历史心跳 | 核对当前 worker / worker-light 两容器正常；允许 workers[] 保留历史心跳条目，不要求界面只有两行。 | contracts/p9 的历史数组允许多行，另 22 旧记录无响应不等同当前容器停机。 |
| R23 | M-07 / 内置标签位置 | 内置标记可在任务详情头核对，不固定要求表格行标签。 | 实际已列内置任务，详情明确内置，开关恢复正确；仅标签位置不同。 |

仓库 HEAD 与方案版本差异仍列入环境待核对，尚不判定为方案错误。

## 批次进度

### 批次 1 冒烟

本批 14 条：11 条通过，1 条失败（P-01 / B01，一般），2 条暂列阻塞。其中 C-28 为部分完成待 C-06 依赖；S-17 为下载与结构核验完成、Excel 可视步骤受 E01 限制。未对其他批次或全项目作完成结论。

P-01 已用规范邮箱完成成员添加，最终 5 人，后续流程可继续；本批未执行停服务、停用账号或删除等需恢复操作。

待后补事项：

- C-28 第 3 步：C-06 完成后创建 HF 2021 起子库并核对篇数。
- S-17：Excel 可视打开受 E01 阻塞。已核验文件为 `tmp/browser-test/downloads/检索结果-20261107-1310.csv`、同名 `.xlsx`，仅完成结构检查。
- AS-10：AS-01 前已记录基线为 2026-11、38,546 token / 不限，后续尚待验证。

X-01 响应头实值：`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: same-origin`、`Permissions-Policy: camera=(), microphone=(), geolocation=()`。

下一步继续批次 2 导入。
### 批次 2 导入（进行中）

以下为已执行步骤与后台状态，尚未形成整条用例结论：

- C-06：S-HF 导出已提交，任务 `#6fea0f58`，观察到分句标注 `0 / 83,679 字`。列映射默认正文 premise、标题行号、语言使用上方语言，其余列为元数据；清空正文列后上传禁用，重选 premise 后提交。截图：C-06-1-column-map.png、C-06-2-body-required.png。
- C-16：日语任务 `#e5efe606` 已导入 1 篇 / 6 句 / 142 词；法语 `#4d056708` 已导入 1 篇 / 8 句 / 158 词，索引排队；德语 `#0c0d5a6d` 运行中，`0 / 736 字`；西语 `#6603361e`、俄语 `#8774c491` 排队。各语种检索与最终状态尚待核验。
- N-10：指定中文的 S-对齐中文 `#c701fe42`、指定英文的 S-对齐英文 `#da977e57` 已提交并排队。截图：N-10-1-queued-imports.png。
### 批次 3 账号与权限（穿插进行中）

批次 2 耗时任务已提交后，穿插执行 A-05、A-06，均通过；其余用例继续执行，不作本批小结。sol-admin 使用独立会话 `sol-admin-real`，已建立“Sol 管理员项目”，可用于 C-29 管理员入口检查。
批次 2 补充进度：C-02 已通过；C-03 以重复点选方式核验去重通过，拖入分支尚未执行。C-05 已完成带有效名称及文件的独立校验，三种错误均显示，点击上传被拦截，判定通过。切换字段表前须先将无效 JSON 修为 `{}`，否则保留 JSON 输入与错误，待确认为方案操作步骤更正。
批次 3 补充进度：A-07、A-08、P-02 已通过。为进入账号页执行 A-07，sol-temp 跳过引导后自动创建其“我的研究项目”，仅涉及本轮 sol-temp 测试数据。P-03 已完成，临时成员移除后主项目恢复 5 人。
批次 2 补充：C-04 已以 5 个作文文件和 genre、level 元数据提交 S-学习者作文，等待队列完成，尚未判定。
批次 3 补充：P-03、P-04、P-07、A-04 已通过。P-03 临时成员已移除，P-04 项目名已恢复，均完成恢复；未新增产品问题。
批次 2 补充：C-29、C-13 已通过。C-25 第 1、2 步已完成：Tatoeba cmn 语言 zh、45,703 句 / 402,442 词，分页从 1–50 到 51–100、101–150，始终共 45,703 句（截图 C-25-1-cmn-preview.png、C-25-2-page-three.png）；第 3 步作文预览仍待 C-04 完成。C-29 管理员会话已关闭释放资源，未修改内置语料。
批次 3 补充：A-11 已通过，sol-temp 已恢复普通账号。P-05 已建立“Sol 删除测试”（`06bcbe93-249c-440e-b18f-5d91e2899a39`），仅 owner、viewer 共 2 人，尚未执行最终删除；不作结论。登录限流用例尚未开始。一次工具诊断挂起已停止本轮诊断父脚本后恢复，不计产品缺陷。
批次 2 补充：C-23 已通过并立即恢复网络无限制，刷新确认本次空语料库不存在。耗时导入已运行约 23 分钟，CPU 持续高，仍在观察，尚不判产品故障。
批次 3 补充：P-05 已通过且临时项目已恢复。P-06 尚未确认第二次删除，仅停在确认框，不作结论。C-22 的样本上传被自动审批拒绝，目前尚未提交；继续核对前置护栏和样本风险，不计产品缺陷。
批次 3 补充：P-06 已通过并立即恢复，P-05、P-06 均无遗留删除状态，临时项目成员仍为 2 人。
批次 2 补充：C-04、C-25、C-32 已通过；C-28 的依赖步骤已补完，结果由暂时阻塞更新为通过。批次 1 最终为 12 通过、1 失败、1 环境阻塞（S-17 / E01）；原批次完成时的 11 / 1 / 2 统计为当时快照。

C-06 当前已完成 1,136 篇 / 1,146 句 / 15,063 词，7 个元数据字段齐全且 year 为数值；第 10 行公式文字、第 113 行单元格内两句换行文本保留（截图 C-06-3-completed-metadata.png、C-06-4-row10.png、C-06-5-cell-newline.png）。尚待任务详情核对跳过重复 59 篇及带逗号正文，暂不判整条通过。实际标题为 `hf-export-nli #10`（去扩展名），与方案 `.csv #10` 不同，待作为标题规则的方案更正确认。
批次 3 补充：A-09、A-10 已通过且立即恢复。停用期间穿插 M-01 第 5 步：在“Sol 删除测试”的改派负责人对话框搜索 sol-disabled，新负责人列表为空、改派按钮不可用，无法设为负责人，未实际改派（截图 M-01-1-disabled-owner-unavailable.png）；其余步骤留批次 8，暂不判整条通过。当前所有账号正常，无遗留停用、临时管理员角色或项目删除状态。
批次 2 补充：C-22 已在只读核对运行镜像的解压前拒绝护栏、样本仅约 0.5 MB / 1.3 MB、运行和排队任务均为 0 后重新通过自动审批，随后完成界面验证，两种解压上限均在毫秒级明确拒绝，未绕过拒绝或展开大文件，产品判通过，不保留为阻塞。N-10 两库均已完成、可检索，判通过；最终列表截图待补。
为满足 P-08 前置，提前完成 N-01 词性层流程并通过。P-08 已开始，五账号初始登录完成，权限矩阵仍在执行，不作整条结论。
P-08 进度：非成员已实际打开语料库、检索、统计、标注、知识库、助手、任务 7 页，全部为门页，无后续操作入口。P-10 暂待完整矩阵核验：帮助角色节列出 5 角色，但标注者文字仅“标注校对、检索、统计”，设置角色表则允许标注者编辑知识库；是否为说明遗漏待确认，暂不报产品缺陷或通过。
批次 3 补充：A-02、A-03 功能通过；A-03 另有探索细节 B02（重复英文错误码小字），不影响限流行为判定。A-09 首次截图因 viewport 设置未生效为 1566 × 1600，事实结论保留并明确该环境例外；会话已纠正为 1440 × 900，A-10 使用补图 A-10-3-retest-restored-1440.png，A-09 待按正确尺寸补复测证据。当前已恢复状态不变。
批次 3 补充：G-05、A-12 已通过。A-12 仅失败改密提交，实际密码未变；重复错误码小字并入 B02。等待限流窗口结束后再补 A-09 正确尺寸复测，当前账号状态均正常。
批次 3 补充：P-11 已通过，之后 1 分钟不以 owner 添加成员。并发请求的限流判定应按服务端到达顺序核对为 20 次成功、其余限流，不能按客户端循环编号硬判“第 21 次起”；该操作判定细化待编为方案更正（R03 已用于 G-05，不重复编号）。
证据复核更新：A-09 / A-10 已按实际 `innerWidth=1440`、`innerHeight=900` 完整复测停用、会话失效、拒绝登录、启用和原密码恢复，最终图改为 A-09-2-disabled-login-1440.png、A-10-3-retest-restored-1440.png，立即恢复完成。X-01 新标签初次默认 2162 × 1350，已设 1440 × 900 后重新访问并刷新两处 404，最终图改为 X-01-3-docs-1440.png、X-01-4-openapi-1440.png。上述尺寸例外为已解决的过程问题。当前账号均正常、temp 为普通账号、“Sol 删除测试”已恢复。
批次 2 补充：C-07–C-12、C-14–C-19、C-21、C-24、C-31 已形成通过结论，详见结果表；N-10 最终图已补为 N-10-2-completed.png。C-20 尚待收尾。C-06 已读取实际界面任务的已发生响应，核对 documents=1,136、skipped_duplicates=59，耗时 23 分 29 秒；当时全程高负载，不仅凭耗时判产品缺陷。未捕获完成通知的完整文案，不声称已看到完整跳过通知；带逗号正文仍待补验。
判定更正：C-03 由重复点选分支通过改为整条暂时阻塞；拖入文件分支尚未实际执行，待工具能力确认，不能以等价点选或静态代码替代。C-05 的无效 JSON 切换步骤更正已确认为 R02；CSV 文档标题去扩展名已确认为 R05，C-27、X-03 后续使用 `hf-export-nli #n` 查找。
P-08 查看者列实测（整条矩阵仍进行中）：

| 操作 | 查看者实际表现 |
| --- | --- |
| 7 个项目页面 | 语料库、检索、统计、标注、知识库、助手、任务均可打开。 |
| 检索、统计、CSV | 维基中文“翻译”60 / 55 / 34；CSV 实际下载；S-GBK 频次实际完成，236 词 / 130 项。 |
| 钉住证据 | `POST /api/projects/.../evidence` 403、`FORBIDDEN`，界面“权限不足”；P-08-2-viewer-pin-forbidden.png。 |
| 上传语料、新建子库 | 均无入口。 |
| 删除自建库、文档 | 均无入口；学习者作文详情仅文档、元数据。 |
| 语义索引 | 未建，只显示 41 句，无建立按钮；P-08-1-viewer-corpus-readonly.png。 |
| 新建层、预标、删除层 | 均无入口。 |
| 校对 owner 单人层 | 点 There 后 Enter 未改动，显示“查看者只读”；P-08-6-viewer-annotation-readonly.png。 |
| 抽样编码 | 使用已有 learner-errors 提交，`POST .../samples` 403、`FORBIDDEN`，界面“权限不足”；P-08-3-viewer-sample-forbidden.png。 |
| 知识库导入 | 页头无导入，导入卡显示“查看者不能导入文献”。 |
| 术语抽取、新建术语、新建规范 | 均无入口。 |
| 新建笔记 | 无入口。 |
| 上传词表 | 词表管理无上传入口。 |
| 方法附录 | owner 通过界面钉住 1 条维基“翻译”证据后，viewer 刷新共享证据篮，实际生成附录成功；P-08-5-viewer-method-appendix.png。 |
| 项目设置管理操作 | 名称框禁用，无成员管理、保存、删除项目、审计；P-08-4-viewer-settings.png。 |
| 取消、重试他人任务 | 任务页无入口。 |
| 内置库上传、重建 | Tatoeba 详情仅文档、元数据，无上传、重建。 |

上述 owner 证据保留供后续 E / K 测试，未清空其他成员证据。截图完整文件名已补齐。
### 批次 2 小结

本批唯一用例 29 条（C-02–C-25、C-29–C-32、N-10）：按当前结果表 27 通过、2 阻塞（C-03 / E02；C-32 运行进度未捕获），无失败。C-06、C-20 已补完结果核验，完整完成 toast 未全部捕获，以上明确采用实际界面与已发生任务响应交叉核对。C-32 建立、完成和取消保留旧索引流程已执行；运行中 x / y 数字进度未捕获，因此暂列部分完成 / 阻塞；后续 S-24 前有合理窗口时补一次实际界面运行进度观察，不为毫秒级帧反复重试。不计产品缺陷、不分配 B 号。C-28 为批次 1 的依赖补验，不重复计入本批。

本批无新增产品缺陷。C-23 网络已恢复无限制，本次空库已删除；C-32 本次重建已取消，旧索引仍已建可用；C-22 两种样本均解压前被拒绝，无大文件展开。无需恢复其他已有账号或内置语料。
批次 2 判定更新：主执行者决定保守将 C-32 改为部分完成 / 阻塞，实际 x / y 句进度未核验；当前本批 27 通过、2 阻塞、0 失败。已执行建立与取消保留旧索引流程的事实不变。
P-08 标注者列实测（整条矩阵仍进行中）：

| 操作 | 标注者实际表现 |
| --- | --- |
| 7 个项目页面 | 语料库、检索、统计、标注、知识库、助手、任务均可打开。 |
| 检索、统计、CSV | 维基中文“翻译”60 / 55 / 34，CSV 实际下载；S-GBK 频次 236 词 / 130 项。 |
| 钉住证据 | `POST .../evidence` 200、existing=false，创建人为标注者。 |
| 上传语料、新建子库 | 均无入口。 |
| 删除自建库、文档 | 均无入口。 |
| 语义索引 | 学习者作文仅显示未建、41 句，无建立按钮。 |
| 新建层、预标、删除层 | 均无入口。 |
| 校对 owner 单人层 | 第 3 句 There 点选并 Enter 不修改，提示只有创建者和名单内的标注者可以修改；P-08-7-annotator-layer-restricted.png。 |
| 抽样编码 | `POST .../samples` 403、`FORBIDDEN`，界面“权限不足”；P-08-8-annotator-sample-forbidden.png。 |
| 知识库导入 | 实际上传专用 58 B 的 p08-annotator.md，“P08 标注者文献”可检索；P-08-9-annotator-imported.png。 |
| 术语抽取、新建术语、新建规范 | 均隐藏。 |
| 新建笔记 | 实际建立“P08 标注者笔记”并保存；P-08-10-annotator-note.png。 |
| 上传词表 | 隐藏。 |
| 方法附录 | 实际生成成功；P-08-11-annotator-method.png。 |
| 项目设置管理操作 | 名称框禁用，无成员写操作、保存、删除项目、审计。 |
| 取消、重试他人任务 | 均无入口。 |
| 内置库上传、重建 | Tatoeba 无上传、重建。 |

以上 17 行均符合方案。负责人和编辑者两列尚在执行，暂不判整条通过。
### 用户调整后的执行状态

仅使用独立 headless agent-browser 会话继续，不再使用 Computer Use、桌面、`--headed`、连接 CDP 或 auto-connect。S-17 按用户明确调整，以已完成的 CSV/XLSX 只读文件结构核验判通过，E01 历史环境限制解除；未补称 Office 可视操作。批次 1 当前最终统计为 13 通过、1 失败（P-01 / B01），无阻塞。

P-08 编辑者补充实测已收到，尚待完整 17 行汇总后判整条：headless 恢复后实际建立“P08编辑者规范”（规范数 2）；english-crlf-bom 文献在列表可检索、1 片段；实际上传“P08编辑者词表”，提示 7 词、1 个重复只保留首等级；维基中文频次实际结果“的 26,909、年 10,794、在 8,139”等共 200 行；方法附录实际渲染语料、处理工具、检索、参考文献；设置仍只读。等待特定总计字符串超时但计算已完成，不计产品故障。截图：P-08-41-editor-guideline-created.png、P-08-42-editor-statistics.png、P-08-43-editor-vocabulary-upload.png、P-08-44-editor-method-appendix.png。
P-08 编辑者追加：统计任务 `#12c5bef1` 已完成；术语抽取 `#53e4c0b2` 完成“新增 0 条草稿，跳过 0 条”；规范导入 `#e8920462` 已完成。Tatoeba 内置详情仅文档、元数据，无上传、重建、编辑、删除（P-08-45-editor-builtin-readonly.png）。设置显示成员 5 人、本人“我”、名称禁用，无成员管理、保存、删除、审计。跨成员任务操作仍待完成。
P-08 编辑者列实测（第 16 行待完成，整条未判定）：

| 操作 | 编辑者实际表现 |
| --- | --- |
| 7 个项目页面 | 7 页均实际打开。 |
| 检索、统计、CSV | 维基“翻译”60 / 55 / 34；实际下载 `tmp/browser-test/downloads-editor/检索结果-20261107-1401.csv`（27,581 B）；频次任务 `#12c5bef1` 完成。 |
| 钉住证据 | 第 2 条维基“翻译”KWIC 实际提交 200，证据篮从 1 到 2。 |
| 上传语料、新建子库 | 实际上传 dup-a 到 S-P08 编辑者，1 篇 / 2 句 / 22 词，并创建 P08 编辑者子库；P-08-34-editor-corpus-upload.png、P-08-35-editor-subcorpus.png。 |
| 删除自建库、文档 | 先实际删除 dup-a 文档至 0 篇，再删除本次空库；P-08-37-editor-document-deleted.png、P-08-38-editor-corpus-deleted.png。 |
| 语义索引 | 在本次小库实际建立 2 句语义索引；P-08-36-editor-semantic-built.png。 |
| 新建层、预标、删除层 | 建 P08 编辑者词性（S-GBK），自动预标后手动预标 `#cae1b6cb` 完成，再实际删该测试层；P-08-33-editor-layer-created.png。 |
| 校对 owner 单人层 | N-01 第 3 句 There 按 Enter 仍为建议，进度保持 14 / 494，提示只有创建者和名单内的标注者可以修改；P-08-32-editor-owner-layer-readonly.png。 |
| 抽样编码 | 实际提交 2 命中、甲乙标签集并建立 P08 编辑者抽样层；P-08-31-editor-sample-created.png。 |
| 知识库导入 | english-crlf-bom 文献导入完成，1 片段、可检索。 |
| 术语抽取、新建术语、新建规范 | 手工建中英术语成功；抽取 `#53e4c0b2` 完成“新增 0 条草稿，跳过 0 条”；P08编辑者规范创建成功；P-08-40-editor-terms-extracted.png、P-08-41-editor-guideline-created.png。 |
| 新建笔记 | P08 编辑者笔记正文保存成功；P-08-39-editor-note-saved.png。 |
| 上传词表 | P08编辑者词表为 7 词、1 重复只保留首等级；P-08-43-editor-vocabulary-upload.png。 |
| 方法附录 | 实际渲染成功；P-08-44-editor-method-appendix.png。 |
| 项目设置管理操作 | 名称禁用，无成员管理、保存、删除项目、审计。 |
| 取消、重试他人任务 | owner 任务 `#41f6bbdd` 被 editor 实际取消，editor 重试生成 `#9a971154`；owner 再取消并重试为 `#77a9e9ed`，双方均可操作，无 403 / 5xx；P-08-46-editor-cancelled-owner-job.png、P-08-47-owner-cancelled-editor-job.png。 |
| 内置库上传、重建 | Tatoeba 仅文档、元数据，无写入口；P-08-45-editor-builtin-readonly.png。 |

上述写操作均仅涉及 sol 项目本轮测试数据。
### 当前覆盖快照

方案共 182 条唯一用例；当前已形成结果 64 条：61 通过、1 失败、2 阻塞（C-03、C-32），余 118 条尚未形成结论（含正在执行的 P-08、P-10），不是本轮最终总结。批次 3 加入 G-05 后共 22 条，目前 20 条通过、P-08 与 P-10 待完成；N-01 为提前完成的批次 6 依赖，单独计 1 条，不重复计入批次 3。
P-08 负责人已完成步骤（其余仍待补，不判整条）：

- 实际上传 dup-a、essay-01 到专用 S-P08负责人，2 篇 / 10 句 / 118 词；建立 10 句语义索引；按 p08_role=owner 建子库，规模一致。实际删除 dup-a 后为 1 篇 / 8 句 / 96 词，随后删除本轮专用库；截图 P-08-12-owner-semantic-built.png、P-08-13-owner-delete-document-button.png、P-08-14-owner-delete-corpus-confirm.png。
- 新建 P08负责人词性层并预标成功，另点预标任务 `#d0fb5d40` 成功；已删除该专用层，N-01 层保留。截图 P-08-15-owner-preannotated.png。
- N-01 校对、S-GBK 频次 236 词 / 130 项、维基“翻译”60 / 55 / 34、钉住成功均已实做。
- 术语抽取 `#a82aa0c3` 完成新增 0 草稿；新建 P08负责人术语、P08负责人规范成功。
- 切换 headless 后重做中断词表上传，P08负责人词表为 zh、一级/二级/三级、7 条，已在管理表列出；截图 P-08-16-owner-wordlist-uploaded.png。

负责人 CSV、方法附录、知识库文献与笔记落地核验、抽样、跨成员任务取消重试尚待补齐。
P-08 跨成员任务步骤限定：负责人 Tatoeba 10 段任务 `#4fd1506a` 在数秒内完成，未赶上取消，不据此判定跨成员取消/重试通过，待主执行者后续实际操作证据。P-08-16-owner-wordlist-uploaded.png 已覆盖为实际词表 7 条的正确证据。
P-08 跨成员任务已实际完成双向操作：owner 发起最低频次 2、等分 10 段的频次任务 `#41f6bbdd` → editor 取消为已取消 → editor 重试为 `#9a971154`（发起人 sol-editor）→ owner 取消 → owner 重试为 `#77a9e9ed`，等待自然完成。双方取消、重试均获允许，无 403 / 5xx，后续请求 200 尚待核对。截图：P-08-46-editor-cancelled-owner-job.png、P-08-47-owner-cancelled-editor-job.png。编辑者 17 行已全部实际执行并符合矩阵；P-08 总判仍待负责人其余项。
P-08 跨成员任务网络与收尾已核对：editor 对 `#41f6bbdd` 的 `POST /api/jobs/.../cancel`、`/retry` 均为 200；owner 对 `#9a971154` 的对应取消、重试均为 200，无失败响应或 error.code。最终 owner 重试 `#77a9e9ed` 已自然完成，运行 0、排队 0，无遗留任务。
P-08 负责人剩余项已完成：新 CSV 导出 `#611c7146` 在界面完成后已自动下载，准确文件已收回 `tmp/browser-test/downloads-perm-owner/检索结果-20261107-1429.csv`，只读结构核验 60 数据行 / 16 列 / 34 个文档，文件头 60 次 / 55 句 / 34 篇；后续重复 CLI download 取消不计产品问题；界面抽样 2 条、learner-errors 标签集，创建 P08负责人抽样并进入该层（P-08-19-owner-sample-created.png）；P08负责人文献 MD 可检索、1 片段；重开 P08负责人笔记保留“负责人新建笔记权限测试。”且保存按钮禁用（P-08-17-owner-note-saved.png）；方法附录实际含维基规模、60 / 55 / 34 命中（P-08-18-owner-method-appendix.png）；助手页实际打开，7 页齐全。成员管理、改名、删除恢复、审计、内置只读采用本轮 P-01 / P-03 / P-05 / P-07 / C-29 的真实操作证据，经主执行者确认复用。

P-08 最终权限矩阵（“可”均有实际界面操作或本轮明确复用的同账号操作；门页均为非成员实际打开 7 页后的统一阻断）：

| 操作 | 负责人 | 编辑者 | 标注者 | 查看者 | 非成员 |
| --- | --- | --- | --- | --- | --- |
| 打开 7 个项目页 | 可 | 可 | 可 | 可 | 门页 |
| 检索、统计、CSV | 可 | 可 | 可 | 可 | 门页 |
| 钉住证据 | 可 | 可 | 可 | 403 FORBIDDEN | 门页 |
| 上传语料、新建子库 | 可 | 可 | 无入口 | 无入口 | 门页 |
| 删除自建库、文档 | 可 | 可 | 无入口 | 无入口 | 门页 |
| 建语义索引 | 可 | 可 | 仅句数，无建按钮 | 仅句数，无建按钮 | 门页 |
| 新建层、预标、删除层 | 可 | 可 | 无入口 | 无入口 | 门页 |
| 校对负责人单人层 | 可 | 创建者/名单限制 | 创建者/名单限制 | 查看者只读 | 门页 |
| 抽样编码提交 | 可 | 可 | 403 FORBIDDEN | 403 FORBIDDEN | 门页 |
| 知识库导入 | 可 | 可 | 可 | 无入口、导入卡提示只读 | 门页 |
| 术语抽取、新建术语、新建规范 | 可 | 可 | 无入口 | 无入口 | 门页 |
| 新建笔记 | 可 | 可 | 可 | 无入口 | 门页 |
| 上传词表 | 可 | 可 | 无入口 | 无入口 | 门页 |
| 生成方法附录 | 可 | 可 | 可 | 可 | 门页 |
| 设置成员、改名、删除、审计 | 可 | 名称禁用，无管理入口 | 名称禁用，无管理入口 | 名称禁用，无管理入口 | 门页 |
| 取消、重试他人项目任务 | 可 | 可 | 无入口 | 无入口 | 门页 |
| 内置语料上传、重建 | 无入口 | 无入口 | 无入口 | 无入口 | 门页 |

### 批次 3 小结

本批原 21 条加 R03 补入 G-05，共 22 条唯一用例，全部通过，无失败、无阻塞。P-08 已逐角色完成 17 行矩阵，P-10 角色说明复核通过。A-03 / A-12 的功能正确，重复英文错误码小字合并为探索细节 B02，不将同一现象重复计缺陷。B01 属批次 1，不重复计本批。

恢复情况：sol-disabled 已启用且可按原密码访问；sol-temp 恢复普通账号；临时移除成员已移除、主项目 5 人；项目名已恢复；“Sol 删除测试”恢复、2 成员；双向任务取消/重试后的最终任务已完成、运行 0 / 排队 0。P-08 专用负责人/编辑者语料库及专用词性层已按测试步骤删除，N-01 原层保留，未改动非 sol 账号和项目。

截至本批结束，共 66 条唯一用例已有结果：63 通过、1 失败、2 阻塞（C-03 / E02、C-32 运行数字进度待补）；其余 116 条尚未形成结论。此为阶段快照，后续继续批次 4，不是最终总结。
P-08 负责人 CSV 证据更正并完成独立只读复核：界面导出后文件已自动落入默认 Downloads，主执行者仅移动该精确文件至 `tmp/browser-test/downloads-perm-owner/检索结果-20261107-1429.csv`；27,581 B，标准 CSV 解析为 60 数据行、16 列、34 个独立文档 ID，命中列仅“翻译”，文件头为 60 次 / 55 句 / 34 篇。后续 CLI 的重复 download 取消为工具操作结果，不是产品下载失败。该单文件已收回规定临时目录；后续启动会话显式指定下载路径。

批次 3 小结已完成落盘，按 22 条全部通过；开始批次 4 检索。当前仍保留 66 条唯一结果的阶段快照，不以未执行步骤补造结论。
### 批次 4 检索（进行中）

S-19 已通过，其余检索用例继续执行，不作本批完成结论。
S-14 已测进度：维基“研究”545 次；含“语言”回车后 12 / 9 / 7，不含后 533 / 430 / 138，清空筛选回车后计数恢复 545 / 439 / 141。截图 S-14-1-include-filter.png、S-14-2-exclude-filter.png 可见查询框分别同步为 `研究 +语言`、`研究 -语言`；S-14-3-filter-cleared.png 可见筛选框空及悬浮提示“作为同句条件重新检索全部结果，回车生效”。清空后顶部查询框的最终同步状态待主执行者核对 DOM，尚不判整条或报缺陷。
S-25 未建分支已实测：S-学习者作文未建，显示 41 句、预计约 1 秒、建语义索引按钮，检索按钮禁用（S-25-1-index-not-built.png）；过期分支待批次 9 的 C-27，整条暂不判通过。

C-32 额外合理窗口补观察一次：重建 `#55f40c34` 捕获“建立中 / 排队中”后很快完成 1,146 句，仍未捕获运行 x / y 数字，也未赶上本次取消，不据此扩充覆盖，不反复重建；C-32 仍部分完成 / 阻塞。`C-32-3-rebuild-progress.png` 实为排队帧，`C-32-4-rebuild-running.png`、`C-32-5-cancel-retains-built.png` 实为已建完成帧，均不按文件名推断取消成功。原先批次 2 已实际完成取消保留旧索引的证据和事实独立保留。
S-14 清空后查询同步疑问已解决：主执行者直接查看最终截图，顶部为“研究”，截图前 full snapshot 的 textbox 同样为“研究”；无需重测，整条判通过，早期目视疑虑不作为产品缺陷。
S-25 未建分支发现 B03（一般），独立会话等待动画结束后仍能复现，整条先判失败；已正确显示未建面板并不能掩盖旧 HF 结果仍在的问题。过期索引分支仍待 C-27，不因当前失败跳过后续覆盖；无 500，不需 API 堆栈。当前产品问题为 B01 一般、B02 细节、B03 一般。
批次 4 主执行者分工的 S-13–S-16、S-19–S-21、S-26 共 8 条已全部通过，其余分工继续，不作整批完成结论。
X-02 已执行步骤待主执行者整条判定：界面检索 `spreadsheet` 后 CSV（587 B）、XLSX（5,486 B）均实际下载，精确文件已收回 `tmp/browser-test/downloads-perm-owner/检索结果-20261107-1441.csv`、`检索结果-20261107-1442.xlsx`。文档标题为 `hf-export-nli #10`，沿用 R05。CSV 左语境为 `'=SUM(A1:A2) is how a `；XLSX G4 同值、字符串类型，公式 0、超链接 0，表头宋体、无底色。只完成结构核验，按新 headless 约束未在 Office 可视打开，不声称观察到“无安全弹窗”。截图：X-02-1-formula-text-result.png。
S-18 下载所遇 CLI 路径问题通过统一相同 `--profile`、使用普通界面点击下载解决，不计产品缺陷。始终保持 headless，未使用桌面或 Office 可视操作。
### 批次 4 小结

本批按计划有 24 条尚需执行的唯一用例，实际新执行 23 条：21 通过、2 失败（S-10 / B04、S-25 / B03）。S-23 依赖 N-06，待批次 6 后补，暂未执行、不预判；S-25 已判失败，C-27 后仍须补过期索引分支。C-32 属批次 2 的原阻塞，不在本批重复计数。

X-02 已按用户最新条件以 CSV/XLSX 只读脚本核验判通过，所有 XLSX 均不用 Office 桌面打开，不再受原 E01 可视权限限制。下载与浏览器恢复后的当前做法为：仅在 `tmp/browser-test/` 下使用专用 profile，所有命令固定同一 profile，headless 启动并显式指定下载目录；误落默认 Downloads 的精确测试文件均已收回规定目录。没有遗留系统目录测试文件。

截至本批共 89 条唯一用例已有结果：84 通过、3 失败、2 阻塞（C-03 / E02、C-32 运行数字进度待补）；其余 93 条尚未形成结论，包含待依赖 S-23。产品问题共 4 项：一般 3（B01、B03、B04）、细节 1（B02）、严重 0。此为阶段快照，下一步批次 5，不是最终总结。
### 批次 5 统计（进行中）

T-09 已通过；其他统计方法与导出继续执行，未作本批小结。
T-04 已由主执行者确认方向查询正确，方案回跳数字更正为 R09；完整指标、图表截图待权限执行者汇总后写入整条结果，未按原错误预期报产品问题。
X-03 进度：CSV 五种危险前缀已逐一按字符串核对；同参数 XLSX 已提交，待下载及只读结构核验后整条判定。
X-03 安全判定已通过。整洁 XLSX 的 data 表头已独立核对为宋体（Unicode 23435、20307），此前仅终端编码显示问题，不是产品缺陷。
### 批次 5 小结

本批新执行 18 条唯一用例（T-02–T-18、X-03）：17 通过、1 失败（T-07 / B05、B06）；T-01 复用批次 1 冒烟，不重复计数。统计导出、整洁数据、安全前缀及计算核对已完成；data 表头字体独立核验为宋体。T-11 自编词表已删除恢复，P08 词表与 NGSL 保留；T-15 深色已恢复浅色；T-17 仅删除本轮 sol 统计输出。

截至本批共 107 条唯一用例已有结果：101 通过、4 失败、2 阻塞（C-03 / E02、C-32 数字进度未捕获），其余 75 条尚未形成结论。产品问题共 6 项：严重 0、一般 5、细节 1。此为阶段快照，不是最终总结。
### 批次 6 标注与抽样（进行中）

SP-01 已通过。SP-02 已实际验证空标签 Enter 提示“先选择标签（数字键）”、J / K 移动，首条 1 + Enter 编码后自动到第 2 条；其余编码及汇总待完成，不判整条。SP-03 先记录抽样基线前 5 条句号 42996 / 13925 / 3500 / 20746 / 19559，待复核层实际对比。N-01 已提前完成并在结果表通过，后续不重复计数。
N-06 已确认估算 41 句 / 5 次模型调用，发送至 api.deepseek.com；已建立“偏误”层并提交预标 `#cb7db682`，观察到 30 / 41、73%。列表单位“篇”错误另记 B08，数值异步差异不报。初次外传审批在只读确认五篇均为 synthetic 测试文本后补证通过，原界面动作正常提交，不保留环境阻塞。N-06 后续校对尚在执行，N-03 任务 `#7166c73f` 排队中，均不提前判整条。
N-06 新增严重问题 B10，根因证据为实际焦点保留和纯 modify 的 PATCH 序列，不是模型生成或网络失败。整体先判失败，其他步骤和依赖仍继续。受影响人工片段已通过界面恢复至预定 148–158 并显式确认，不留此次边界改写的未恢复状态；未改其他模型建议。
批次 6 继续：SP-01–SP-05 均已执行，4 通过、1 失败（B09）。N-11 层已建立，本地 MiniLM 预标 `#25074341` 自 15:15:40 运行中、0 / 1 篇，CPU 约 100%、内存约 2.9 GiB 持续计算，未退出或报 500；目标句选择尚禁用，先留后台，不提前判失败。N-06 后续及 N-07 等仍在执行，批次 6 尚未收完。

按耗时任务穿插规则，先执行批次 7 独立的 K-01 文件导入和本地检索，待后台完成再回验标注。标注测试未改动非 sol 数据。
### 批次 7 独立步骤穿插（尚未收批）

- K-01：导入卡一次实际点选 PDF、DOCX、kb-guideline、kb-article-36k 共 4 文件，提示“已提交 4 个文件”（K-01-1-four-imports-submitted.png）；仍排队，待核阶段、最终标题和元数据，不先判通过。
- K-07：实际建立 explicitation / en、译名显化 / zh、定义“译文比原文表达得更明确。”，从证据篮加入 HF #123 例句，提示已加入例句、语料例句 1（K-07-1-term-example.png）；TBX、CSV、XLSX 3 份界面导出已提交（K-07-2-term-exports-submitted.png），待完成与文件核验，不先判通过。
依赖后补：S-23 已在 N-06 人工测试准备后完整通过，批次 4 当前最终为 24 条、22 通过 / 2 失败，无待执行 S-23；不将本条重复计作批次 6。N-14 已通过并恢复层列表展开。N-06 仍因 B10 整体失败；外部预标在有限一次重试后仍有 20 句失败，停止重跑，非本地 API 500，作为环境过程与预标覆盖限定保留，不新增产品问题。
N-12 已完成部分：界面下载 `tmp/browser-test/downloads-permissions/S-学习者作文_词性-20261107-1524.conllu`（21,041 B），只读解析 41 个 sent_id / 494 token、每行 10 字段；首 essay-01-1、末 essay-03-8，无 UUID，人工 My=PRON 生效、拒绝 Hometown 导出 UPOS 为 `_`。导出 busy 结束后多人菜单可正常打开，显示“JSON · 另附各标注者原始标注”（N-12-2-multi-json-menu-after-adjudication.png）；单人片段菜单口径见 N-12-3-single-span-export-scope.png。BRAT `#9cee7c67`、XLSX `#13cca71b` 已提交排队，待 N-08 `#110202e8` 完成后查文件，不重复提交，整条尚待结论。
N-08 进度：重开后两条人工关系仍在，状态已确认、来源人工（N-08-4-saved-relations-reopened.png）；后台 0 / 1 仍观察，整条结论待主执行者确认。
K-02 进度：三模式“什么是显化”均 200，有高 / 低标签，无原始分数；向量 8 项为 1 高 / 7 低并实际展开。固定来源混合预期按 R13 更正，补查询“译文比原文更明确”向量首位返回 DOCX；文档位置 chunk 913 已等待加载，最终定位待确认，尚不判整条。
N-11 后台已自然完成并完整通过，原运行状态观察为历史过程；未因耗时提前判失败。K-07 文件核验已完成，结果表已有通过，不重复计数。
N-09 有限尝试后部分完成 / E03 阻塞，层最终 ready；409 为请求到达时已完成，不凭此报产品取消故障。误建 POS 层已界面清理，真实依存层保留；不存在未恢复的取消副作用或遗留运行任务。未继续重跑以追逐短暂窗口。
### 批次 6 小结

本批覆盖 N-01–N-14、SP-01–SP-05 共 19 条，其中 N-01 提前用于 P-08、N-10 已在批次 2 完成，本批不重复计数。新执行 17 条：14 通过、2 失败（N-06 / B10，SP-05 / B09）、1 阻塞（N-09 / E03）。按完整本批范围为 16 通过、2 失败、1 阻塞。S-23 已依赖后补通过，归原批次 4，不在本批重复计数。

N-06 的严重问题为确认键意外修改人工边界（B10），受影响片段已恢复至预定 148–158 并显式确认；外部模型预标有限重试仍有 20 句失败，保留过程限定，不新增产品缺陷。N-09 真实运行后取消到达时已完成、409，列覆盖阻塞，不冒称已取消或已重试。N-08 人工关系新建、确认、两弧错开及重开保留已通过，可选预标结果后续另记。

恢复与保留：N-04 临时层已按 N-13 删除；误建 POS 层已删除；N-14 折叠已展开恢复；N-11 初次未清空目标已界面纠正为最终未对齐。N-01、偏误、多人与抽样等测试层按后续依赖保留，未改非 sol 数据。

截至本批及已穿插的 K-01 / K-02 / K-07 / K-12，共 129 条唯一用例已有结果：120 通过、6 失败、3 阻塞；其余 53 条尚未形成结论。产品问题 11 项：严重 1、一般 8、细节 2。此为阶段快照，批次 7 继续。
N-08 可选预标后续已成功：written=1 / total=3、failed_sentences=0；worker 执行 07:37:53.348–07:52:18.952，外部 200 响应曾有解码 / invalid format 后有限重试，非本地 500，不新增产品缺陷。K-11 专用笔记防抖实测通过，准备期任务与连续输入期间已区分，未把加载空行截图当最终证据。
N-08 最终界面补核：N-08-5-preannotation-done-relations.png 显示 2 / 3（67%）、新增模型建议虚线与原两人工实线均正常，三层关系标签无重叠。当前已无该任务待观察状态，结果仍通过。
E-02 进行中：owner 已真实 `DELETE /api/projects/<主项目>/evidence?mine=true` 200，篮 11→3；保留 editor 句 8102 / 9842 及先前他人维基证据 1 条，待 editor 刷新最终确认。按钮越界问题另记 B13，用 Shift+Tab / Enter 两次完成界面操作，不以接口代替测试，整条尚待隔离结果。
AS-02 已执行部分：确认前证据篮保持 3；实际点执行后为 4，卡片显示已执行，并正常渲染 2 个工具结果（1 新增、1 已有）。模型说明前两命中对应同句且第二项已有，本次数字与工具结果一致，不把方案固定 +2 当产品缺陷。第三条取消步骤待完成，再整条判定；待更正为按新增唯一证据数验收。
AS-03、AS-04 已提交模型运行，尚待结果，不提前判定。AS-02 已完整通过，新增数字按工具结果而不是固定措辞判断。
AS-04 进度：已读取近义词辨析流程、多项对比及近义词对比，组件三列、31 行，词频 99 / 80、每百万 430.95 / 348.24；调用 Word Sketch 的条件预期按 R17 更正，待组件计数最终核对后判整条。
批次 8 独立全局步骤穿插：H-01、H-02、H-03 已通过；H-01 文献格式已恢复 GB/T，H-02 的专用反馈已提交等待 M-04，不作批次 8 完成结论。
E-04 已开始真实界面准备：维基中文“研究”545 命中，第 1 页实际点击 50 次钉住，篮 7→57，继续第 2、3 页；未用接口或模型代写，不提前判超过 200 的分页结果。
X-05 已测部分：实际上传 `S-<img src=x onerror=alert(1)>` 专用库，1 篇 / 2 句 / 22 词，列表、详情、检索面包屑、命令面板、任务均为字面文字，未生成对应 img / onerror DOM、无对话框或控制台错误；最终证据 X-05-2-corpus-imported-literal.png、X-05-4-command-name-literal.png、X-05-7-search-breadcrumb-literal-final.png、X-05-8-jobs-literal-final.png。脚本字符串反馈实际提交 200（id93），待管理员页核验。仅本例专用库已界面删除 204 并确认移除（X-05-10-delete-own-corpus-confirm.png、X-05-11-own-corpus-deleted.png），未动其他库；整条仍待反馈端结论。
M-01 本次步骤 1–4 已完成并恢复：admin 按 sol-owner 搜得两项目、列完整；仅 Sol 删除测试实际改派给 editor，两会话设置分别显示原 owner 为编辑者、editor 为负责人。立即改派回 owner 后，因自动加入 editor 使成员 2→3，再仅移除本次新增关系恢复 owner + viewer 原 2 人，主项目未变。截图 M-01-1-owner-project-filter.png、M-01-2-reassign-confirm.png、M-01-3-reassigned.png、M-01-4-old-owner-now-editor.png、M-01-5-editor-now-owner.png、M-01-6-owner-restored-admin.png、M-01-7-owner-restored-settings.png、M-01-8-editor-role-after-restore.png、M-01-9-original-members-restored.png。步骤 5 在 A-09 期间已有实际不可选停用账号证据，是否复用待主执行者确认，暂不整条判定。
J-06 正在补两次小统计与任务托盘观察；J-01–J-04 由导入执行者继续，尚未收批次 8。
AS-10 管理端用量已核：2026-11 按用户 sol-owner 为总 1,771,350 token = 提示 1,659,284 + 生成 112,066，81 调用；实际切按项目 Sol 浏览器测试为同数（AS-10-3-admin-usage-by-user.png、AS-10-4-admin-usage-by-project.png）。与先前 AS-01 前 38,546 基线相比已增加，账号页最终值仍待主执行者核对后整条判定。
### 批次 7 小结

按当前唯一结果表程序核对，本批 K-01–K-12（K-05 留批次 9）、E-01–E-05、AS-02–AS-12 共 27 条：23 通过、4 失败（K-09 / B12、AS-04 / B14、AS-05 / B16、AS-08 / B15），0 阻塞。已穿插提前完成的本批项只在全局唯一表计一次。

AS-10 owner 页实际增至 1,514,397 token，后续 admin 为 1,771,350，采样间有后续调用，非用量差错。模型型用例按能力调用、组件和工具数字判断，不以措辞比较；有效空候选、既有证据、条件调用等已分别作方案更正。

恢复情况：K-10 已载入最新并保留 B 修改和 A 本地文本；AS-08 补测运行已真实停止恢复；E-02 清空仅影响 owner 项，editor 两项保留；E-04 207 条本轮测试证据保留复查；所有 Office 文件只读结构核验，未使用桌面。K-05 长文摘要待批次 9，未提前判定。

截至当前含已完成的独立全局项，共 166 条唯一用例已有结果：153 通过、10 失败、3 阻塞；其余 16 条待结。产品问题 16 项：严重 1、一般 13、细节 2。此为阶段快照，批次 8 继续。
批次 9 前置准备：C-26 在 S-去重（1 篇 / 2 句 / 22 词）新建本轮删除校验词性层，实际确认 Corpus / linguistics / studies 共 3 词，进度 3 / 22（14%）；从编辑器钉 1 句，篮 207→208（C-26-1-prepared-three-manual.png）。尚未执行删除，待批次 8 收完后做影响检查，不提前判 C-26。
### 批次 8 小结

本批 U-03 留至批次 9，当前 J-01–J-07、M-01–M-07、H-01–H-05、X-04–X-05、U-01 / U-02 / U-04 / U-05 / U-06 共 26 条，程序核对 25 通过、1 阻塞（J-04 / E04），0 失败。J-04 主执行者最后用同一 CLI 脚本提交、托盘、目标详情不到 2 秒，新任务初帧尚无取消按钮，随后 2.5 秒完成，未发 cancel；有限补验停止，不将未覆盖断言冒作通过或产品缺陷。

恢复与收尾：J-03 导入重试及自动索引已完成；J-04 所有尝试已完成，无运行残留；M-01 负责人和原 2 成员已恢复；sol-disabled 启用不变；M-07 内置开关已关闭；X-05 专用库已删除、反馈按用例保留；窗口恢复 1440 × 900、浅色模式恢复。H-02 专用反馈已由 M-04 标记处理，未处理其他用户反馈。

截至当前 178 条唯一用例已有结果：164 通过、10 失败、4 阻塞；仅 C-26、C-27、K-05、U-03 共 4 条待结，进入批次 9。当前产品问题仍 16 项（严重 1、一般 13、细节 2），本段为阶段快照，非最终总结。
### 批次 9 收尾（进行中）

C-26 已通过，按用例永久删除本轮 S-去重 测试库；证据保留，学习者文档取消删除、未受破坏。K-05 已实际上传指定长文 666,606 B，文档 ac1d1e0a、任务 761016a7，向量化 747 片段（已观察 128 / 747），待可检索后再摘要，不提前判定（K-05-1-long-document-importing.png）。
K-05 更新：导入完成 747 片段、标题语料库翻译学综述（长篇），实际确认生成摘要及发送说明，`POST /api/kb/documents/ac1d1e0a-37ce-4842-bac2-723365af33ec/summarize` 200，任务 `109babed` 于 16:44:00 提交；托盘已观察 5 / 21、24%（K-05-4-twenty-one-step-progress.png），待最终 20 段及全文截断说明，仍不提前判定。
C-27 已完成删除、自动重建及 spreadsheet 0 命中，瞬态提示未捕获列 E05；不再删除额外文档。S-25 过期分支已补完整：显示旧索引 1,146 句 / 当前 1,145 句、文档有增删需重建，实际查询“A researcher studies translation.”成功渲染结果表和过期标签，未另数本次行数，不写默认 50。整体仍为原 B03 失败。K-05 已完成并通过，无遗留外部摘要任务。
U-03 停 API 测试窗口后的独立只读服务核验：Compose corpus 的 api / postgres / worker / worker-light 均 running、healthy，agent / web running；`/api/health` 为 `{ok:true,db:true}`。仍待执行者核对中文提示、实际重试及临时额外词元状态，尚不判 U-03、不结束报告。仓库只读状态仅新增本结果文件，业务代码、配置、测试及其他文档未改，tmp 保持忽略。
U-03 最终实测事实待判：仅停 corpus-api-1，并以 try/finally 同 Compose 启动恢复，health 为 ok / db true、服务 running / healthy。停机后实际 `POST /api/layers/1aeb59f4.../annotations` 502（38984.5417），nginx HTML、无 error.code，非 API 500，无 /app 堆栈；There 修改未持久化，回 11 处待确认。中文错误提示瞬时未捕获，首失败截图过早，不宣称看到期望原文，也不再次停机补图。

恢复期间一次 Enter 误确认 are，已真实点本句重置、确认后 POST reset 200，are 恢复建议 / 语料自带、11 待确认（U-03-4-reset-are-confirm.png、U-03-5-are-restored-to-suggested.png）。随后明确选 There、Enter，annotations 200，重新选中显示已确认 PRON / 语料自带·人工确认、10 待确认（U-03-6-there-retry-confirmed-final.png）；最终层 15 / 494、确认 14 / 修改 0 / 拒绝 1、VERB 已确认 0（U-03-7-final-manual-count.png），仅 There 新增、are 已恢复。U-03-3 为误确认 are 的中间图，不作为 There 成功证据。最后状态待主执行者决定，不提前写完成。
U-03 主执行者决定作仅一次有区别的补核：同脚本停 API、真实触发失败、延迟 700–1000 ms 读取实际提示和截图、finally 启动并验健康；恢复后不确认 are，只核建议和 15 / 494 不变。不作第三次停机，等待最终证据，本报告仍执行中。
### 批次 9 小结

本批 C-26、C-27、K-05、U-03 共 4 条：3 通过、1 阻塞（C-27 / E05），0 失败。C-26 删除影响与人工保护正常，保留原证据；C-27 自动重建和删除项 0 命中正常，仅更新中瞬态提示未捕获。K-05 的 20 / 22 段截断明确且摘要完成。U-03 真实中文提示、修改未保存、恢复后重试和最终标注状态均已补齐，API 已恢复健康。

## 最终总结

全部 9 批已执行并逐批留档。用例按编号去重后共 182 条：**通过 167、失败 10、阻塞 5、未执行 0**。全部计划编号均在结果表，无额外或重复编号。失败不等于问题条数：同一用例可有多项问题，部分探索问题不影响原用例主体判定。

产品问题 **16 项：严重 1、一般 13、细节 2**。严重问题 B10 会使确认键意外改写人工标注边界；本次受影响边界已通过界面恢复。已知限制和方案更正不计产品缺陷。本轮未修改业务代码、配置、迁移、测试或其他文档，也未提交或推送 Git；问题均为记录，未修复。

5 条阻塞均有已执行步骤及截图，不当作产品失败：

| 用例 | 未完成断言 | 已确认的实际结果 |
| --- | --- | --- |
| C-03 / E02 | 真实本地文件拖入去重分支 | 重复点选去重正确；CLI 无本地文件拖入参数，未用 JS 合成拖放。 |
| C-32（覆盖限制） | 建索引运行中的 x / y 句进度 | 建立完成、取消重建后旧索引保留已测；只捕获排队 / 已建，未冒称看到数字运行进度。 |
| N-09 / E03 | 取消成功后的层失败和重试 | 实际运行后取消到达时已完成、409；层 ready，有限尝试后停止。 |
| J-04 / E04 | 5 秒内取消及统计页结束态 | 统计在 2.5–5.3 秒内完成，按钮窗口未完整覆盖；P-08 同类取消 200 可参考但不替代本条断言。 |
| C-27 / E05 | 索引更新中瞬态提示 | 删除准确测试文档、自动重建完成、spreadsheet 0 命中；未捕获更新中提示，不额外重删。 |

恢复已完成：API、数据库、worker、worker-light 健康，agent / web 运行，API health 为 ok / db true；停用账号已启用、临时管理员已撤销、负责人和成员已恢复、临时软删项目已恢复、窗口与主题已恢复。U-03 额外 are 确认已重置，There 的明确重试确认保留，最终 15 / 494、确认 14 / 修改 0 / 拒绝 1。用例指定永久删除的本轮语料、文档、临时层和词表按记录执行；测试证据和剩余 sol 测试数据保留复查，未改非 sol 账号及其数据。没有无法恢复的副作用。

浏览器最终执行遵循用户调整：仅独立 headless agent-browser，所有命令固定专用 tmp profile；不再使用 Computer Use、桌面、headed、连接 CDP 或 auto-connect。Office 文件仅只读结构核验。误落默认下载目录的精确文件已收回 `tmp/browser-test/`，未把密钥、密码或会话值写入报告。

### 优先修复

1. **B10（严重）**：片段确认键再次激活边界按钮，意外改写人工标注。
2. **B06（一般）**：分布回查丢失文档位置筛选，7 命中行回到全查询 60 命中。
3. **B12（一般）**：笔记证据追加不去重，正文更新滞后。
4. **B14（一般）**：助手近义词卡将正式 31 行显示成 29 行且无部分说明。
5. **B03（一般）**：切换至未建语义索引语料后仍显示旧库结果及上下文。

B16 的助手会话 / 页面范围提示问题紧随；其他问题详见 B01–B16 问题表。以上为实际问题及修复优先级，未实施代码修改。

### 方案更正列表

以下 23 项均不计产品缺陷；测试结果采用实际界面、现有契约和用户最新执行条件判断：
- **R01（C-28 / 批次顺序）**：批次 1 先执行 C-28 第 1、2、4 步；第 3 步应在批次 2 的 C-06 导入完成后补测。 C-28 第 3 步依赖 S-HF 导出，但方案将 C-06 排在批次 2，批次 1 无法完整执行。本项为方案依赖顺序更正，不计产品缺陷。
- **R02（C-05 / 元数据输入）**：无效 JSON 先修为 `{}`，再切换字段表并验证重复字段及缺字段名。 无效 JSON 直接切换时保留输入与错误，防止未解析内容丢失，属于合理保护；原步骤需补操作，不计产品缺陷。
- **R03（G-05 / 批次顺序）**：将 G-05 补入批次 3 的引导回归。 第五节执行顺序表未列 G-05，本轮已补实际执行，未新建项目；非产品缺陷。
- **R04（P-11 / 并发限流）**：22 个并发请求应核对 20 次成功、其余 429，按服务端到达顺序判定，不按客户端循环编号。 实测 20 个 200、2 个 429，429 循环编号为 19、21，编号 22 为 200；并发到达次序可不同，限额实际正确。
- **R05（C-06、C-27、X-03 / CSV 文档标题）**：CSV 导入标题按统一去扩展名规则使用 `hf-export-nli #n`，相关查找以此为准。 实际标题为 `hf-export-nli #10` 等，与 TXT 同样去扩展名；方案写为 `.csv #n` 有误，不是正文或元数据丢失。
- **R06（S-13 / 译文条件错误文案）**：字段下的 inline 错误为“第 11 个字符：$ 后应为数字，如 $3 或 $2-5”，无需额外“译文条件”前缀。 提示就在译文条件框下，错误字段和字符定位准确；原方案将前缀也写入预期，属于轻微文案预期更正，不计产品缺陷。
- **R07（S-11 / 无片段层前置）**：第 2 步改在当时无片段层的维基英文补测，其他步骤仍使用维基中文。 批次 3 的 P-08 已为维基中文创建“P08负责人抽样”片段层，此时片段查询可检索为正常行为；应在实际无该层的语料核验提前报错，不计产品缺陷。
- **R08（T-09 / 作文词数估计）**：样本实际 5 篇词数为 78–97，替代方案估计的“约 78–93”。 实际每篇数值已核对，仍全部不足 100，短文指标适用说明正确；近似范围差异不作为产品计数缺陷。
- **R09（T-04 / 搭配回跳方向计数）**：奥德赛共现总频次 3；“右侧”回跳应为 1 次，反向左侧为 2 次，1 + 2 = 3。 右侧 `翻译 $4 "奥德赛"` 在句 201 为 1 次；左侧在句 172 为 2 次。原方案将总共现 3 当成右侧命中 3，产品方向查询正确，不计缺陷。
- **R10（T-05 / 同库参照校验）**：实际为参照菜单排除当前目标；目标变更若与参照重合，自动清空参照并提示“请选择参照”。 防护发生在选库阶段，比方案期待“参照与目标相同”更早，避免同库提交有效，不计产品缺陷。
- **R11（T-07 / 柱图交互）**：点柱先选中、高亮对应表行，再点击该行“回到例句”。 柱本身不直接导航属于实际交互设计，原方案步骤应细化，不因此报缺陷；表行回跳缺少区间过滤另记 B06。
- **R12（T-08 / 默认最低频次期望）**：前列词应以默认最低频次 2 过滤后的实际 8 项为准，不强求 translated 出现。 样本另一处 translated 对应中文“直译”，不匹配“翻译”；匹配 7 句中仅 1 次，按参数过滤正确。
- **R13（K-02 / 固定来源预期）**：检索不强制同一 top 8 同时出现 DOCX 与综述；用对应内容查询补验 DOCX 可返回、文档可定位。 三模式实际排序均可检索，向量 top 8 为综述片段；“译文比原文更明确”向量查询 DOCX 首位返回，固定来源混合不是检索排序契约。
- **R14（E-01 / 共享证据判重操作）**：正常刷新页面中同条已显示“已钉”，再点会移出；需两会话旧 DOM 竞争提交同条，验证 existing=true 与已在提示。 共享篮状态会同步，不能把“已钉”的移出按钮误作再次钉住。实际旧页面竞争请求已确认去重正常。
- **R15（AS-02 / 执行后证据计数）**：增量应等于工具结果中的唯一新增数，已有 / 重复项不再新增，不固定要求 +2。 本次两工具结果为 1 新增、1 已有，篮由 3 变 4，取消后不变；P08 已有同句证据，按工具实际结果核对正确。
- **R16（AS-11 / 保存笔记标题）**：保存回答默认沿用会话标题，实际直接保存成功，不固定为“助手回答”。 本次新笔记标题沿用“统计维基百科中文里 翻译的搭配词，前10个，条形图展示logDice”，内容表格正确保留，非保存失败。
- **R17（AS-04 / Word Sketch 调用）**：按本地近义词流程，仅需完整画像时额外调用 Word Sketch，不强制每次比较都调用。 本地 skill 第 4 条有明确条件；本次已读取流程并执行多项对比、近义词对比，调用必要能力即可，数字和组件另核。
- **R18（K-06 / 词性模式候选前置）**：S-TMX 小样本可有效返回 0；为核验有草稿、语料来源和例句分支，补一次现有 S-HF 词性模式抽取。 S-TMX 没有出现 2 次以上的词性组合，空候选提示正确；不能固定期待新增草稿，补 S-HF 后 12 项有例句并可确认。
- **R19（U-06 / 关闭焦点）**：模态关闭后焦点落 BODY，不要求回新建层按钮；随后点词元 Enter 不重开即可。 doc/change-log.md:128 的 Q46 既定处理为避免 Enter 再次触发顶栏按钮；当前真实行为符合该决定，方案焦点返回预期应修正。
- **R20（J-02 / 小导入排队预期）**：小于默认 5 MB 的导入同属短 lane，按 FIFO 与统计共享队列，不要求统计越过已提交小导入。 只读 jobs.py short_lane 与实际日志均验证：worker-light 正常处理统计，未被重导入阻塞；原方案将小语种样本也当成长队任务不准确。
- **R21（M-03 / 登录失败审计）**：切登录失败前清除 sol-admin 筛选；本轮已知邮箱失败的操作人实际显示该邮箱，不固定要求系统或空。 筛选和操作对象实际正确，邮箱展示更明确；原预期写死身份文字，不计产品缺陷。
- **R22（M-05 / Worker 历史心跳）**：核对当前 worker / worker-light 两容器正常；允许 workers[] 保留历史心跳条目，不要求界面只有两行。 contracts/p9 的历史数组允许多行，另 22 旧记录无响应不等同当前容器停机。
- **R23（M-07 / 内置标签位置）**：内置标记可在任务详情头核对，不固定要求表格行标签。 实际已列内置任务，详情明确内置，开关恢复正确；仅标签位置不同。

最终数字由计划与唯一结果表程序核对；历史阶段快照保留时间顺序，旧的尚待说明以其后完成记录和本最终总结为准。


## 回归（修复后）

### 环境

| 项目 | 实际环境 |
| --- | --- |
| 日期、执行人 | 2026-11-08，sol |
| 测试地址 | http://127.0.0.1:8088 |
| 代码版本 | HEAD `d731a34`，工作区含未提交修复；测试栈已由用户用新代码重建。 |
| 浏览器与工具 | agent-browser 0.33.0，headless，1440 × 900。 |
| 账号与隔离 | sol-owner@example.edu、sol-editor@example.edu；独立会话 `sol-r-owner`、`sol-r-editor`，配置文件分别为 `tmp/browser-test/profiles/sol-r-owner/`、`tmp/browser-test/profiles/sol-r-editor/`。 |
| 执行约束 | 仅 headless agent-browser；未连接用户浏览器，未使用 CDP、auto-connect、Computer Use 或桌面程序。下载产物只读结构核验。 |
| 证据目录 | `tmp/browser-test/shots/`；截图按 `<用例>-R<序号>-<简述>.png` 命名。 |

### 用例结果

原问题表 B03、B06、B10、B12、B14 保留；本节记录修复后的回归结论。

| 用例 | 结果 | 备注 |
| --- | --- | --- |
| S-25 / B03 | 已修复（回归通过） | S-HF 导出检索 `A teacher explains the meaning of a poem.` 返回 50 条，打开首条 HF #831 上下文后切换 S-学习者作文：旧结果与上下文立即清空，输入句子保留；当前索引面板为未建、41 句。截图：S-25-R1-before.png、S-25-R2-cleared.png。 |
| T-07 / B06 | 已修复（回归通过） | 维基百科中文 1000 篇，查询 `翻译\|翻譯`、文档位置 10 区间；10–20% 行为 7 命中，回到检索为 7 次 / 7 句 / 6 篇，显示“临时筛选 · 文档位置 10–20%”。分解（分组入口）、抽样编码、整洁数据导出、分布与语义入口禁用且带说明；另在 Tatoeba 补验统计译法禁用，悬停“文档位置区间仅用于查看例句”。清除标签后各入口恢复，维基全查询恢复 60 / 55 / 34。CSV、XLSX 导出任务均 succeeded，两个下载接口只读 GET 200；两格式均 7 行数据、两行文件头与字段头一致，首行含文档位置 10–20%；XLSX 130 个已存储单元格 fillId=0、A4:P4 字段标题宋体。原生 CLI 下载在此环境返回 canceled，改为同源只读 GET 原下载接口保存并核验，不声称完成桌面可视验收。截图：T-07-R1-distribution.png、T-07-R2-position-search.png、T-07-R3-disabled.png、T-07-R4-cleared.png、T-07-R5-parallel-disabled.png。 |
| N-06 / B10 | 已修复（回归通过） | 用临时手工片段层隔离数据：真实鼠标拖选 informations 147–159，鼠标起点 +1、终点 −1 后为 148–158；Enter 仅确认，Shift+Enter 整句确认并到第 5 句，返回第 4 句仍为 148–158。另将终点鼠标左移至 157，Tab 再 Shift+Tab 回到终点左移按钮，Enter 后为 156，键盘焦点按钮仍可触发。恢复 148–158 后删除临时层，原偏误层未改。截图：N-06-R3-after-shift-enter.png、N-06-R4-tab-boundary.png。 |
| K-09 / B12 | 已修复（回归通过） | 临时笔记“Sol-R-K09-证据追加”先插入 1 条 Corpus linguistics 证据；证据篮显示 208、本次界面载入 200 条，加入现有笔记后立即正文 200 块、引用 200，无重复。删除首块后为 199 块，再加入提示“已加入笔记「Sol-R-K09-证据追加」1 条，199 条已在笔记中，已跳过，打开笔记”，正文立即补回 200 块；再次全部已有时提示“均已在笔记「Sol-R-K09-证据追加」中，打开笔记”。临时笔记已删除，原笔记未改。截图：K-09-R1-appended.png、K-09-R2-restored-block.png、K-09-R3-all-existing.png。 |
| AS-04 / B14 | 已修复（回归通过） | UD 英文 EWT 比较 big、large，步骤含读取“近义词辨析”研究流程。正式统计 `559bdd49-9224-4b97-b5bf-a0c4ecc68248` GET 200、row_count=31；卡片 DOM 为偏 big 13 行、共同 1 行、偏 large 17 行，共 31 行，逐行 freq_a / freq_b / diff 与正式结果一致（显示值按两位小数四舍五入）。原漏项 large 并列（0 / 2、−12）与 US than+N（0 / 2、−13.19）均已显示。B14 卡片修复通过，同轮回答正文数字另有 B18，整个回答不能判为全部通过。截图：AS-04-R1-all-31-rows.png。正式结果已归档后删除，归档见 `tmp/browser-test/AS-04-R-evidence.json`、`tmp/browser-test/R-stat-evidence.json`。 |
| A-01 登录抽查 | 通过 | sol-owner 正常登录后进入主项目语料库页，无改密页。该账号已完成引导，本轮未重置首次登录条件，不重复判定首次引导分支。截图：A-01-R1-login.png。 |
| S-01 | 通过 | 维基百科中文 1000 篇，三组查询“翻译”“研究”“研究 $3 方法”分别为 60 / 55 / 34、545 / 439 / 141、3 / 2 / 2，与预期一致。截图：S-01-R1-counts.png。 |
| N-01 键盘流抽查 | 通过 | 临时词性层新建后 Enter 不重开对话框；My 确认、Hometown 改为 ADJ 后拒绝，J → Shift+Enter → K 后第 2 句已完成、0 处待确认，进度即时更新。临时层已删除。截图：N-01-R3-completed.png。 |
| K-10 | 通过 | owner、editor 独立浏览器同时打开临时笔记；editor 追加 B / B2 并保存，owner 旧版本追加 A 后返回 409 并显示冲突处理。复制本地内容、载入最新版本后，正式正文含 B / B2、不含 A，只读本地内容保留 B + A，未覆盖他人修改。临时笔记已删除。截图：K-10-R2-conflict.png、K-10-R3-latest-loaded.png。 |
| E-01 | 失败 | B17：未载入的既有证据误显示“钉住”；点击后服务端 existing=true、总数仍 208，界面却从 208 增至 209，刷新才恢复。未新增服务端记录。截图：E-01-R3-existing-unloaded.png、E-01-R4-count-inflated.png。 |

### 新发现问题

| 编号 | 页面/功能 | 严重度 | 现象 | 复现步骤 | 期望 | 截图 | 控制台 / 网络错误 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B17 | 证据篮 / 分页证据钉住与计数 | 一般 | 证据篮共 208 条、界面仅载入首 200 条；位于第 2 页的既有证据句 8102“我在翻译。”在检索行误显示“钉住”。点击后提示“已在证据篮中”，胶囊却由 208 增至 209；只读分页 GET 的 total 仍为 208，未新增记录，刷新后胶囊恢复 208。 | sol-owner 登录主项目 → Tatoeba 中文侧检索“翻译” → 找到句 8102“我在翻译。” → 点击行尾“钉住” → 对照胶囊与分页 GET 总数。原证据 `7980a364-3e30-44ad-8fee-b625b8ef64b7` 由 sol-editor 创建，本轮未改其记录。 | 未载入页面的既有证据也准确显示已钉状态；返回 existing=true 时不得增加项目总数。 | E-01-R3-existing-unloaded.png、E-01-R4-count-inflated.png | `POST /api/projects/e6b68bfd-c5ba-4de3-81ce-8a180fb439a6/evidence` 200、existing=true，返回同一证据 ID；只读分页 GET 200、total=208；无 500 或控制台错误，error.code 不适用。 |
| B18 | 助手 / 回答正文统计口径 | 一般 | 同轮 SketchDiff 卡片为 31 行（偏 big 13、共同 1、偏 large 17），正式 row_count=31；回答正文却写“共34个搭配里只有1个（主语it）几乎无差异”，总数与正式结果不一致。 | sol-owner → UD 英文 EWT → 新对话发送“比较 big 和 large 的用法” → 对照近义词卡、正式统计结果与回答正文。本次观测已复现；模型输出每次不同，未断言每次必现。 | 回答正文引用的统计数字与正式统计结果一致。 | AS-04-R3-summary-34-vs31.png | `GET /api/stats/559bdd49-9224-4b97-b5bf-a0c4ecc68248` 200、row_count=31；无 HTTP 失败，error.code 不适用。统计结果已归档到 `tmp/browser-test/AS-04-R-evidence.json`、`tmp/browser-test/R-stat-evidence.json`，随后删除。 |

### 清理与限制

临时词性层、片段层已删除；只读 GET 项目标注层 total=11，无本轮 Sol-R 临时层。临时笔记已删除，GET 返回 404，笔记总数恢复 7。新建助手会话已删除（204）。本轮分布、多项对比、SketchDiff 三个统计结果已归档到上述 JSON 后删除（204），导出任务记录及下载核验文件保留为测试证据。

证据篮只读 GET 最终 total=208。清理时受 B17 的显示误导，将原有 sol-owner 的 Tatoeba 句 547、1295、2856 三条证据误当作新增移出；发现后已由原账号按相同内容重新钉住，内容、创建人和总数恢复，但三条记录 ID 与创建时间已更新。新 ID 按上述句序依次为 `5ecc16f0-a4cc-4563-8b5d-db74a694f84c`、`39cc4c5a-b7bc-4b3b-a44d-51a4abd41223`、`8310b081-d776-4d63-a3f6-fd511450f17d`。不将此轮数据状态描述为完全未改动。

浏览器会话 `sol-r-owner`、`sol-r-editor` 均已执行 close 成功。启动排障会话 `owner` 关闭时多次出现守护进程配置冲突；主执行者核验 PID、headless / profile 参数及父进程后，仅停止该会话自己的 headless Chrome 与专属守护进程，再次执行 `agent-browser --session owner close` 返回“Browser closed”。本轮打开的所有 agent-browser 会话均已关闭。

本轮五个原缺陷的指定修复行为均回归通过；邻项 E-01 失败，新发现 B17、B18 均为一般问题，不能据此宣称本轮全部验收通过。

## 第二轮回归

### 环境

| 项目 | 实际环境 |
| --- | --- |
| 日期、执行人 | 2026-11-08，sol |
| 测试地址 | http://127.0.0.1:8088 |
| 代码版本 | HEAD `f3ef39a`，工作区含未提交修复；测试栈已由用户用新代码重建。 |
| 浏览器与工具 | agent-browser 0.33.0，HeadlessChrome 156.0.0.0，1440 × 900。 |
| 账号与隔离 | sol-owner@example.edu：`sol-r2b-owner` / `tmp/browser-test/profiles/sol-r2-owner/`，`sol-r2b-auth` / `tmp/browser-test/profiles/sol-r2-auth/`；sol-editor@example.edu：`sol-r2b-editor` / `tmp/browser-test/profiles/sol-r-editor/`。 |
| 执行约束 | 仅 headless agent-browser；未访问 8080，未使用 Computer Use、桌面程序、`--headed`、CDP 或 auto-connect。 |
| 证据目录 | `tmp/browser-test/shots/`；新截图按 `<用例>-R2b-<序号>-<简述>.png` 命名。上次中断草稿与 R2 截图仅作参考，本节结论均已重新核实。 |
| 开始前状态 | 只读查询 sol-owner 的 17 个助手对话，运行中为空，无需停止残留任务。 |

### 用例结果

原问题表与第一轮回归记录保留。13 个指定问题中，12 个已修复（回归通过），B05 未修复；B18 两次独立执行均通过。8 个相邻功能抽查均通过。

| 用例 | 结果 | 备注 |
| --- | --- | --- |
| P-01 / B01 | 已修复（回归通过） | 空值提示“请输入邮箱”，`bad-email` 提示“邮箱格式不正确”。临时移除 sol-viewer 后，输入精确值 `  SOL-VIEWER@Example.edu  ` 添加成功，立即恢复原查看者角色，最终仍为 5 人。截图：P-01-R2b-1-invalid.png、P-01-R2b-2-restored.png。 |
| A-03、A-12 / B02 | 已修复（回归通过） | 登录限流仅显示“登录尝试过多，请 1 分钟后再试”；改密错误与限流分别仅显示“原密码不正确”和同一中文限流提示，无 `WRONG_PASSWORD`、`LOGIN_RATE_LIMITED` 小字。A-03 恢复登录核验时距最后限流约 114 秒（提交略早）；A-12 等待超过 60 秒（约 2 分钟）后退出，用原密码登录成功。所有改密均为错误原密码失败提交，实际密码未变。截图：A-03-R2b-2-limited.png、A-03-R2b-3-recovered.png、A-12-R2b-1-wrong.png、A-12-R2b-3-limited.png、A-12-R2b-4-recovered.png。 |
| S-10 / B04 | 已修复（回归通过） | UD 中文 GSD `{dep=nsubj}` 为 8,383 次 / 4,302 句 / 2 篇；首行“依存树”可展开原生树，40 条弧线与 2 个 `nsubj` 标签可见，命中词“他們”有高亮类 `dtk hl`、背景 `rgb(254,247,195)`。只读，无“在标注中打开”或编辑控件。截图：S-10-R2b-1-native-tree.png。 |
| T-07 / B05 | 未修复 | 10 区间图 SVG 为 598 × 220，标签清晰；50 区间图仍为 598 × 220，33 个非零数值标签有 13 对边界矩形重叠，例如 61.9 / 63.7、63.7 / 63.8、127.7 / 127.4。表格完整显示 50 行，多柱图标签仍冲突。截图：T-07-R2b-1-ten-bars.png、T-07-R2b-2-fifty-bars.png。 |
| N-02 / B07 | 已修复（回归通过） | 原词性层编辑页文档下拉与统计“文档进度·句”逐项一致：essay-01 为 2 / 8、essay-04 为 0 / 8、essay-02 为 0 / 8、essay-05 为 0 / 9、essay-03 为 0 / 8。层进度 15 / 494、确认 14、拒绝 1；未修改原层。截图：N-02-R2b-1-editor.png、N-02-R2b-2-stats.png、N-02-R2b-3-document-list.png。 |
| N-06 / B08 | 已修复（回归通过） | 片段、词级、关系预标均在实际界面显示“句”。片段从 0 / 41 推进至 10 / 41，任务 done=10、total=41、unit=句；词性层维基英文显示“预标中 2,262 / 37,383 句”，随后任务 done=2,901、total=37,383、unit=句（轮询时点不同）；关系层显示“预标中 0 / 4 句”，任务 total=4、unit=句。临时层均已按 ID 删除；片段和词级任务 cancelled，关系任务清理时已 succeeded。截图：N-06-R2b-2-progress.png、N-06-R2b-3-progress.png、N-06-R2b-5-token-progress.png、N-06-R2b-7-relation-progress.png。 |
| SP-05 / B09 | 已修复（回归通过） | 复用既有抽样层，独立“3 检索”节含 Tatoeba 中英 / 中文侧、查询 `翻译\|翻譯`、84 次 / 79 句 / 1 篇文档，与重新检索 `POST /api/search` 的 200 响应（complete=true、hits=84、sentences=79、documents=1）一致。检索页第三卡为 79 句对，单位不同；另含 n=20、seed=42、总命中 84 与 Wilson 1927。方法说明请求状态未捕获，重开使用缓存，不宣称其 HTTP 状态；既有层未改。截图：SP-05-R2b-1-method.png、SP-05-R2b-2-search-counts.png。 |
| K-02 / B11 | 已修复（回归通过） | 向量检索“什么是显化”POST 200；展开 7 条低相关结果，长篇综述摘要正常显示 `Cohen's kappa`、`Krippendorff's alpha`，DOM 无 `&#x27;`、`&#39;`、`&amp;`、`&lt;`、`&gt;` 实体文本。截图已视觉核验，未修改业务数据。截图：K-02-R2b-1-expanded.png。 |
| E-02 / B13 | 已修复（回归通过） | 208 条证据的面板底部“加入笔记 / XLSX / DOCX / 生成方法附录 / 清空我钉的”分两行（y=759、791），最右边缘 1403 < 1440，按钮均可用。实际点击清空进入“确认清空我钉的”，立即 Esc 取消，未删除证据。截图：E-02-R2b-1-footer.png、E-02-R2b-2-confirm-cancel.png。 |
| AS-08 / B15 | 已修复（回归通过） | 同账号三个标签在不足 1 秒内发送，前两个正常运行，第三个消息 POST 429、`TOO_MANY_RUNS`；界面显示“已有 2 个对话在运行，请等待完成或停止后再试”，输入原文完整保留。界面停止第一个后第三个重发 200、进入思考；再停止另外两个，三会话均确认 idle 后按 ID 删除。截图：AS-08-R2b-1-third-rejected.png、AS-08-R2b-2-retry-running.png。 |
| AS-05 / B16 | 已修复（回归通过） | Tatoeba 中文侧“翻译”84 次结果选首行，打开助手并发送“当前结果里有几条是动词用法？举两个例子。”；仅用面包屑切到 UD 英文 EWT，未重新检索，即显示“会话范围：子库「Tatoeba 中文侧」；当前页面：UD 英文 EWT”及“按当前范围新对话”。点击后新空对话使用 EWT 范围。截图：AS-05-R2b-1-running.png、AS-05-R2b-2-mismatch.png、AS-05-R2b-3-new-scope.png。 |
| E-01 / B17 | 已修复（回归通过） | 证据总数 208、尾页 8 条旧记录；未载入首 200 条的句 8102 准确显示“已钉”（aria-pressed=true），原 ID 未变。另用两个 owner 隔离配置保留句 3500 的未钉旧页面：第一页界面新增 1 条后，第二页真实前端再钉返回 200、existing=true、同一 ID，显示“已在证据篮中”，行变已钉，胶囊保持 208 → 208，未错误加 1。旧页 208 仅证明 existing 分支不增量，不代表跨标签自动同步；瞬时服务端 209 含本轮新增 1 条。立即仅按新 ID 删除（204），服务端恢复 208，旧证据未删。截图：E-01-R2b-1-unloaded-pinned.png、E-01-R2b-2-race-before.png、E-01-R2b-3-existing-no-increment.png。 |
| AS-04 / B18（第 1 次） | 已修复（回归通过） | 正文“共 31 个搭配行”，偏 big 13 / 共同 1 / 偏 large 17；SketchDiff 卡 DOM 为 13 + 1 + 17 = 31 行，正式统计 `d753af84-31b7-470a-b1d4-42890c97ef61` 的 row_count=31、实际 31 行，三者一致。步骤含读取近义词流程、多项对比与近义词对比。截图：AS-04-R2b-2-first-card.png。 |
| AS-04 / B18（第 2 次） | 已修复（回归通过） | 正文“big 偏 13 个搭配，large 偏 17 个，全部 31 个”；卡 DOM 为 13 / 1 / 17 行，正式统计 `c5ca80bd-ae17-422a-a514-b03de41b3efa` 的 row_count=31、实际 31 行，三者一致。已视觉核验正文与卡同屏。两次通过仅说明本轮缓解有效，不保证后续模型输出。截图：AS-04-R2b-3-second.png、AS-04-R2b-4-second-summary.png。 |
| A-01 登录抽查 | 通过 | sol-owner 使用原密码进入主项目语料库，无改密门页。该账号已完成引导，未重验首次登录引导分支。截图：A-01-R2b-1-login.png。 |
| S-01 基本检索抽查 | 通过 | 维基中文“翻译”“研究”“研究 $3 方法”分别为 60 次 / 55 句 / 34 篇、545 / 439 / 141、3 / 2 / 2，与预期一致。截图：S-01-R2b-1-translation.png、S-01-R2b-2-gap.png。 |
| S-12 平行检索抽查 | 通过 | Tatoeba 中文侧“翻译”为 84 次 / 79 句 / 79 句对；英文对齐句与“无对齐译文”正常显示，整句切换可用。截图：S-12-R2b-1-parallel.png。 |
| T-01 频次抽查 | 通过 | 排除标点和数字时前五为的 26,909、年 10,794、在 8,139、月 5,582、和 4,905；取消排除后逗号 43,129、句号 25,178。本次仅核验上述频次，未扩展其他指标。截图：T-01-R2b-1-frequency.png、T-01-R2b-2-punctuation.png。 |
| N-01 词性键盘流抽查 | 通过 | 临时层新建后 Enter 未重开对话框；My 用 Enter 确认，Hometown 改 ADJ 后重新点词、Delete 拒绝。J → Shift+Enter → K 返回第 2 句显示已完成、0 处待确认，文档 2 / 8、层进度 14 / 494，无需刷新。临时层已删除，旧层未改。截图：N-01-R2b-2-complete.png。 |
| K-09 证据加入笔记抽查 | 通过 | 临时笔记自动保存后先插入句 2856 的旧证据 1 条，再加入证据篮已载入 200 / 总 208 条，无刷新正文立即为 25,819 字符、200 来源块、200 引用，GET 独立引用 200，首条未重复；201 次引用 POST 均 200。预览命中词粗体、英文译文和来源正常。临时笔记已删，旧笔记、旧证据未改。截图：K-09-R2b-1-preview.png。 |
| AS-01 助手基本对话抽查 | 通过 | 调用解析查询式、计算搭配两项工具；正式结果 25 行，卡展示前 10 并明确为部分结果。图表奥德赛 10.61、英文 10.55、爱因斯坦 10.52 与正式结果一致，英文共现频次为 5；未复现旧草稿“都 3 次”的解释错误。截图：AS-01-R2b-1-answer.png。 |
| 新对话首条回答流式显示 | 通过 | 新建会话首问解释搭配十步骤；只读 MutationObserver 捕获 226 帧，回答运行中由“语”（1 字）到“语料库”（3 字）、5 字持续增长，最终 2,395 字并完成，无需刷新。帧记录 `tmp/browser-test/R2b-stream-frames.json`。截图：AS-01-R2b-3-stream-running.png、AS-01-R2b-4-live-answer.png。 |

### 新发现问题

本次未确认新的独立问题。B05 为原问题仍未修复，未重复编号。上次中断草稿中的 B19 搭配解释错误在本次未复现，不直接据旧草稿新增问题。

| 编号 | 页面/功能 | 严重度 | 现象 | 复现步骤 | 期望 | 截图 | 控制台 / 网络错误 |
| --- | --- | --- | --- | --- | --- | --- | --- |

### 清理与限制

仅按本轮预先记下的 ID 清理新增数据，下列删除均返回 204；未按面板显示清理旧证据。

| 新建数据 | 已删除 ID |
| --- | --- |
| 分布统计 | `f264b2cf-35ff-4548-b8f2-3438f8806ee4`、`f70d6175-0801-4760-9908-1456a0e6570a` |
| 频次统计 | `37a18923-4a44-45bc-a59f-a90b7835b129`、`a27fa576-861b-4a3e-9905-3113d19d9a83`、`d275d07e-9a80-4766-a302-f0e304961d4e` |
| AS-05 会话与统计 | 会话 `2faab070-c87a-4c36-b426-220b3caaee4a`（先停止、确认 idle）；统计 `b667dca3-5783-4545-85b1-65e81486b98c`、`105fe4d4-8883-46d0-9b72-72f92cda3140`、`9b99e218-2620-4fad-91a4-d1e63645eb94` |
| AS-04 两次会话 | `b960d65d-a42b-4967-ba1d-b6618f35ef8d`、`b1449805-977f-4c2f-9d83-43cd59856cf4` |
| AS-04 统计 | `88dcb0c9-0b69-45a0-8ade-a89e14d2686c`、`d753af84-31b7-470a-b1d4-42890c97ef61`、`7ebac9ce-3ea3-4caf-b801-f221025b073a`、`c5ca80bd-ae17-422a-a514-b03de41b3efa` |
| AS-01、流式会话与统计 | 会话 `8d955f31-9c9e-4332-bc13-f5fb4cb2f7ad`、`9f99fb46-0e3e-4353-b0ba-d9d62d73b080`、`3ea8cd7b-b2b3-4500-833b-55b95346ae0e`；统计 `401f0132-fc52-4de6-9782-e8d099ecb774` |
| AS-08 会话 | `3109bc2a-1583-43a6-9863-65b01bc97b3e`、`2e576fca-4638-44ab-af4d-6c33c2ce678d`、`0ee80d5c-afb2-4a2a-afe3-8e5fc54dfdb7`（均先停止、确认 idle） |
| AS-08 统计 | `675f7911-1f64-4ebd-814f-04474fc4abc9`、`91cc221c-25b4-40f3-9270-bfd32a51ea2a`、`4d1414b5-0e2f-4a1d-8bbb-c08cfc980f4f` |
| N-01 词性临时层 | `479dc2f9-a19c-4146-ae87-fb57719f1f57`；一次选库失败误建的本轮 EWT 临时层 `9ddc32fd-2a08-4fa6-a288-d33911d1dbc4` 未标注，发现后立即删除 |
| N-06 三类临时层 | 片段 `25b4ad2a-9b0d-4c7b-a619-e1129e3963e3`、词性 `b9f2a3de-c08c-4f11-8c9a-62be6b54df60`、关系 `4b50b76a-4dac-47e0-be56-7abbdeec6627` |
| K-09 临时笔记 | `ce2d51ca-ee0e-475a-9ffc-498a194ddf36`，删除后 GET 404，笔记总数恢复 7 |
| E-01 竞争测试新增证据 | `15ade72b-23aa-4aa0-bde1-7e66fa58fd48`，删除后服务端总数恢复 208 |
| 取消期间已生成的统计 | `45cc6174-d4bc-4671-92ac-0fe1b3af62ff`（AS-05，job `2d2a1396-15ab-4af9-8b6b-12b6a1d064ae`）、`20cd4ff6-a24b-44b1-8c87-4a6a5cce0c20`（AS-08，job `d6ebd9fd-60a7-471d-874a-ccc2a50ef2f6`）；经任务所有者、时间及工具参数确认属于本轮后，按这两个 ID 删除（204）。取消时后端可能已完成，不据取消动作推定未生成结果。 |

片段预标任务 `bffaff05-6782-480f-9961-bdafb78c6eea`、词性预标任务 `c9f6e453-48ab-4368-94e5-c77bef44e80b` 均为 cancelled；关系预标任务 `6946615f-fade-4012-8285-f8da04fa9ad1` 清理时已 succeeded，未误记为取消。关系层只读引用旧偏误片段层，旧层未改。方法说明复用旧抽样层 `aeebcdb2-67c3-44a4-b02a-1fa09511b948`，原词性层 `1aeb59f4-2952-4a14-9897-6585f25a2ff1` 未改。旧句 8102 证据 ID `7980a364-3e30-44ad-8fee-b625b8ef64b7` 保留。

最终只读核验：证据 total=208、旧句 8102 原 ID 保留；重载后胶囊 208、句 8102 仍为已钉（截图：E-01-R2b-4-restored.png）。标注层 total=11、无 Sol-R2b 临时层；助手会话 total=17，与开始一致，running=[]；本轮时段内新增统计已清理，owner 本轮任务无 queued / running。成员 5 人、sol-viewer 为查看者；笔记 7 条、无 Sol-R2b 临时笔记。用户原有 17 个会话与旧业务数据未删除；sol-owner 原密码未变，限流后登录已恢复。

本轮浏览器会话 `sol-r2b-owner`、`sol-r2b-auth`、`sol-r2b-editor`，以及启动失败尝试 `sol-r2-owner` 均已执行 close；逐会话 `session info --json` 复核均为 active=false、pid=null、runtime=null，无本轮会话 / 配置名称对应进程。session list 曾残留 `sol-r2-owner` 名称，但逐会话状态已明确 inactive，未为清理列表标记修改仓库外文件。

未取得全程明确的控制台错误汇总，不宣称控制台始终零错误。失败与限流结论依据实际界面、请求与截图。原问题表及本节之前的记录完整保留；未修改其他代码、配置或 doc 文件，未执行 Git 提交。
