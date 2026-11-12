import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { ColumnResizeHandle } from './ColumnResizeHandle'

function setup(renderedWidth = 300, bounds = { minSize: 80, maxSize: 2000 }) {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width: renderedWidth,
  } as DOMRect)
  const onResize = vi.fn()
  const onCommit = vi.fn()
  const onParentPointerDown = vi.fn()
  render(
    <div onPointerDown={onParentPointerDown}>
      <ColumnResizeHandle
        label="Name"
        size={150}
        minSize={bounds.minSize}
        maxSize={bounds.maxSize}
        onResize={onResize}
        onCommit={onCommit}
      />
    </div>,
  )
  return { handle: screen.getByRole('separator', { name: 'Resize Name column' }), onResize, onCommit, onParentPointerDown }
}

describe('ColumnResizeHandle', () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => vi.restoreAllMocks())

  it('drags from the rendered width instead of the default column size', () => {
    const { handle, onResize, onCommit } = setup(300)

    fireEvent.pointerDown(handle, { clientX: 500, button: 0 })
    fireEvent.pointerMove(window, { clientX: 540, buttons: 1 })
    fireEvent.pointerUp(window, { clientX: 540 })

    expect(onResize).toHaveBeenCalledWith(340)
    expect(onCommit).toHaveBeenCalledTimes(1)
    expect(onCommit).toHaveBeenCalledWith(340)
  })

  it('rounds fractional widths', () => {
    const { handle, onCommit } = setup(300.4)

    fireEvent.pointerDown(handle, { clientX: 100, button: 0 })
    fireEvent.pointerMove(window, { clientX: 110.3, buttons: 1 })
    fireEvent.pointerUp(window)

    expect(onCommit).toHaveBeenCalledWith(311)
  })

  it('clamps to the column bounds', () => {
    const { handle, onCommit } = setup(300, { minSize: 80, maxSize: 400 })

    fireEvent.pointerDown(handle, { clientX: 500, button: 0 })
    fireEvent.pointerMove(window, { clientX: 0, buttons: 1 })
    fireEvent.pointerUp(window)
    fireEvent.pointerDown(handle, { clientX: 0, button: 0 })
    fireEvent.pointerMove(window, { clientX: 900, buttons: 1 })
    fireEvent.pointerUp(window)

    expect(onCommit.mock.calls).toEqual([[80], [400]])
  })

  it('commits a drag that the browser cancels', () => {
    const { handle, onCommit } = setup(300)

    fireEvent.pointerDown(handle, { clientX: 0, button: 0 })
    fireEvent.pointerMove(window, { clientX: 20, buttons: 1 })
    fireEvent.pointerCancel(window)

    expect(onCommit).toHaveBeenCalledWith(320)
  })

  it('does not freeze a column on a click without movement', () => {
    const { handle, onCommit } = setup(300)

    fireEvent.pointerDown(handle, { clientX: 500, button: 0 })
    fireEvent.pointerUp(window, { clientX: 500 })

    expect(onCommit).not.toHaveBeenCalled()
  })

  it('stops tracking the pointer after release', () => {
    const { handle, onResize } = setup(300)

    fireEvent.pointerDown(handle, { clientX: 0, button: 0 })
    fireEvent.pointerUp(window)
    fireEvent.pointerMove(window, { clientX: 50, buttons: 1 })

    expect(onResize).not.toHaveBeenCalled()
  })

  it('ignores non-primary buttons', () => {
    const { handle, onResize } = setup(300)

    fireEvent.pointerDown(handle, { clientX: 0, button: 2 })
    fireEvent.pointerMove(window, { clientX: 50, buttons: 1 })

    expect(onResize).not.toHaveBeenCalled()
  })

  it('does not let the drag reach the header (sorting)', () => {
    const { handle, onParentPointerDown } = setup(300)

    fireEvent.pointerDown(handle, { clientX: 0, button: 0 })
    fireEvent.pointerUp(window)

    expect(onParentPointerDown).not.toHaveBeenCalled()
  })

  it('ends a drag when the button was released outside the window', () => {
    const { handle, onResize, onCommit } = setup(300)

    fireEvent.pointerDown(handle, { clientX: 0, button: 0 })
    fireEvent.pointerMove(window, { clientX: 30, buttons: 1 })
    fireEvent.pointerMove(window, { clientX: 90, buttons: 0 })
    fireEvent.pointerMove(window, { clientX: 120, buttons: 1 })

    expect(onResize.mock.calls).toEqual([[330]])
    expect(onCommit.mock.calls).toEqual([[330]])
  })

  it('ends a drag when the window loses focus', () => {
    const { handle, onCommit } = setup(300)

    fireEvent.pointerDown(handle, { clientX: 0, button: 0 })
    fireEvent.pointerMove(window, { clientX: 15, buttons: 1 })
    fireEvent.blur(window)

    expect(onCommit.mock.calls).toEqual([[315]])
  })

  it('reports the rendered width to assistive technology', () => {
    let notify: ResizeObserverCallback = () => {}
    const original = globalThis.ResizeObserver
    globalThis.ResizeObserver = class {
      constructor(cb: ResizeObserverCallback) {
        notify = cb
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    try {
      const { handle } = setup(300)

      act(() =>
        notify([{ borderBoxSize: [{ inlineSize: 321.6 }] } as unknown as ResizeObserverEntry], {} as ResizeObserver),
      )

      expect(handle).toHaveAttribute('aria-valuenow', '322')
    } finally {
      globalThis.ResizeObserver = original
    }
  })

  it('resets the column on double-click', () => {
    const { handle, onCommit } = setup(300)

    fireEvent.doubleClick(handle)

    expect(onCommit).toHaveBeenCalledWith(null)
  })

  it('resizes with the arrow keys', () => {
    const { handle, onResize, onCommit } = setup(300)

    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })

    expect(onResize.mock.calls).toEqual([[310], [290]])
    expect(onCommit.mock.calls).toEqual([[310], [290]])
  })

  it('is a focusable, labelled separator', () => {
    const { handle } = setup(300)

    expect(handle).toHaveAttribute('tabindex', '0')
    expect(handle).toHaveAttribute('aria-orientation', 'vertical')
    expect(handle).toHaveAttribute('aria-valuenow', '150')
    expect(handle).toHaveAttribute('aria-valuemin', '80')
    expect(handle).toHaveAttribute('aria-valuemax', '2000')
  })
})
