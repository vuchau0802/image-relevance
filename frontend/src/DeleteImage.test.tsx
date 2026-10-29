import { beforeEach, expect, test, vi } from 'vitest'
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { deleteImage } from './api'
import DeleteImage from './DeleteImage'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  deleteImage: vi.fn(),
}))

const mockedDelete = vi.mocked(deleteImage)
const imageId = 'img_test'

beforeEach(() => {
  mockedDelete.mockReset()
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-token')
  mockedDelete.mockResolvedValue(undefined)
})

function showControl(onDeleted = vi.fn()) {
  return render(
    <DeleteImage
      imageId={imageId}
      creator="Example photographer"
      onDeleted={onDeleted}
    />,
  )
}

async function openConfirmation() {
  const user = userEvent.setup()
  await user.click(
    screen.getByRole('button', { name: 'Delete image' }),
  )
  return user
}

test('opening confirmation identifies the image without deleting', async () => {
  showControl()
  await openConfirmation()

  expect(screen.getByText(imageId)).toBeInTheDocument()
  expect(
    screen.getByText('Photo by Example photographer'),
  ).toBeInTheDocument()
  expect(mockedDelete).not.toHaveBeenCalled()
  expect(getSessionToken).not.toHaveBeenCalled()
})

test('cancelling sends no deletion request', async () => {
  const onDeleted = vi.fn()
  showControl(onDeleted)
  const user = await openConfirmation()

  await user.click(
    screen.getByRole('button', {
      name: 'Cancel image deletion',
    }),
  )

  expect(
    screen.getByRole('button', { name: 'Delete image' }),
  ).toBeInTheDocument()
  expect(mockedDelete).not.toHaveBeenCalled()
  expect(onDeleted).not.toHaveBeenCalled()
})

test('confirmed deletion reports the deleted image ID', async () => {
  const onDeleted = vi.fn()
  showControl(onDeleted)
  const user = await openConfirmation()

  await user.click(
    screen.getByRole('button', {
      name: 'Confirm image deletion',
    }),
  )

  await waitFor(() => {
    expect(onDeleted).toHaveBeenCalledExactlyOnceWith(imageId)
  })
  expect(mockedDelete).toHaveBeenCalledExactlyOnceWith(
    imageId,
    expect.any(AbortSignal),
    'synthetic-token',
  )
})

test('failed deletion preserves confirmation and allows retry', async () => {
  mockedDelete.mockRejectedValueOnce(
    new Error('Image processing is still running.'),
  )
  const onDeleted = vi.fn()
  showControl(onDeleted)
  const user = await openConfirmation()

  await user.click(
    screen.getByRole('button', {
      name: 'Confirm image deletion',
    }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Image processing is still running.',
  )
  expect(onDeleted).not.toHaveBeenCalled()

  await user.click(
    screen.getByRole('button', {
      name: 'Confirm image deletion',
    }),
  )

  await waitFor(() => {
    expect(onDeleted).toHaveBeenCalledExactlyOnceWith(imageId)
  })
  expect(mockedDelete).toHaveBeenCalledTimes(2)
})

test('blocks duplicates and aborts a pending deletion on unmount', async () => {
  let finish!: () => void
  mockedDelete.mockReturnValue(
    new Promise<void>((resolve) => {
      finish = resolve
    }),
  )

  const onDeleted = vi.fn()
  const view = showControl(onDeleted)
  await openConfirmation()

  await act(async () => {
    const button = screen.getByRole('button', {
      name: 'Confirm image deletion',
    })
    fireEvent.click(button)
    fireEvent.click(button)
  })

  expect(mockedDelete).toHaveBeenCalledOnce()
  expect(
    screen.getByRole('button', { name: 'Deleting…' }),
  ).toBeDisabled()
  expect(
    screen.getByRole('button', {
      name: 'Cancel image deletion',
    }),
  ).toBeDisabled()

  const signal = mockedDelete.mock.calls[0][1]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish()
  })

  expect(onDeleted).not.toHaveBeenCalled()
})