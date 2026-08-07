// Container IPs are strings, so the default table comparator orders them as
// text: 192.168.1.10 lands before 192.168.1.9. That breaks exactly the case
// people sort by IP for - a stack whose containers hold consecutive addresses.

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/

/** Numeric value of an IPv4 address, or null if the string is not one.
 *
 * Deliberately lenient about surrounding whitespace and leading zeros: this
 * orders a list rather than validating input, and sorting 010.0.0.1 next to
 * 10.0.0.1 serves the reader better than exiling it to the bottom. Octets are
 * read as decimal, matching what the cell displays - never as octal.
 */
export function ipv4ToNumber(ip: string | null | undefined): number | null {
  if (!ip) return null

  const match = IPV4.exec(ip.trim())
  if (!match) return null

  let value = 0
  for (let i = 1; i <= 4; i++) {
    const octet = Number(match[i])
    if (octet > 255) return null
    value = value * 256 + octet
  }
  return value
}

/**
 * Order two container IPs. Addresses sort numerically; anything unparseable -
 * including a container with no address - sorts after them, and stably among
 * itself so the rows around it do not jump.
 */
export function compareIpAddresses(
  a: string | null | undefined,
  b: string | null | undefined,
): number {
  const left = ipv4ToNumber(a)
  const right = ipv4ToNumber(b)

  if (left !== null && right !== null) return left - right
  if (left !== null) return -1
  if (right !== null) return 1

  return (a || '').localeCompare(b || '')
}
