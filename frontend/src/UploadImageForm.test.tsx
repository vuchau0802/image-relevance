import { beforeEach, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { uploadImage } from './api'
import type { ImageUploadResult } from './api'
import UploadImageForm from './UploadImageForm'

const { getSessionToken } = vi.hoisted(() => ({
  getSessionToken: vi.fn(),
}))

vi.mock('./useSessionToken', () => ({
  useSessionToken: () => getSessionToken,
}))

vi.mock('./api', () => ({
  uploadImage: vi.fn(),
}))

const mockedUpload = vi.mocked(uploadImage)

beforeEach(() => {
  mockedUpload.mockReset()
  getSessionToken.mockReset()
  getSessionToken.mockResolvedValue('synthetic-token')
})

function jpegFile() {
  return new File(['synthetic JPEG'], 'fox.jpg', {
    type: 'image/jpeg',
  })
}

async function fillForm(file = jpegFile()) {
  const user = userEvent.setup()
  await user.upload(screen.getByLabelText('JPEG image'), file)
  await user.type(
    screen.getByRole('textbox', { name: 'Image creator' }),
    'Example creator',
  )
  return { user, file }
}

test('uploads the file and clears the form after success', async () => {
  mockedUpload.mockResolvedValue({
    image_id: 'img_uploaded',
    status: 'pending',
  })

  render(<UploadImageForm />)
  const { file } = await fillForm()

  await act(async () => {
    fireEvent.submit(
      screen.getByRole('form', { name: 'Upload image' }),
    )
  })

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Image saved: img_uploaded. Status: pending.',
  )
  expect(mockedUpload).toHaveBeenCalledWith(
    file,
    'Example creator',
    expect.any(AbortSignal),
    'synthetic-token',
  )
  expect(
    screen.getByRole('textbox', { name: 'Image creator' }),
  ).toHaveValue('')
  expect(screen.getByLabelText('JPEG image')).toHaveValue('')
})

test('failed upload preserves the selected file and creator', async () => {
  mockedUpload.mockRejectedValue(new Error('Upload unavailable'))

  render(<UploadImageForm />)
  const { file } = await fillForm()

  await act(async () => {
    fireEvent.submit(
      screen.getByRole('form', { name: 'Upload image' }),
    )
  })

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Upload unavailable',
  )
  expect(
    screen.getByRole('textbox', { name: 'Image creator' }),
  ).toHaveValue('Example creator')

  const input = screen.getByLabelText('JPEG image') as HTMLInputElement
  expect(input.files?.[0]).toBe(file)
  expect(
    screen.getByRole('button', { name: 'Upload image' }),
  ).toBeEnabled()
})

test('rejects an oversized file before requesting a token', async () => {
  const file = new File(
    [new Uint8Array(10 * 1024 * 1024 + 1)],
    'large.jpg',
    { type: 'image/jpeg' },
  )

  render(<UploadImageForm />)
  await fillForm(file)

  await act(async () => {
    fireEvent.submit(
      screen.getByRole('form', { name: 'Upload image' }),
    )
  })

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Choose a JPEG no larger than 10 MiB.',
  )
  expect(mockedUpload).not.toHaveBeenCalled()
  expect(getSessionToken).not.toHaveBeenCalled()
})

test('prevents duplicate submissions and aborts on unmount', async () => {
  let finish!: (result: ImageUploadResult) => void
  mockedUpload.mockReturnValue(
    new Promise<ImageUploadResult>((resolve) => {
      finish = resolve
    }),
  )

  const view = render(<UploadImageForm />)
  await fillForm()

  await act(async () => {
    const form = screen.getByRole('form', { name: 'Upload image' })
    fireEvent.submit(form)
    fireEvent.submit(form)
  })

  expect(mockedUpload).toHaveBeenCalledOnce()
  expect(screen.getByRole('button')).toBeDisabled()

  const signal = mockedUpload.mock.calls[0][2]
  view.unmount()
  expect(signal.aborted).toBe(true)

  await act(async () => {
    finish({ image_id: 'img_uploaded', status: 'pending' })
  })
})

test('required fields prevent an empty submission', async () => {
  const user = userEvent.setup()
  render(<UploadImageForm />)

  await user.click(
    screen.getByRole('button', { name: 'Upload image' }),
  )

  expect(mockedUpload).not.toHaveBeenCalled()
  expect(getSessionToken).not.toHaveBeenCalled()
})

test('quota rejection preserves the file and creator without reporting success', async () => {
  const message =
    'Your workspace image limit has been reached. Delete an image before uploading another.'

  mockedUpload.mockRejectedValue(new Error(message))
  const onUploaded = vi.fn()

  render(<UploadImageForm onUploaded={onUploaded} />)
  const { file } = await fillForm()

  await act(async () => {
    fireEvent.submit(
      screen.getByRole('form', { name: 'Upload image' }),
    )
  })

  expect(await screen.findByRole('alert')).toHaveTextContent(
    message,
  )
  expect(
    screen.getByRole('textbox', { name: 'Image creator' }),
  ).toHaveValue('Example creator')

  const input = screen.getByLabelText(
    'JPEG image',
  ) as HTMLInputElement
  expect(input.files?.[0]).toBe(file)

  expect(
    screen.getByRole('button', { name: 'Upload image' }),
  ).toBeEnabled()
  expect(onUploaded).not.toHaveBeenCalled()
  expect(screen.queryByText(/Image saved:/)).not.toBeInTheDocument()
  expect(mockedUpload).toHaveBeenCalledOnce()
})