import { CircleHelp } from 'lucide-react'
import {
  createContext,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useCallback,
  useContext,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { createPortal } from 'react-dom'

type ActiveTip = {
  id: string
  title: string
  content: string
  trigger: HTMLButtonElement
}

type TooltipContextValue = {
  activeId: string | null
  toggle: (tip: ActiveTip) => void
}

const TooltipContext = createContext<TooltipContextValue | null>(null)
const VIEWPORT_MARGIN = 12
const TRIGGER_GAP = 8
const MAX_WIDTH = 340

function samePosition(left: CSSProperties, right: CSSProperties): boolean {
  return left.left === right.left
    && left.top === right.top
    && left.width === right.width
    && left.maxHeight === right.maxHeight
}

function stopPointerPropagation(event: ReactPointerEvent) {
  event.stopPropagation()
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<ActiveTip | null>(null)
  const [position, setPosition] = useState<CSSProperties>({ visibility: 'hidden' })
  const popoverRef = useRef<HTMLDivElement>(null)

  const close = useCallback((restoreFocus: boolean) => {
    if (restoreFocus) active?.trigger.focus()
    setActive(null)
  }, [active])

  const toggle = useCallback((tip: ActiveTip) => {
    setPosition({ visibility: 'hidden' })
    setActive((current) => current?.id === tip.id ? null : tip)
  }, [])

  const reposition = useCallback(() => {
    if (!active || !popoverRef.current) return
    const trigger = active.trigger.getBoundingClientRect()
    const popover = popoverRef.current
    const availableWidth = Math.max(1, window.innerWidth - VIEWPORT_MARGIN * 2)
    const width = Math.min(MAX_WIDTH, availableWidth)
    popover.style.width = `${width}px`
    popover.style.maxHeight = `${Math.max(1, window.innerHeight - VIEWPORT_MARGIN * 2)}px`
    const measured = popover.getBoundingClientRect()
    const idealLeft = trigger.left + trigger.width / 2 - width / 2
    const left = Math.min(
      Math.max(idealLeft, VIEWPORT_MARGIN),
      window.innerWidth - width - VIEWPORT_MARGIN,
    )
    const below = Math.max(VIEWPORT_MARGIN, trigger.bottom + TRIGGER_GAP)
    const roomBelow = Math.max(1, window.innerHeight - below - VIEWPORT_MARGIN)
    const roomAbove = Math.max(1, trigger.top - TRIGGER_GAP - VIEWPORT_MARGIN)
    const placeBelow = measured.height <= roomBelow || roomBelow >= roomAbove
    const maxHeight = placeBelow ? roomBelow : roomAbove
    const top = placeBelow
      ? Math.min(below, window.innerHeight - VIEWPORT_MARGIN - maxHeight)
      : Math.max(VIEWPORT_MARGIN, trigger.top - TRIGGER_GAP - Math.min(measured.height, maxHeight))
    const next: CSSProperties = {
      left: Math.round(left),
      top: Math.round(top),
      width,
      maxHeight,
      visibility: 'visible',
    }
    setPosition((current) => samePosition(current, next) ? current : next)
  }, [active])

  useLayoutEffect(() => {
    if (!active) return
    reposition()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(reposition)
    if (popoverRef.current) observer?.observe(popoverRef.current)
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
    }
  }, [active, reposition])

  useLayoutEffect(() => {
    if (!active) return
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (active.trigger.contains(target) || popoverRef.current?.contains(target)) return
      close(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        close(true)
      }
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [active, close])

  const context = useMemo<TooltipContextValue>(() => ({
    activeId: active?.id ?? null,
    toggle,
  }), [active?.id, toggle])

  return (
    <TooltipContext.Provider value={context}>
      {children}
      {active ? createPortal(
        <div
          className="metric-tip-popover"
          id={active.id}
          ref={popoverRef}
          role="tooltip"
          style={position}
        >
          <strong>{active.title}</strong>
          <p>{active.content}</p>
        </div>,
        document.body,
      ) : null}
    </TooltipContext.Provider>
  )
}

export function MetricTip({ title, children }: { title: string; children: string }) {
  const context = useContext(TooltipContext)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const generatedId = useId()
  const id = `metric-tip-${generatedId.replaceAll(':', '')}`
  if (!context) {
    return <TooltipProvider><MetricTip title={title}>{children}</MetricTip></TooltipProvider>
  }
  const open = context.activeId === id
  return (
    <span className="metric-tip">
      <button
        aria-controls={open ? id : undefined}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        aria-label={`Что означает: ${title}`}
        className={open ? 'active' : ''}
        onClick={() => {
          if (!triggerRef.current) return
          context.toggle({ id, title, content: children, trigger: triggerRef.current })
        }}
        onPointerDown={stopPointerPropagation}
        ref={triggerRef}
        title={`Что означает: ${title}`}
        type="button"
      >
        <CircleHelp aria-hidden="true" />
      </button>
    </span>
  )
}
