import { BRAND } from '@/lib/brand'

export function Footer() {
  return (
    <footer className="border-t border-ink-200/60 mt-8">
      <div className="max-w-[1440px] mx-auto px-6 py-4 flex items-center justify-between text-[11px] text-ink-400">
        <span>
          {BRAND.name} {BRAND.version} · {BRAND.tech}
        </span>
        <span className="cursive-text text-[13px]">
          made with care · hand-drawn edition
        </span>
      </div>
    </footer>
  )
}
