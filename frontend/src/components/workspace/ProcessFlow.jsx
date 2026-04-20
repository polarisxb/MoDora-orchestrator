/**
 * 处理流水 — 1:1 匹配原型的 4 步卡片网格
 */
const STEPS = [
  { num: '01', title: 'OCR · 抽取', desc: 'PaddleOCR 切分 blocks,识别标题、正文、图表、页眉页脚。' },
  { num: '02', title: 'CCTree · 构建', desc: '按层级组织成组件关联树,保留"侧栏 vs 正文"这类布局语义。' },
  { num: '03', title: 'Retrieve · 检索', desc: 'LLM 剪枝 + Embedding 兜底,多通道投票,位置感知定位。' },
  { num: '04', title: 'Fill · 填充', desc: '按模板格式回填 Excel / Word,冲突自动仲裁,单位统一化。' },
]

export function ProcessFlow() {
  return (
    <section className="rounded-xl border border-ink-200 bg-white p-5 transition-shadow duration-200 hover:shadow-soft">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-ink-900">处理流水</h2>
          <p className="text-[11px] text-ink-500 mt-0.5">
            MoDora 的四步法 · 你可随时查看每一步的中间结果
          </p>
        </div>
        <span className="cursive-text text-sm text-ink-400">how it works</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-in">
        {STEPS.map((step) => (
          <div key={step.num} className="relative p-3 rounded-lg border border-ink-200 bg-paper-50 transition-colors duration-200 hover:border-primary-300 hover:bg-white">
            <div className="text-[11px] font-mono text-ink-400">{step.num}</div>
            <div className="mt-1 text-sm font-semibold text-ink-900">{step.title}</div>
            <div className="mt-1 text-[11px] text-ink-500 leading-relaxed">{step.desc}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
