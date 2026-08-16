/**
 * Returns true if the URL is an external embed (http/https).
 * Local paths (e.g. /assets/video.mp4) return false.
 */
export function isEmbed(url: string): boolean {
  return url.startsWith('http://') || url.startsWith('https://')
}

/**
 * Normalizes a YouTube URL to an embed URL and appends autoplay,
 * mute, loop, and playlist params. Handles youtu.be/ short links,
 * youtube.com/watch?v=, and youtube.com/embed/ URLs.
 * Non-YouTube URLs are returned with the same params appended.
 */
export function buildEmbedUrl(src: string): string {
  if (!isEmbed(src)) return src

  let url = src

  // Normalize short URLs to embed format
  if (url.includes('youtu.be/')) {
    const id = url.split('youtu.be/')[1]?.split(/[?&#]/)[0]
    if (id) url = `https://www.youtube.com/embed/${id}`
  } else if (url.includes('youtube.com/watch')) {
    const id = url.match(/[?&]v=([^&#]+)/)?.[1]
    if (id) url = `https://www.youtube.com/embed/${id}`
  }

  const sep = url.includes('?') ? '&' : '?'
  const params =
    'autoplay=1&mute=1&loop=1&playsinline=1&enablejsapi=1&rel=0&modestbranding=1&vq=hd1440'

  // YouTube requires playlist param for loop to work
  const match = url.match(/youtube\.com\/embed\/([^?&]+)/)
  const playlist = match ? `&playlist=${match[1]}` : ''

  return url + sep + params + playlist
}
