import { beforeEach, expect, test, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { getPosts } from './api'
import PostPicker from './PostPicker'

vi.mock('./api', () => ({
  getPosts: vi.fn(),
}))

const mockedGetPosts = vi.mocked(getPosts)

beforeEach(() => {
  mockedGetPosts.mockReset()
})

test('loads API posts and forwards the selected ID', async () => {
  const user = userEvent.setup()
  const onSelect = vi.fn()

  mockedGetPosts.mockResolvedValue([
    {
      id: 'custom_001',
      title: 'My uploaded-content post',
      required_subject: 'red fox',
    },
    {
      id: 'custom_002',
      title: 'Another user-created post',
      required_subject: 'motor scooter',
    },
  ])

  render(<PostPicker value="custom_001" onSelect={onSelect} />)

  const dropdown = await screen.findByRole('combobox', {
    name: 'Blog post',
  })

  expect(
    screen.getByRole('option', {
      name: 'My uploaded-content post',
    }),
  ).toBeInTheDocument()

  expect(onSelect).toHaveBeenCalledWith('custom_001')

  await user.selectOptions(dropdown, 'custom_002')

  expect(onSelect).toHaveBeenLastCalledWith('custom_002')
})

test('shows an empty state when the tenant has no posts', async () => {
  const onSelect = vi.fn()
  mockedGetPosts.mockResolvedValue([])

  render(<PostPicker value="" onSelect={onSelect} />)

  expect(
    await screen.findByText('No posts are available yet.'),
  ).toBeInTheDocument()

  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  expect(onSelect).toHaveBeenCalledWith('')
})

test('reloads posts after a failed request', async () => {
  const user = userEvent.setup()
  const onSelect = vi.fn()

  mockedGetPosts
    .mockRejectedValueOnce(new Error('Could not load posts (502).'))
    .mockResolvedValueOnce([
      {
        id: 'custom_003',
        title: 'Recovered post',
        required_subject: 'pizza',
      },
    ])

  render(<PostPicker value="" onSelect={onSelect} />)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not load posts (502).',
  )

  await user.click(
    screen.getByRole('button', { name: 'Reload posts' }),
  )

  expect(
    await screen.findByRole('option', { name: 'Recovered post' }),
  ).toBeInTheDocument()

  await waitFor(() => {
    expect(onSelect).toHaveBeenLastCalledWith('custom_003')
  })

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
