export function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface Interval {
  lower: number;
  upper: number;
}

function percentile(sorted: number[], fraction: number): number {
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(fraction * sorted.length) - 1));
  return sorted[index] as number;
}

export function bootstrapInterval(values: number[], samples: number, seed: number): Interval {
  if (values.length === 0) throw new Error("EMPTY_BOOTSTRAP_INPUT");
  if (!Number.isInteger(samples) || samples < 1) throw new Error("INVALID_BOOTSTRAP_SAMPLES");
  const random = mulberry32(seed);
  const means: number[] = [];
  for (let sample = 0; sample < samples; sample += 1) {
    let total = 0;
    for (let index = 0; index < values.length; index += 1) {
      total += values[Math.floor(random() * values.length)] as number;
    }
    means.push(total / values.length);
  }
  means.sort((left, right) => left - right);
  return { lower: percentile(means, 0.025), upper: percentile(means, 0.975) };
}
