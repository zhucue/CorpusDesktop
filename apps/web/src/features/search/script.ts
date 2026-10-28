/** Simplified ↔ traditional Chinese for the zero-hit hint (QA Q36): common one-to-one character pairs only.
 * Ambiguous characters take their most frequent counterpart; the hint is verified by a real count before it is
 * shown, so a rare miss only means no hint. */
const PAIRS =
  "为為 与與 并並 后後 时時 这這 个個 们們 来來 说說 国國 学學 会會 对對 发發 经經 动動 现現 产產 进進 过過 还還 没沒 样樣 " +
  "种種 将將 两兩 见見 问問 长長 开開 关關 东東 车車 门門 书書 马馬 鸟鳥 鱼魚 龙龍 风風 飞飛 云雲 电電 话話 语語 读讀 写寫 " +
  "认認 识識 让讓 请請 谁誰 该該 课課 词詞 译譯 论論 议議 记記 讲講 计計 设設 证證 试試 诗詩 谈談 调調 资資 质質 贵貴 买買 " +
  "卖賣 钱錢 银銀 铁鐵 钟鐘 错錯 镜鏡 间間 闻聞 闭閉 阅閱 头頭 题題 颜顏 页頁 顺順 须須 领領 预預 华華 业業 专專 丝絲 丢丟 " +
  "严嚴 丧喪 临臨 丽麗 举舉 义義 乌烏 乐樂 习習 乡鄉 乱亂 争爭 亏虧 亚亞 亲親 亿億 仅僅 从從 仓倉 仪儀 价價 众眾 优優 伟偉 " +
  "传傳 伤傷 伦倫 伪偽 体體 余餘 侠俠 侦偵 侧側 侨僑 俭儉 债債 倾傾 偿償 储儲 儿兒 党黨 兰蘭 兴興 养養 兽獸 内內 册冊 军軍 " +
  "农農 冲衝 决決 况況 冻凍 净淨 凉涼 减減 凤鳳 凭憑 击擊 刘劉 则則 刚剛 创創 删刪 别別 剂劑 剑劍 剧劇 劝勸 办辦 务務 励勵 " +
  "劳勞 势勢 区區 医醫 协協 单單 卢盧 卫衛 却卻 厂廠 厅廳 历歷 压壓 厌厭 县縣 参參 双雙 变變 叙敘 号號 叹嘆 吓嚇 吗嗎 听聽 " +
  "启啟 员員 响響 团團 园園 围圍 图圖 圆圓 圣聖 场場 坏壞 块塊 坚堅 坛壇 执執 扩擴 扫掃 扬揚 扰擾 抢搶 护護 报報 担擔 拟擬 " +
  "拥擁 择擇 挂掛 挡擋 挤擠 挥揮 损損 换換 据據 摄攝 摆擺 摇搖 敌敵 数數 断斷 无無 旧舊 显顯 晓曉 暂暫 术術 杀殺 杂雜 权權 " +
  "条條 杨楊 极極 构構 枪槍 标標 树樹 档檔 桥橋 梦夢 检檢 楼樓 横橫 欢歡 欧歐 岁歲 归歸 残殘 毁毀 毕畢 气氣 汉漢 汤湯 沟溝 " +
  "泪淚 泽澤 洁潔 浅淺 测測 济濟 浓濃 润潤 涨漲 温溫 湾灣 湿濕 满滿 灭滅 灯燈 灵靈 灾災 炉爐 点點 烂爛 烟煙 烦煩 烧燒 热熱 " +
  "爱愛 爷爺 牵牽 犹猶 独獨 狱獄 猪豬 环環 画畫 畅暢 疗療 盖蓋 盘盤 着著 矿礦 码碼 础礎 确確 礼禮 祸禍 离離 积積 称稱 稳穩 " +
  "穷窮 竞競 笔筆 筑築 签簽 简簡 类類 粮糧 紧緊 红紅 约約 级級 纪紀 纯純 纳納 纵縱 纸紙 线線 练練 组組 细細 织織 终終 绍紹 " +
  "结結 绕繞 绘繪 给給 络絡 绝絕 统統 继繼 绩績 续續 维維 综綜 绿綠 编編 缘緣 缩縮 网網 罗羅 罚罰 职職 联聯 肃肅 肤膚 胜勝 " +
  "胆膽 脑腦 脚腳 脸臉 艺藝 节節 苏蘇 范範 荣榮 药藥 获獲 营營 蓝藍 虑慮 虚虛 虽雖 补補 袭襲 装裝 规規 视視 览覽 觉覺 触觸 " +
  "订訂 讨討 训訓 许許 访訪 评評 诉訴 诚誠 询詢 详詳 误誤 诸諸 谋謀 谓謂 谢謝 谱譜 贝貝 负負 贡貢 财財 责責 败敗 货貨 贫貧 " +
  "购購 贯貫 贴貼 费費 贸貿 赏賞 赔賠 赛賽 赞贊 赢贏 赵趙 赶趕 趋趨 跃躍 践踐 轨軌 转轉 轮輪 软軟 轻輕 载載 较較 辅輔 辆輛 " +
  "辈輩 输輸 辞辭 边邊 达達 迁遷 运運 远遠 违違 连連 迟遲 适適 选選 递遞 遗遺 邮郵 邻鄰 郑鄭 释釋 里裡 针針 钢鋼 铜銅 铺鋪 " +
  "链鏈 销銷 锁鎖 锅鍋 键鍵 闪閃 闹鬧 队隊 阳陽 阴陰 阵陣 阶階 际際 陆陸 陈陳 险險 随隨 隐隱 难難 雾霧 静靜 韩韓 项項 顶頂 " +
  "顾顧 顿頓 颗顆 额額 饭飯 饮飲 饰飾 饱飽 饿餓 馆館 驱驅 驶駛 驾駕 验驗 骂罵 骑騎 骗騙 鸡雞 鸣鳴 麦麥 黄黃 齐齊 齿齒 龟龜 " +
  "广廣 庆慶 库庫 应應 废廢 张張 弹彈 强強 当當 录錄 彻徹 径徑 忆憶 忧憂 怀懷 态態 总總 恋戀 恶惡 悬懸 惊驚 惯慣 愿願 懒懶 " +
  "战戰 戏戲 户戶 扑撲 托託 万萬 丑醜 么麼 于於 亩畝 处處 备備 复復 够夠 夹夾 夺奪 奋奮 奖獎 妇婦 妈媽 娱娛 婴嬰 孙孫 宁寧 " +
  "宝寶 实實 审審 宪憲 宽寬 宾賓 寻尋 导導 寿壽 尔爾 尘塵 尝嘗 层層 属屬 岛島 岭嶺 币幣 师師 帐帳 带帶 帮幫 干幹 几幾 庄莊 " +
  "叶葉 吴吳 声聲 观觀 辉輝 迹跡 锦錦 鲁魯 鲜鮮 尽盡 汇匯 罢罷 摊攤 盐鹽 鸭鴨 鹅鵝 猫貓 灿燦";

const S2T = new Map<string, string>();
const T2S = new Map<string, string>();
for (const p of PAIRS.split(" ")) {
  const [s, t] = Array.from(p);
  if (!s || !t || s === t) continue;
  if (!S2T.has(s)) S2T.set(s, t);
  if (!T2S.has(t)) T2S.set(t, s);
}

export type Script = "simplified" | "traditional" | "mixed";

/** Convert the characters the table knows; returns the text unchanged when nothing converts. */
export function convertScript(text: string, to: "simplified" | "traditional"): string {
  const map = to === "traditional" ? S2T : T2S;
  return Array.from(text, (c) => map.get(c) ?? c).join("");
}

/** Script of a text sample by simplified-only vs traditional-only characters; null without enough evidence. */
export function guessScript(sample: string): Script | null {
  let s = 0;
  let t = 0;
  for (const c of sample) {
    if (S2T.has(c)) s += 1;
    else if (T2S.has(c)) t += 1;
  }
  if (s + t < 5) return null;
  if (t > 4 * s) return "traditional";
  if (s > 4 * t) return "simplified";
  return "mixed";
}

export const scriptLabel: Record<Script, string> = { simplified: "简体", traditional: "繁体", mixed: "简繁混合" };
