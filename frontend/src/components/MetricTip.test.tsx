import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MetricTip, TooltipProvider } from './MetricTip'

function rect(values: Partial<DOMRect>): DOMRect {
  return {
    bottom: 0,
    height: 0,
    left: 0,
    right: 0,
    toJSON: () => ({}),
    top: 0,
    width: 0,
    x: 0,
    y: 0,
    ...values,
  }
}

function Fixture() {
  return (
    <TooltipProvider>
      <MetricTip title="Первый показатель">Первое объяснение</MetricTip>
      <MetricTip title="Второй показатель">Второе объяснение</MetricTip>
      <button type="button">Вне подсказки</button>
    </TooltipProvider>
  )
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('MetricTip', () => {
  it('keeps one tip open and closes it on an outside pointer press', () => {
    render(<Fixture />)

    fireEvent.click(screen.getByLabelText('Что означает: Первый показатель'))
    expect(screen.getByText('Первое объяснение')).toBeVisible()

    fireEvent.click(screen.getByLabelText('Что означает: Второй показатель'))
    expect(screen.queryByText('Первое объяснение')).not.toBeInTheDocument()
    expect(screen.getByText('Второе объяснение')).toBeVisible()

    fireEvent.pointerDown(screen.getByRole('button', { name: 'Вне подсказки' }))
    expect(screen.queryByText('Второе объяснение')).not.toBeInTheDocument()
  })

  it('closes on Escape and returns focus to its trigger', () => {
    render(<Fixture />)
    const trigger = screen.getByLabelText('Что означает: Первый показатель')

    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByText('Первое объяснение')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('clamps the popover within a narrow viewport', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 240 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('metric-tip-popover')) {
        return rect({ height: 180, width: 296, right: 296, bottom: 180 })
      }
      if (this.getAttribute('aria-label') === 'Что означает: Второй показатель') {
        return rect({ left: 294, right: 318, top: 214, bottom: 238, width: 24, height: 24 })
      }
      return rect({})
    })
    render(<Fixture />)

    fireEvent.click(screen.getByLabelText('Что означает: Второй показатель'))
    const popover = screen.getByRole('tooltip')
    await waitFor(() => expect(popover).toHaveStyle({ visibility: 'visible' }))

    const left = Number.parseFloat(popover.style.left)
    const top = Number.parseFloat(popover.style.top)
    const width = Number.parseFloat(popover.style.width)
    const maxHeight = Number.parseFloat(popover.style.maxHeight)
    expect(left).toBeGreaterThanOrEqual(12)
    expect(left + width).toBeLessThanOrEqual(308)
    expect(top).toBeGreaterThanOrEqual(12)
    expect(top + maxHeight).toBeLessThanOrEqual(228)
  })
})
