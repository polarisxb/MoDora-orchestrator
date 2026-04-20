import { cn } from '@/lib/utils'

/**
 * 页面 Hero 大卡 —— Workspace DNA 的核心视觉单元
 *
 * 特征:
 *   - 圆角 `rounded-xl` + 1px border
 *   - 顶部浅渐变(唯一允许渐变的场合之一,参考 inspirations.md)
 *   - 徽章行、大标题、短副标、可选 CTA、右侧 SVG 图解槽
 *   - 内边距响应式: p-6 (mobile) -> p-8 lg -> p-10 xl
 *
 * 用法:
 *   <PageHero
 *     badges={[<Badge>模块③</Badge>, <Badge variant="primary">素材+模板</Badge>]}
 *     title={<>让 AI 自动读取素材、理解结构,<br/>一键生成<span className="text-primary-600">企业模板</span>。</>}
 *     description="从 Excel、Word、Markdown 到业务结构..."
 *     action={<Button>开始</Button>}
 *     illustration={<HeroIllustration/>}
 *   />
 */
export function PageHero({
  badges,
  title,
  description,
  action,
  illustration,
  tone = 'ink',
  className,
}) {
  const toneStyles = {
    ink: 'from-ink-50 to-white',
    primary: 'from-primary-50/40 to-white',
  }
  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-xl border border-ink-200 bg-gradient-to-br',
        toneStyles[tone] || toneStyles.ink,
        className,
      )}
    >
      <div className="relative z-10 p-6 lg:p-8 xl:p-10">
        {badges && (
          <div className="flex flex-wrap items-center gap-2 mb-5">{badges}</div>
        )}
        <h1 className="text-xl lg:text-2xl font-semibold text-ink-900 leading-tight tracking-tight max-w-[640px]">
          {title}
        </h1>
        {description && (
          <p className="mt-3 text-sm text-ink-600 leading-relaxed max-w-[560px]">
            {description}
          </p>
        )}
        {action && <div className="mt-6">{action}</div>}
      </div>

      {illustration && (
        <div className="absolute top-0 right-0 h-full w-[320px] hidden xl:block pointer-events-none opacity-90">
          {illustration}
        </div>
      )}
    </section>
  )
}
