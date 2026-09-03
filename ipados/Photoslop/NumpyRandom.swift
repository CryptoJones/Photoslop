// SPDX-License-Identifier: Apache-2.0
import Foundation

/// NumPy's `SeedSequence` and `PCG64` generator, ported bit for bit so the
/// datamosh filter (#327) rolls the same motion field on iOS as
/// `photoslop.filters._mosh_blocks` rolls on the desktop and in the CLI.
///
/// The whole point of the desktop's seed is that one value lays the same
/// glitch across a set of images, and across platforms. That only holds if
/// the generator is the same generator: `_mosh_blocks` keys three streams by
/// `SeedSequence([seed, row]).spawn(3)` and draws from `default_rng`, which is
/// PCG64 (XSL-RR output, 128-bit LCG state), with `random()` as the top 53
/// bits of a draw and `integers()` as Lemire's bounded method over buffered
/// 32-bit halves. A system generator would silently break that parity, so
/// each piece is reproduced here. `FilterParityTests` proves the sequence
/// against a desktop-generated fixture.
enum NumpyRandom {
  /// `numpy.random.SeedSequence`: entropy words are hashed into a pool and
  /// children spawn by appending their index to the spawn key.
  struct SeedSequence {
    private static let initA: UInt32 = 0x43B0_D7E5
    private static let multA: UInt32 = 0x931E_8875
    private static let initB: UInt32 = 0x8B51_F9DD
    private static let multB: UInt32 = 0x58F3_8DED
    private static let mixMultL: UInt32 = 0xCA01_F9DD
    private static let mixMultR: UInt32 = 0x4973_F715
    private static let xshift: UInt32 = 16
    private static let poolSize = 4

    private let entropy: [UInt32]
    private let spawnKey: [UInt64]
    private var pool: [UInt32]
    private var childrenSpawned: UInt64 = 0

    /// `SeedSequence([values...])`: each non-negative integer contributes its
    /// 32-bit words, least significant first (`_int_to_uint32_array`).
    init(entropy values: [UInt64]) {
      self.init(entropyWords: values.flatMap(Self.words), spawnKey: [])
    }

    private init(entropyWords: [UInt32], spawnKey: [UInt64]) {
      entropy = entropyWords
      self.spawnKey = spawnKey
      pool = [UInt32](repeating: 0, count: Self.poolSize)
      mixEntropy(assembled())
    }

    private static func words(_ value: UInt64) -> [UInt32] {
      if value == 0 { return [0] }
      var out: [UInt32] = []
      var rest = value
      while rest > 0 {
        out.append(UInt32(truncatingIfNeeded: rest))
        rest >>= 32
      }
      return out
    }

    /// `get_assembled_entropy`: the run entropy, padded to the pool size when
    /// a spawn key follows it, then the spawn key's words.
    private func assembled() -> [UInt32] {
      var run = entropy
      let spawn = spawnKey.flatMap(Self.words)
      if !spawn.isEmpty, run.count < Self.poolSize {
        run += [UInt32](repeating: 0, count: Self.poolSize - run.count)
      }
      return run + spawn
    }

    private mutating func mixEntropy(_ words: [UInt32]) {
      var hashConst = Self.initA
      func hashmix(_ input: UInt32) -> UInt32 {
        var value = input ^ hashConst
        hashConst = hashConst &* Self.multA
        value = value &* hashConst
        value ^= value >> Self.xshift
        return value
      }
      func mix(_ x: UInt32, _ y: UInt32) -> UInt32 {
        var result = (Self.mixMultL &* x) &- (Self.mixMultR &* y)
        result ^= result >> Self.xshift
        return result
      }
      let size = Self.poolSize
      for i in 0..<size {
        pool[i] = hashmix(i < words.count ? words[i] : 0)
      }
      for src in 0..<size {
        for dst in 0..<size where src != dst {
          pool[dst] = mix(pool[dst], hashmix(pool[src]))
        }
      }
      if words.count > size {
        for src in size..<words.count {
          for dst in 0..<size {
            pool[dst] = mix(pool[dst], hashmix(words[src]))
          }
        }
      }
    }

    /// `generate_state(n, dtype=np.uint32)`.
    func generateState(words count: Int) -> [UInt32] {
      var hashConst = Self.initB
      var out: [UInt32] = []
      out.reserveCapacity(count)
      for i in 0..<count {
        var value = pool[i % Self.poolSize]
        value ^= hashConst
        hashConst = hashConst &* Self.multB
        value = value &* hashConst
        value ^= value >> Self.xshift
        out.append(value)
      }
      return out
    }

    /// `generate_state(n, dtype=np.uint64)`: pairs of 32-bit words, low first.
    func generateState(doubleWords count: Int) -> [UInt64] {
      let words = generateState(words: 2 * count)
      return (0..<count).map { UInt64(words[2 * $0]) | (UInt64(words[2 * $0 + 1]) << 32) }
    }

    /// `spawn(n)`: children keyed by this sequence's entropy plus their index.
    mutating func spawn(_ count: Int) -> [SeedSequence] {
      var children: [SeedSequence] = []
      for i in 0..<count {
        children.append(
          SeedSequence(entropyWords: entropy, spawnKey: spawnKey + [childrenSpawned + UInt64(i)]))
      }
      childrenSpawned += UInt64(count)
      return children
    }
  }

  /// `numpy.random.PCG64` — the `default_rng` bit generator — with the two
  /// `Generator` draws the datamosh uses.
  struct PCG64 {
    private static let multiplierHigh: UInt64 = 2_549_297_995_355_413_924
    private static let multiplierLow: UInt64 = 4_865_540_595_714_422_341

    private var stateHigh: UInt64 = 0
    private var stateLow: UInt64 = 0
    private var incrementHigh: UInt64
    private var incrementLow: UInt64
    /// `next_uint32` hands out a 64-bit draw in two halves; the high half
    /// waits here for the next call.
    private var bufferedHalf: UInt32?

    /// `PCG64(seed_sequence)`: four 64-bit words of state, the first pair the
    /// initial state (high word first) and the second the stream.
    init(seed: SeedSequence) {
      let words = seed.generateState(doubleWords: 4)
      // inc = (initseq << 1) | 1
      incrementHigh = (words[2] << 1) | (words[3] >> 63)
      incrementLow = (words[3] << 1) | 1
      step()
      let (low, carry) = stateLow.addingReportingOverflow(words[1])
      stateLow = low
      stateHigh = stateHigh &+ words[0] &+ (carry ? 1 : 0)
      step()
    }

    /// `state = state * multiplier + increment`, mod 2^128.
    private mutating func step() {
      let product = stateLow.multipliedFullWidth(by: Self.multiplierLow)
      let high =
        product.high &+ (stateHigh &* Self.multiplierLow) &+ (stateLow &* Self.multiplierHigh)
      let (low, carry) = product.low.addingReportingOverflow(incrementLow)
      stateLow = low
      stateHigh = high &+ incrementHigh &+ (carry ? 1 : 0)
    }

    /// `pcg64_next64`: step, then the XSL-RR output of the new state.
    mutating func next64() -> UInt64 {
      step()
      let value = stateHigh ^ stateLow
      let rotation = UInt64(stateHigh >> 58)
      return (value >> rotation) | (value << ((64 &- rotation) & 63))
    }

    /// `pcg64_next32`: the low half of a draw now, the high half next time.
    mutating func next32() -> UInt32 {
      if let waiting = bufferedHalf {
        bufferedHalf = nil
        return waiting
      }
      let draw = next64()
      bufferedHalf = UInt32(truncatingIfNeeded: draw >> 32)
      return UInt32(truncatingIfNeeded: draw)
    }

    /// `Generator.random()`: the top 53 bits of a draw as a double in [0, 1).
    mutating func nextDouble() -> Double {
      Double(next64() >> 11) * (1.0 / 9_007_199_254_740_992.0)
    }

    /// `Generator.integers(low, high)` for a 64-bit result whose range fits
    /// 32 bits: Lemire's bounded method with rejection, over `next32`.
    /// `high` is exclusive, as in NumPy.
    mutating func integer(low: Int, high: Int) -> Int {
      precondition(high > low, "an empty range has no integers")
      let range = UInt64(high - 1 - low)
      precondition(range < 0xFFFF_FFFF, "ranges wider than 32 bits are not needed here")
      if range == 0 { return low }
      let rangeExclusive = UInt32(range) &+ 1
      var product = UInt64(next32()) * UInt64(rangeExclusive)
      var leftover = UInt32(truncatingIfNeeded: product)
      if leftover < rangeExclusive {
        let threshold = (UInt32.max - UInt32(range)) % rangeExclusive
        while leftover < threshold {
          product = UInt64(next32()) * UInt64(rangeExclusive)
          leftover = UInt32(truncatingIfNeeded: product)
        }
      }
      return low + Int(product >> 32)
    }
  }
}
