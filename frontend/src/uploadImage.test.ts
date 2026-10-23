import { beforeEach, expect, test, vi } from 'vitest'
import { uploadImage } from './api'
import { apiFetch } from './http'

vi.mock('./http', () => ({
  apiFetch: vi.fn(),
}))

const mockedFetch = vi.mocked(apiFetch)

beforeEach(() => {
  mockedFetch.mockReset()
})

test('sends the file and trimmed creator as multipart form data', async () => {
  mockedFetch.mockResolvedValue(
    new Response(
      JSON.stringify({ image_id: 'img_test', status: 'pending' }),
      { status: 201 },
    ),
  )
  const file = new File(['test'], 'photo.jpg', {
    type: 'image/jpeg',
  })
  const controller = new AbortController()

  const result = await uploadImage(
    file,
    '  Example creator  ',
    controller.signal,
    'synthetic-token',
  )

  expect(result).toEqual({
    image_id: 'img_test',
    status: 'pending',
  })
  expect(mockedFetch).toHaveBeenCalledOnce()

  const [path, signal, token, options] = mockedFetch.mock.calls[0]
  expect(path).toBe('/images')
  expect(signal).toBe(controller.signal)
  expect(token).toBe('synthetic-token')
  expect(options?.method).toBe('POST')
  expect(new Headers(options?.headers).has('Content-Type')).toBe(false)

  const body = options?.body
  expect(body).toBeInstanceOf(FormData)

  const form = body as FormData
  const uploaded = form.get('file') as File
  expect(uploaded.name).toBe('photo.jpg')
  expect(uploaded.size).toBe(file.size)
  expect(form.get('creator')).toBe('Example creator')
})

test.each([
  [413, 'The upload is too large'],
  [422, 'Choose a valid JPEG'],
  [401, 'Please sign in again'],
  [503, 'Could not upload the image (503)'],
] as const)('explains HTTP %s failures', async (status, message) => {
  mockedFetch.mockResolvedValue(new Response(null, { status }))

  await expect(
    uploadImage(
      new File(['test'], 'photo.jpg', { type: 'image/jpeg' }),
      'Example creator',
      new AbortController().signal,
      'synthetic-token',
    ),
  ).rejects.toThrow(message)
})