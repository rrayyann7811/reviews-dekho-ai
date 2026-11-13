export default function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <svg aria-hidden viewBox="0 0 32 32" className="size-7 shrink-0">
        <rect width="32" height="32" rx="7" fill="#22577a" />
        <path d="M9 10h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-8l-4 3.5V21H9a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" />
        <path d="M11.5 17.5v-2M16 17.5v-4M20.5 17.5v-3" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight text-ink">
        Reviews Dekho <span className="font-medium text-ink-3">AI</span>
      </span>
    </span>
  )
}
