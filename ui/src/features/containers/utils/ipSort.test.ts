import { describe, it, expect } from 'vitest'
import { compareIpAddresses, ipv4ToNumber } from './ipSort'

describe('ipv4ToNumber', () => {
  it('converts dotted quads to a comparable number', () => {
    expect(ipv4ToNumber('0.0.0.0')).toBe(0)
    expect(ipv4ToNumber('0.0.0.1')).toBe(1)
    expect(ipv4ToNumber('0.0.1.0')).toBe(256)
    expect(ipv4ToNumber('255.255.255.255')).toBe(4294967295)
  })

  it('rejects anything that is not a dotted quad', () => {
    expect(ipv4ToNumber(null)).toBeNull()
    expect(ipv4ToNumber(undefined)).toBeNull()
    expect(ipv4ToNumber('')).toBeNull()
    expect(ipv4ToNumber('not-an-ip')).toBeNull()
    expect(ipv4ToNumber('192.168.1')).toBeNull()
    expect(ipv4ToNumber('192.168.1.1.1')).toBeNull()
    expect(ipv4ToNumber('192.168.1.256')).toBeNull()
    expect(ipv4ToNumber('192.168.1.-1')).toBeNull()
    expect(ipv4ToNumber('fd00::1')).toBeNull()
  })

  it('rejects octets with non-numeric content rather than coercing', () => {
    expect(ipv4ToNumber('192.168.1.0x1')).toBeNull()
    expect(ipv4ToNumber('192.168.1. 1')).toBeNull()
    expect(ipv4ToNumber('1e2.168.1.1')).toBeNull()
    // \d is ASCII-only, so full-width digits do not sneak through.
    expect(ipv4ToNumber('１９２.168.1.1')).toBeNull()
  })

  // Leniency is deliberate for a comparator: a slightly non-canonical string
  // is better sorted among its neighbours than exiled to the bottom.
  it('tolerates surrounding whitespace', () => {
    expect(ipv4ToNumber(' 192.168.1.1 ')).toBe(ipv4ToNumber('192.168.1.1'))
  })

  it('reads leading-zero octets as decimal, never octal', () => {
    expect(ipv4ToNumber('010.0.0.1')).toBe(ipv4ToNumber('10.0.0.1'))
    expect(ipv4ToNumber('192.168.001.010')).toBe(ipv4ToNumber('192.168.1.10'))
  })
})

describe('compareIpAddresses', () => {
  const sorted = (ips: Array<string | null>) => [...ips].sort(compareIpAddresses)

  it('orders consecutive addresses numerically, not as text', () => {
    // The reporter's case: a stack whose containers hold consecutive IPs.
    // A string sort puts .10 and .11 ahead of .8 and .9.
    expect(sorted(['192.168.1.11', '192.168.1.9', '192.168.1.10', '192.168.1.8'])).toEqual([
      '192.168.1.8',
      '192.168.1.9',
      '192.168.1.10',
      '192.168.1.11',
    ])
  })

  it('differs from a naive string sort on exactly that case', () => {
    const ips = ['192.168.1.10', '192.168.1.9']
    expect([...ips].sort()).toEqual(['192.168.1.10', '192.168.1.9'])
    expect(sorted(ips)).toEqual(['192.168.1.9', '192.168.1.10'])
  })

  it('orders across octets', () => {
    expect(sorted(['192.168.2.1', '192.168.1.5'])).toEqual(['192.168.1.5', '192.168.2.1'])
    expect(sorted(['192.168.1.1', '10.0.0.1', '172.17.0.5'])).toEqual([
      '10.0.0.1',
      '172.17.0.5',
      '192.168.1.1',
    ])
  })

  it('treats equal addresses as equal', () => {
    expect(compareIpAddresses('172.17.0.5', '172.17.0.5')).toBe(0)
  })

  it('puts containers with no address after those with one', () => {
    expect(sorted(['192.168.1.5', null, '10.0.0.1'])).toEqual([
      '10.0.0.1',
      '192.168.1.5',
      null,
    ])
    expect(compareIpAddresses(null, '10.0.0.1')).toBeGreaterThan(0)
    expect(compareIpAddresses('10.0.0.1', null)).toBeLessThan(0)
  })

  it('treats two missing addresses as equal', () => {
    expect(compareIpAddresses(null, null)).toBe(0)
    expect(compareIpAddresses(null, '')).toBe(0)
  })

  it('keeps unparseable values after parseable ones, ordered predictably', () => {
    // Docker only reports IPv4 here today, but the field is a plain string,
    // so an unexpected value must not scramble the addresses around it.
    expect(sorted(['fd00::2', '192.168.1.5', 'fd00::1'])).toEqual([
      '192.168.1.5',
      'fd00::1',
      'fd00::2',
    ])
  })
})
