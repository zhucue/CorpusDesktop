import { Modal } from "antd";
import { Icon } from "../Icon";

type Row = [string, string[]];
const GLOBAL: Row[] = [["命令面板", ["Ctrl", "K"]], ["快捷键", ["?"]], ["关闭浮层", ["Esc"]], ["聚焦输入框", ["/"]]];
const PAGE: Record<string, { name: string; rows: Row[] }> = {
  search: { name: "检索", rows: [["检索", ["Enter"]], ["查询历史", ["H"]], ["词性着色", ["P"]]] },
  stats: { name: "统计", rows: [["切换统计方法", ["1", "–", "5"]]] },
  annotate: {
    name: "标注",
    rows: [
      ["确认当前词", ["Enter"]],
      ["整句确认", ["Shift", "Enter"]],
      ["拒绝（词性层）", ["Del"]],
      ["修改：聚焦标签筛选", ["E"]],
      ["选词", ["←", "→"]],
      ["选标签", ["1", "–", "9", "A", "–", "Z"]],
      ["上一句 / 下一句", ["K", "J"]],
      ["词性着色", ["P"]],
      ["片段：选片段", ["←", "→"]],
      ["片段：连关系", ["R"]],
      ["片段：取消选择", ["Esc"]],
      ["对齐：确认 / 拒绝句对", ["Enter", "Del"]],
    ],
  },
  assistant: { name: "助手", rows: [["发送", ["Enter"]], ["换行", ["Shift", "Enter"]], ["停止运行", ["Esc"]]] },
};

function KeyRow({ row }: { row: Row }) {
  return (
    <div className="key-row">
      <span>{row[0]}</span>
      <span>{row[1].map((k, i) => (k === "–" ? <span key={i}>–</span> : <kbd key={i}>{k}</kbd>))}</span>
    </div>
  );
}

export default function KeysOverlay({ open, page, onClose }: { open: boolean; page: string; onClose: () => void }) {
  const pk = PAGE[page];
  return (
    <Modal open={open} onCancel={onClose} footer={null} closable={false} width={560} style={{ top: "12vh" }} className="cmdk" destroyOnHidden>
      <div className="cmdk-in">
        <Icon name="keyboard" size={18} />
        <b className="grow" style={{ color: "var(--text)", fontWeight: 600 }}>
          快捷键
        </b>
        <kbd>Esc</kbd>
      </div>
      <div className="keys-grid">
        <h3>全局</h3>
        {GLOBAL.map((r) => (
          <KeyRow key={r[0]} row={r} />
        ))}
        {pk && <h3>{pk.name}</h3>}
        {pk?.rows.map((r) => <KeyRow key={r[0]} row={r} />)}
      </div>
    </Modal>
  );
}
